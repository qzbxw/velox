import asyncio
import time
from collections import defaultdict

from bot.services import (
    extract_avg_entry_from_balance,
    get_mid_price,
    get_perps_context,
    get_perps_state,
    get_spot_balances,
    get_symbol_name,
    get_user_funding,
    pretty_float,
)

DELTA_WARN_PCT = 5.0
DELTA_CRIT_PCT = 10.0

MARGIN_GREEN_PCT = 50.0
MARGIN_RED_PCT = 30.0

FUNDING_EXTREME_RATE = 0.001  # 0.1%/hour in decimal
NEGATIVE_FUNDING_STREAK_HOURS = 4.0

PRICE_MOVE_1H_PCT = 10.0
OI_DROP_1H_PCT = 15.0

HISTORY_KEEP_SEC = 8 * 3600


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(symbol: str | None) -> str:
    s = str(symbol or "").upper().strip()
    if not s:
        return ""
    if s.endswith("/USDC"):
        s = s.split("/", 1)[0]
    return s


def _margin_level_icon(margin_health_pct: float) -> tuple[str, str]:
    if margin_health_pct > MARGIN_GREEN_PCT:
        return "green", "🟢"
    if margin_health_pct >= MARGIN_RED_PCT:
        return "yellow", "🟡"
    return "red", "🔴"


def _delta_icon(delta_pct: float) -> str:
    if delta_pct >= DELTA_CRIT_PCT:
        return "🚨"
    if delta_pct >= DELTA_WARN_PCT:
        return "⚠️"
    return "✅"


def _extract_perps_ctx_map(ctx) -> dict[str, dict]:
    universe = []
    asset_ctxs = []
    if isinstance(ctx, list) and len(ctx) == 2:
        raw_universe = ctx[0]
        asset_ctxs = ctx[1] if isinstance(ctx[1], list) else []
        if isinstance(raw_universe, dict):
            universe = raw_universe.get("universe", [])
        elif isinstance(raw_universe, list):
            universe = raw_universe
    elif isinstance(ctx, dict):
        universe = ctx.get("universe", [])
        asset_ctxs = ctx.get("assetCtxs", [])

    out: dict[str, dict] = {}
    if not isinstance(universe, list) or not isinstance(asset_ctxs, list):
        return out

    for i, u in enumerate(universe):
        if i >= len(asset_ctxs):
            break
        if not isinstance(u, dict):
            continue
        sym = _normalize_symbol(u.get("name"))
        if not sym:
            continue
        a = asset_ctxs[i] if isinstance(asset_ctxs[i], dict) else {}
        out[sym] = {
            "markPx": _safe_float(a.get("markPx", 0)),
            "funding": _safe_float(a.get("funding", 0)),
            "openInterest": _safe_float(a.get("openInterest", 0)),
        }
    return out


def _new_coin_bucket(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "price": 0.0,
        "spot_qty": 0.0,
        "spot_value": 0.0,
        "spot_upnl": 0.0,
        "perp_qty": 0.0,
        "short_qty": 0.0,
        "short_notional": 0.0,
        "short_upnl": 0.0,
        "perp_upnl": 0.0,
        "delta_qty": 0.0,
        "delta_usd": 0.0,
        "hedge_base_qty": 0.0,
        "delta_pct": 0.0,
        "funding_current": 0.0,
        "funding_avg_24h": 0.0,
        "funding_avg_7d": 0.0,
        "funding_avg_30d": 0.0,
        "funding_apy_24h": 0.0,
        "funding_apy_7d": 0.0,
        "funding_apy_30d": 0.0,
        "funding_earned_24h": 0.0,
        "funding_earned_7d": 0.0,
        "funding_earned_30d": 0.0,
        "funding_earned_all": 0.0,
        "oi_usd": 0.0,
        "price_change_1h_pct": None,
        "oi_change_1h_pct": None,
        "neg_funding_hours": 0.0,
        "_funding_events": [],
    }


async def _fetch_wallet_data(wallet: str):
    return await asyncio.gather(
        get_spot_balances(wallet),
        get_perps_state(wallet),
        get_user_funding(wallet),
        return_exceptions=True,
    )


async def collect_delta_neutral_snapshot(
    wallets: list[str],
    ws=None,
    perps_ctx=None,
) -> dict:
    now_ts = int(time.time())
    now_ms = now_ts * 1000

    perps_ctx = perps_ctx if perps_ctx is not None else await get_perps_context()
    ctx_map = _extract_perps_ctx_map(perps_ctx)

    wallet_payloads = await asyncio.gather(
        *(_fetch_wallet_data(w) for w in wallets),
        return_exceptions=True,
    )

    coins = defaultdict(dict)
    price_cache: dict[str, float] = {}

    spot_value_total = 0.0
    spot_upnl_total = 0.0
    short_upnl_total = 0.0

    perps_account_value = 0.0
    perps_margin_used = 0.0
    perps_maint_margin = 0.0

    async def resolve_price(sym_raw: str, sym_norm: str, original_id: str | None = None) -> float:
        if sym_norm in price_cache and price_cache[sym_norm] > 0:
            return price_cache[sym_norm]

        px = 0.0
        if ws:
            px = _safe_float(ws.get_price(sym_raw, original_id))
            if px <= 0:
                px = _safe_float(ws.get_price(sym_norm, original_id))

        if px <= 0:
            px = _safe_float(ctx_map.get(sym_norm, {}).get("markPx", 0))

        if px <= 0:
            px = _safe_float(await get_mid_price(sym_raw, original_id))
            if px <= 0 and sym_norm != sym_raw:
                px = _safe_float(await get_mid_price(sym_norm, original_id))

        if px > 0:
            price_cache[sym_norm] = px
        return px

    for payload in wallet_payloads:
        if isinstance(payload, Exception) or not isinstance(payload, list) or len(payload) != 3:
            continue

        spot_bals, perps_state, funding_updates = payload
        if isinstance(spot_bals, Exception):
            spot_bals = []
        if isinstance(perps_state, Exception):
            perps_state = None
        if isinstance(funding_updates, Exception):
            funding_updates = []

        if isinstance(spot_bals, list):
            for b in spot_bals:
                amount = _safe_float(b.get("total", 0))
                if amount <= 0:
                    continue
                coin_id = b.get("coin")
                raw_sym = await get_symbol_name(coin_id, is_spot=True)
                norm_sym = _normalize_symbol(raw_sym)
                if not norm_sym:
                    continue
                if norm_sym == "USDC":
                    # Keep delta view focused on hedged assets; cash buffer is external.
                    continue

                px = await resolve_price(raw_sym, norm_sym, str(coin_id) if coin_id is not None else None)
                val = amount * px
                entry = _safe_float(extract_avg_entry_from_balance(b))
                upnl = (px - entry) * amount if px > 0 and entry > 0 else 0.0

                bucket = coins[norm_sym] if coins[norm_sym] else _new_coin_bucket(norm_sym)
                coins[norm_sym] = bucket
                bucket["price"] = px if px > 0 else bucket["price"]
                bucket["spot_qty"] += amount
                bucket["spot_value"] += val
                bucket["spot_upnl"] += upnl

                spot_value_total += val
                spot_upnl_total += upnl

        if isinstance(perps_state, dict):
            ms = perps_state.get("marginSummary", {}) if isinstance(perps_state.get("marginSummary"), dict) else {}
            perps_account_value += _safe_float(ms.get("accountValue", 0))
            perps_margin_used += _safe_float(ms.get("totalMarginUsed", 0))
            perps_maint_margin += _safe_float(perps_state.get("crossMaintenanceMarginUsed", 0))

            for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {}) if isinstance(p, dict) else {}
                szi = _safe_float(pos.get("szi", 0))
                if szi == 0:
                    continue
                coin_id = pos.get("coin")
                raw_sym = await get_symbol_name(coin_id, is_spot=False)
                norm_sym = _normalize_symbol(raw_sym)
                if not norm_sym:
                    continue

                entry = _safe_float(pos.get("entryPx", 0))
                px = await resolve_price(raw_sym, norm_sym, str(coin_id) if coin_id is not None else None)
                upnl = (px - entry) * szi if px > 0 and entry > 0 else 0.0

                bucket = coins[norm_sym] if coins[norm_sym] else _new_coin_bucket(norm_sym)
                coins[norm_sym] = bucket
                bucket["price"] = px if px > 0 else bucket["price"]
                bucket["perp_qty"] += szi
                bucket["perp_upnl"] += upnl

                if szi < 0:
                    short_qty = abs(szi)
                    bucket["short_qty"] += short_qty
                    bucket["short_notional"] += short_qty * px
                    bucket["short_upnl"] += upnl
                    short_upnl_total += upnl

        if isinstance(funding_updates, list):
            for fu in funding_updates:
                delta = fu.get("delta", {}) if isinstance(fu, dict) else {}
                coin = _normalize_symbol(delta.get("coin"))
                if not coin:
                    continue
                ts_ms = int(_safe_float(fu.get("time", 0)))
                rate = _safe_float(delta.get("fundingRate", 0))
                amount = _safe_float(delta.get("amount", 0))

                bucket = coins[coin] if coins[coin] else _new_coin_bucket(coin)
                coins[coin] = bucket
                bucket["_funding_events"].append((ts_ms, rate, amount))
                bucket["funding_earned_all"] += amount

    cut_24h = now_ms - (24 * 3600 * 1000)
    cut_7d = now_ms - (7 * 24 * 3600 * 1000)
    cut_30d = now_ms - (30 * 24 * 3600 * 1000)

    hedge_base_usd_total = 0.0
    delta_usd_total = 0.0

    for sym, bucket in coins.items():
        bucket["funding_current"] = _safe_float(ctx_map.get(sym, {}).get("funding", 0))
        mark = _safe_float(bucket.get("price", 0))
        if mark <= 0:
            mark = _safe_float(ctx_map.get(sym, {}).get("markPx", 0))
            if mark > 0:
                bucket["price"] = mark

        oi = _safe_float(ctx_map.get(sym, {}).get("openInterest", 0))
        bucket["oi_usd"] = oi * bucket["price"] if bucket["price"] > 0 else 0.0

        events = bucket.get("_funding_events", [])
        e24 = [e for e in events if e[0] >= cut_24h]
        e7 = [e for e in events if e[0] >= cut_7d]
        e30 = [e for e in events if e[0] >= cut_30d]

        def avg_rate(rows: list[tuple[int, float, float]]) -> float:
            if not rows:
                return 0.0
            return sum(r[1] for r in rows) / len(rows)

        def sum_amt(rows: list[tuple[int, float, float]]) -> float:
            return sum(r[2] for r in rows) if rows else 0.0

        bucket["funding_avg_24h"] = avg_rate(e24)
        bucket["funding_avg_7d"] = avg_rate(e7)
        bucket["funding_avg_30d"] = avg_rate(e30)

        bucket["funding_apy_24h"] = bucket["funding_avg_24h"] * 24 * 365 * 100
        bucket["funding_apy_7d"] = bucket["funding_avg_7d"] * 24 * 365 * 100
        bucket["funding_apy_30d"] = bucket["funding_avg_30d"] * 24 * 365 * 100

        bucket["funding_earned_24h"] = sum_amt(e24)
        bucket["funding_earned_7d"] = sum_amt(e7)
        bucket["funding_earned_30d"] = sum_amt(e30)

        bucket["delta_qty"] = bucket["spot_qty"] + bucket["perp_qty"]
        bucket["delta_usd"] = bucket["delta_qty"] * bucket["price"]
        bucket["hedge_base_qty"] = max(
            abs(bucket["spot_qty"]),
            abs(bucket["short_qty"]),
            abs(bucket["perp_qty"]),
        )
        if bucket["hedge_base_qty"] > 0:
            bucket["delta_pct"] = abs(bucket["delta_qty"]) / bucket["hedge_base_qty"] * 100
        else:
            bucket["delta_pct"] = 0.0

        hedge_base_usd = bucket["hedge_base_qty"] * bucket["price"]
        hedge_base_usd_total += hedge_base_usd
        delta_usd_total += bucket["delta_usd"]

    active_coins = []
    for bucket in coins.values():
        if bucket["spot_qty"] > 0 or abs(bucket["perp_qty"]) > 0:
            bucket.pop("_funding_events", None)
            active_coins.append(bucket)

    active_coins.sort(
        key=lambda c: max(abs(c.get("delta_usd", 0)), c.get("spot_value", 0), c.get("short_notional", 0)),
        reverse=True,
    )

    funding_24h_total = sum(_safe_float(c.get("funding_earned_24h", 0)) for c in active_coins)
    funding_7d_total = sum(_safe_float(c.get("funding_earned_7d", 0)) for c in active_coins)
    funding_30d_total = sum(_safe_float(c.get("funding_earned_30d", 0)) for c in active_coins)
    funding_total_active = sum(_safe_float(c.get("funding_earned_all", 0)) for c in active_coins)

    margin_health = 0.0
    margin_util = 0.0
    if perps_account_value > 0:
        margin_util = (perps_margin_used / perps_account_value) * 100
        margin_health = max(0.0, 100.0 - margin_util)
    margin_level, margin_icon = _margin_level_icon(margin_health)

    total_delta_pct = (abs(delta_usd_total) / hedge_base_usd_total * 100) if hedge_base_usd_total > 0 else 0.0

    best_symbol = None
    best_rate = None
    for c in active_coins:
        if c.get("short_qty", 0) <= 0:
            continue
        r = c.get("funding_current", 0)
        if best_rate is None or r > best_rate:
            best_rate = r
            best_symbol = c["symbol"]

    snapshot = {
        "ts": now_ts,
        "wallet_count": len(wallets),
        "coins": active_coins,
        "totals": {
            "portfolio_no_buffer": spot_value_total + short_upnl_total,
            "spot_value": spot_value_total,
            "spot_upnl": spot_upnl_total,
            "short_upnl": short_upnl_total,
            "delta_usd": delta_usd_total,
            "delta_pct": total_delta_pct,
            "delta_icon": _delta_icon(total_delta_pct),
            "margin_health_pct": margin_health,
            "margin_util_pct": margin_util,
            "margin_level": margin_level,
            "margin_icon": margin_icon,
            "perps_account_value": perps_account_value,
            "perps_margin_used": perps_margin_used,
            "perps_maint_margin": perps_maint_margin,
            "funding_today": funding_24h_total,
            "funding_week": funding_7d_total,
            "funding_30d": funding_30d_total,
            "funding_total": funding_total_active,
            "best_symbol": best_symbol,
            "best_rate": best_rate or 0.0,
        },
    }
    return snapshot


def _init_state(previous_state: dict | None) -> dict:
    prev = previous_state if isinstance(previous_state, dict) else {}
    history = prev.get("history", {})
    neg_hours = prev.get("neg_hours", {})
    cooldowns = prev.get("cooldowns", {})
    if not isinstance(history, dict):
        history = {}
    if not isinstance(neg_hours, dict):
        neg_hours = {}
    if not isinstance(cooldowns, dict):
        cooldowns = {}
    return {
        "history": history,
        "neg_hours": neg_hours,
        "cooldowns": cooldowns,
        "updated_at": int(prev.get("updated_at", 0) or 0),
    }


def _latest_point_before(points: list[list[float]], target_ts: int):
    out = None
    for p in points:
        if len(p) != 3:
            continue
        if p[0] <= target_ts:
            out = p
        else:
            break
    return out


def _on_cooldown(cooldowns: dict, key: str, now_ts: int, sec: int) -> bool:
    last_ts = int(_safe_float(cooldowns.get(key, 0)))
    return (now_ts - last_ts) < sec


def _touch_cooldown(cooldowns: dict, key: str, now_ts: int):
    cooldowns[key] = int(now_ts)


def apply_delta_monitoring(
    snapshot: dict,
    previous_state: dict | None = None,
    now_ts: int | None = None,
    interval_hours: float = 0.0,
    emit_alerts: bool = True,
) -> tuple[list[dict], dict]:
    now_ts = int(now_ts if now_ts is not None else time.time())
    state = _init_state(previous_state)
    history = state["history"]
    neg_hours = state["neg_hours"]
    cooldowns = state["cooldowns"]

    alerts: list[dict] = []

    active_symbols = {c.get("symbol") for c in snapshot.get("coins", []) if c.get("symbol")}
    for old_symbol in list(history.keys()):
        if old_symbol not in active_symbols:
            history.pop(old_symbol, None)
    for old_symbol in list(neg_hours.keys()):
        if old_symbol not in active_symbols:
            neg_hours.pop(old_symbol, None)

    for coin in snapshot.get("coins", []):
        sym = coin.get("symbol")
        if not sym:
            continue

        points = history.get(sym, [])
        if not isinstance(points, list):
            points = []
        points.append([now_ts, _safe_float(coin.get("price", 0)), _safe_float(coin.get("oi_usd", 0))])
        points = [p for p in points if isinstance(p, list) and len(p) == 3 and (now_ts - int(p[0])) <= HISTORY_KEEP_SEC]
        points.sort(key=lambda x: x[0])
        history[sym] = points

        ref = _latest_point_before(points, now_ts - 3600)
        if ref and _safe_float(ref[1]) > 0:
            chg_px = ((_safe_float(coin.get("price", 0)) / _safe_float(ref[1])) - 1.0) * 100.0
            coin["price_change_1h_pct"] = chg_px
        else:
            coin["price_change_1h_pct"] = None

        if ref and _safe_float(ref[2]) > 0 and _safe_float(coin.get("oi_usd", 0)) > 0:
            chg_oi = ((_safe_float(coin.get("oi_usd", 0)) / _safe_float(ref[2])) - 1.0) * 100.0
            coin["oi_change_1h_pct"] = chg_oi
        else:
            coin["oi_change_1h_pct"] = None

        nh = _safe_float(neg_hours.get(sym, 0))
        if _safe_float(coin.get("short_qty", 0)) > 0:
            if _safe_float(coin.get("funding_current", 0)) < 0:
                nh += max(0.0, interval_hours)
            else:
                nh = 0.0
        else:
            nh = 0.0
        neg_hours[sym] = round(nh, 3)
        coin["neg_funding_hours"] = nh

        if not emit_alerts:
            continue

        delta_pct = _safe_float(coin.get("delta_pct", 0))
        delta_usd = _safe_float(coin.get("delta_usd", 0))
        if _safe_float(coin.get("hedge_base_qty", 0)) > 0:
            if delta_pct >= DELTA_CRIT_PCT:
                key = f"delta_crit:{sym}"
                if not _on_cooldown(cooldowns, key, now_ts, 1800):
                    _touch_cooldown(cooldowns, key, now_ts)
                    alerts.append({"kind": "delta_critical", "symbol": sym, "delta_pct": delta_pct, "delta_usd": delta_usd})
            elif delta_pct >= DELTA_WARN_PCT:
                key = f"delta_warn:{sym}"
                if not _on_cooldown(cooldowns, key, now_ts, 1800):
                    _touch_cooldown(cooldowns, key, now_ts)
                    alerts.append({"kind": "delta_warning", "symbol": sym, "delta_pct": delta_pct, "delta_usd": delta_usd})

        funding_cur = _safe_float(coin.get("funding_current", 0))
        if _safe_float(coin.get("short_qty", 0)) > 0 and funding_cur < 0:
            key = f"funding_neg:{sym}"
            if not _on_cooldown(cooldowns, key, now_ts, 3600):
                _touch_cooldown(cooldowns, key, now_ts)
                alerts.append({"kind": "funding_negative", "symbol": sym, "funding_current": funding_cur})

            if nh >= NEGATIVE_FUNDING_STREAK_HOURS:
                key_streak = f"funding_neg_4h:{sym}"
                if not _on_cooldown(cooldowns, key_streak, now_ts, 14400):
                    _touch_cooldown(cooldowns, key_streak, now_ts)
                    alerts.append(
                        {
                            "kind": "funding_negative_streak",
                            "symbol": sym,
                            "hours": nh,
                            "funding_current": funding_cur,
                        }
                    )

        if abs(funding_cur) >= FUNDING_EXTREME_RATE:
            key = f"funding_extreme:{sym}"
            if not _on_cooldown(cooldowns, key, now_ts, 3600):
                _touch_cooldown(cooldowns, key, now_ts)
                alerts.append({"kind": "funding_extreme", "symbol": sym, "funding_current": funding_cur})

        px_1h = coin.get("price_change_1h_pct")
        if px_1h is not None and abs(_safe_float(px_1h)) >= PRICE_MOVE_1H_PCT:
            key = f"price_1h:{sym}"
            if not _on_cooldown(cooldowns, key, now_ts, 3600):
                _touch_cooldown(cooldowns, key, now_ts)
                alerts.append({"kind": "price_move_1h", "symbol": sym, "change_pct": _safe_float(px_1h)})

        oi_1h = coin.get("oi_change_1h_pct")
        if oi_1h is not None and _safe_float(oi_1h) <= -OI_DROP_1H_PCT:
            key = f"oi_drop_1h:{sym}"
            if not _on_cooldown(cooldowns, key, now_ts, 3600):
                _touch_cooldown(cooldowns, key, now_ts)
                alerts.append({"kind": "oi_drop_1h", "symbol": sym, "change_pct": _safe_float(oi_1h)})

    if emit_alerts:
        margin_health = _safe_float(snapshot.get("totals", {}).get("margin_health_pct", 0))
        if margin_health < MARGIN_RED_PCT:
            key = "margin_low"
            if not _on_cooldown(cooldowns, key, now_ts, 1800):
                _touch_cooldown(cooldowns, key, now_ts)
                alerts.append({"kind": "margin_low", "margin_health_pct": margin_health})

    state["updated_at"] = now_ts
    state["history"] = history
    state["neg_hours"] = neg_hours
    state["cooldowns"] = cooldowns
    return alerts, state


def _fmt_signed_pct_hour(rate_decimal: float) -> str:
    return f"{(rate_decimal * 100):+.4f}%/h"


def _fmt_signed_pct(rate_decimal: float) -> str:
    return f"{(rate_decimal * 100):+.4f}%"


def format_dashboard_text(snapshot: dict, lang: str = "ru") -> str:
    is_ru = str(lang or "ru").lower().startswith("ru")
    t = snapshot.get("totals", {})
    coins = snapshot.get("coins", [])

    if is_ru:
        lines = [
            "📊 <b>Delta-Neutral Dashboard</b>",
            "━━━━━━━━━━━━━━━━━━━",
            f"💰 Портфель (без буфера): <b>${pretty_float(t.get('portfolio_no_buffer', 0), 2)}</b>",
            f"⚖️ Дельта: <b>${pretty_float(t.get('delta_usd', 0), 2)}</b> ({t.get('delta_pct', 0):.2f}%) {t.get('delta_icon', '✅')}",
            f"📊 Margin: <b>{t.get('margin_health_pct', 0):.1f}%</b> {t.get('margin_icon', '🟢')}",
            f"💸 Фандинг 24ч: <b>${pretty_float(t.get('funding_today', 0), 2)}</b>",
            f"💸 Фандинг 7д: <b>${pretty_float(t.get('funding_week', 0), 2)}</b>",
            f"💸 Фандинг 30д: <b>${pretty_float(t.get('funding_30d', 0), 2)}</b>",
            f"💸 Фандинг всего: <b>${pretty_float(t.get('funding_total', 0), 2)}</b>",
        ]
        if t.get("best_symbol"):
            lines.append(
                f"🏆 Платит больше сейчас: <b>{t['best_symbol']}</b> ({_fmt_signed_pct_hour(t.get('best_rate', 0))})"
            )
    else:
        lines = [
            "📊 <b>Delta-Neutral Dashboard</b>",
            "━━━━━━━━━━━━━━━━━━━",
            f"💰 Portfolio (no buffer): <b>${pretty_float(t.get('portfolio_no_buffer', 0), 2)}</b>",
            f"⚖️ Delta: <b>${pretty_float(t.get('delta_usd', 0), 2)}</b> ({t.get('delta_pct', 0):.2f}%) {t.get('delta_icon', '✅')}",
            f"📊 Margin: <b>{t.get('margin_health_pct', 0):.1f}%</b> {t.get('margin_icon', '🟢')}",
            f"💸 Funding 24h: <b>${pretty_float(t.get('funding_today', 0), 2)}</b>",
            f"💸 Funding 7d: <b>${pretty_float(t.get('funding_week', 0), 2)}</b>",
            f"💸 Funding 30d: <b>${pretty_float(t.get('funding_30d', 0), 2)}</b>",
            f"💸 Funding total: <b>${pretty_float(t.get('funding_total', 0), 2)}</b>",
        ]
        if t.get("best_symbol"):
            lines.append(
                f"🏆 Highest payer now: <b>{t['best_symbol']}</b> ({_fmt_signed_pct_hour(t.get('best_rate', 0))})"
            )

    if coins:
        lines.append("")

    for c in coins:
        delta_icon = _delta_icon(_safe_float(c.get("delta_pct", 0)))
        if is_ru:
            lines.append(
                f"• <b>{c['symbol']}</b> | Δ {c.get('delta_qty', 0):+.4f} (${pretty_float(c.get('delta_usd', 0), 2)}, {c.get('delta_pct', 0):.2f}%) {delta_icon}"
            )
            lines.append(
                f"  Spot: {c.get('spot_qty', 0):.4f} (${pretty_float(c.get('spot_value', 0), 2)}) uPnL {pretty_float(c.get('spot_upnl', 0), 2)}"
            )
            lines.append(
                f"  Short: {c.get('short_qty', 0):.4f} (${pretty_float(c.get('short_notional', 0), 2)}) uPnL {pretty_float(c.get('short_upnl', 0), 2)}"
            )
            lines.append(
                f"  Funding: {_fmt_signed_pct_hour(c.get('funding_current', 0))} | 24h {_fmt_signed_pct(c.get('funding_avg_24h', 0))} | 7d {_fmt_signed_pct(c.get('funding_avg_7d', 0))} | 30d {_fmt_signed_pct(c.get('funding_avg_30d', 0))}"
            )
            lines.append(
                f"  APY(7d): {c.get('funding_apy_7d', 0):+.2f}% | Earned 24h/7d/30d/all: ${pretty_float(c.get('funding_earned_24h', 0), 2)} / ${pretty_float(c.get('funding_earned_7d', 0), 2)} / ${pretty_float(c.get('funding_earned_30d', 0), 2)} / ${pretty_float(c.get('funding_earned_all', 0), 2)}"
            )
            px_ch = c.get("price_change_1h_pct")
            oi_ch = c.get("oi_change_1h_pct")
            if px_ch is not None or oi_ch is not None:
                px_part = f"{px_ch:+.2f}%" if px_ch is not None else "n/a"
                oi_part = f"{oi_ch:+.2f}%" if oi_ch is not None else "n/a"
                lines.append(f"  1h: Price {px_part} | OI {oi_part}")
        else:
            lines.append(
                f"• <b>{c['symbol']}</b> | Δ {c.get('delta_qty', 0):+.4f} (${pretty_float(c.get('delta_usd', 0), 2)}, {c.get('delta_pct', 0):.2f}%) {delta_icon}"
            )
            lines.append(
                f"  Spot: {c.get('spot_qty', 0):.4f} (${pretty_float(c.get('spot_value', 0), 2)}) uPnL {pretty_float(c.get('spot_upnl', 0), 2)}"
            )
            lines.append(
                f"  Short: {c.get('short_qty', 0):.4f} (${pretty_float(c.get('short_notional', 0), 2)}) uPnL {pretty_float(c.get('short_upnl', 0), 2)}"
            )
            lines.append(
                f"  Funding: {_fmt_signed_pct_hour(c.get('funding_current', 0))} | 24h {_fmt_signed_pct(c.get('funding_avg_24h', 0))} | 7d {_fmt_signed_pct(c.get('funding_avg_7d', 0))} | 30d {_fmt_signed_pct(c.get('funding_avg_30d', 0))}"
            )
            lines.append(
                f"  APY(7d): {c.get('funding_apy_7d', 0):+.2f}% | Earned 24h/7d/30d/all: ${pretty_float(c.get('funding_earned_24h', 0), 2)} / ${pretty_float(c.get('funding_earned_7d', 0), 2)} / ${pretty_float(c.get('funding_earned_30d', 0), 2)} / ${pretty_float(c.get('funding_earned_all', 0), 2)}"
            )
            px_ch = c.get("price_change_1h_pct")
            oi_ch = c.get("oi_change_1h_pct")
            if px_ch is not None or oi_ch is not None:
                px_part = f"{px_ch:+.2f}%" if px_ch is not None else "n/a"
                oi_part = f"{oi_ch:+.2f}%" if oi_ch is not None else "n/a"
                lines.append(f"  1h: Price {px_part} | OI {oi_part}")

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3850] + "\n...\n"
    return text


def format_alert_digest(alerts: list[dict], lang: str = "ru") -> str:
    if not alerts:
        return ""

    is_ru = str(lang or "ru").lower().startswith("ru")
    header = "🚨 <b>Delta-Neutral Alerts</b>"
    lines = [header]

    for a in alerts:
        kind = a.get("kind")
        sym = a.get("symbol", "")

        if kind == "delta_critical":
            lines.append(f"⚖️ <b>{sym}</b> дельта {a.get('delta_pct', 0):.2f}% (${pretty_float(a.get('delta_usd', 0), 2)}) > 10%")
        elif kind == "delta_warning":
            lines.append(f"⚖️ <b>{sym}</b> дельта {a.get('delta_pct', 0):.2f}% (${pretty_float(a.get('delta_usd', 0), 2)}) > 5%")
        elif kind == "margin_low":
            lines.append(f"🔴 Margin ratio {a.get('margin_health_pct', 0):.1f}% < 30%")
        elif kind == "funding_negative":
            lines.append(f"💸 <b>{sym}</b> funding отрицательный: {_fmt_signed_pct_hour(a.get('funding_current', 0))}")
        elif kind == "funding_negative_streak":
            lines.append(f"⏰ <b>{sym}</b> funding < 0 уже {a.get('hours', 0):.1f}ч подряд")
        elif kind == "funding_extreme":
            lines.append(f"⚠️ <b>{sym}</b> funding аномальный: {_fmt_signed_pct_hour(a.get('funding_current', 0))}")
        elif kind == "price_move_1h":
            lines.append(f"📈 <b>{sym}</b> движение цены за 1ч: {a.get('change_pct', 0):+.2f}%")
        elif kind == "oi_drop_1h":
            lines.append(f"📉 <b>{sym}</b> OI за 1ч: {a.get('change_pct', 0):+.2f}%")

    if not is_ru:
        lines = [header]
        for a in alerts:
            kind = a.get("kind")
            sym = a.get("symbol", "")
            if kind == "delta_critical":
                lines.append(f"⚖️ <b>{sym}</b> delta drift {a.get('delta_pct', 0):.2f}% (${pretty_float(a.get('delta_usd', 0), 2)}) > 10%")
            elif kind == "delta_warning":
                lines.append(f"⚖️ <b>{sym}</b> delta drift {a.get('delta_pct', 0):.2f}% (${pretty_float(a.get('delta_usd', 0), 2)}) > 5%")
            elif kind == "margin_low":
                lines.append(f"🔴 Margin ratio {a.get('margin_health_pct', 0):.1f}% < 30%")
            elif kind == "funding_negative":
                lines.append(f"💸 <b>{sym}</b> funding turned negative: {_fmt_signed_pct_hour(a.get('funding_current', 0))}")
            elif kind == "funding_negative_streak":
                lines.append(f"⏰ <b>{sym}</b> funding negative for {a.get('hours', 0):.1f}h")
            elif kind == "funding_extreme":
                lines.append(f"⚠️ <b>{sym}</b> abnormal funding: {_fmt_signed_pct_hour(a.get('funding_current', 0))}")
            elif kind == "price_move_1h":
                lines.append(f"📈 <b>{sym}</b> 1h price move: {a.get('change_pct', 0):+.2f}%")
            elif kind == "oi_drop_1h":
                lines.append(f"📉 <b>{sym}</b> 1h OI change: {a.get('change_pct', 0):+.2f}%")

    return "\n".join(lines)
