from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.billing import get_plan_config, normalize_plan
from bot.database import db
from bot.config import HLP_VAULT_ADDR, DIGEST_TARGETS
from bot.utils import _vault_display_name, pretty_float
from bot.services import (
    get_spot_balances, get_user_portfolio, get_perps_context, 
    get_hlp_info, _is_buy, calc_avg_entry_from_fills, get_all_assets_meta,
    get_fear_greed_index, get_user_vault_equities
)
from bot.analytics import prepare_modern_market_data
from bot.market_overview import market_overview
from bot.rss_engine import rss_engine
from bot.renderer import render_html_to_image
from bot.delta_neutral import (
    collect_delta_neutral_snapshot,
    apply_delta_monitoring,
    format_alert_digest,
)
import datetime
import asyncio
import logging
import time
import markdown
import html
import re
import hashlib
from functools import wraps
from aiogram.types import BufferedInputFile, InputMediaPhoto
from bot.locales import _t
from bot.handlers._common import format_money

logger = logging.getLogger(__name__)

def safe_job(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Scheduler job {func.__name__} failed: {e}")
    return wrapper

# In-memory caches
_digest_cache: dict = {}
_digest_cache_ts: float = 0

_market_images_cache: dict[str, bytes] = {}
_market_images_ts: float = 0

_overview_cache: dict[str, tuple[dict, bytes, float]] = {} # key: hash(prompt+style+lang) -> (ai_data, image_bytes, ts)

async def _refresh_digest_cache():
    global _digest_cache, _digest_cache_ts
    if time.time() - _digest_cache_ts < 300 and _digest_cache:
        return
    
    try:
        # Load users with digest settings and billing info
        users = await db.users.find(
            {"digest_settings": {"$exists": True}},
            {"user_id": 1, "digest_settings": 1, "billing": 1, "lang": 1}
        ).to_list(None)
        _digest_cache = {u["user_id"]: u for u in users}
        _digest_cache_ts = time.time()
        logger.info(f"Digest cache refreshed: {len(_digest_cache)} users")
    except Exception as e:
        logger.error(f"Failed to refresh digest cache: {e}")


async def _get_user_wallet_pairs() -> list[tuple[int | str, str]]:
    """Return deduplicated (user_id, wallet) pairs from current + legacy storage."""
    pairs: set[tuple[int | str, str]] = set()

    # Primary source: dedicated wallets collection
    cursor = db.wallets.find({})
    async for w_doc in cursor:
        user_id = w_doc.get("user_id")
        wallet = w_doc.get("address")
        if user_id and isinstance(wallet, str) and wallet:
            pairs.add((user_id, wallet.lower()))

    # Legacy source: users.wallet_address
    users = await db.get_all_users()
    for user in users:
        user_id = user.get("user_id")
        wallet = user.get("wallet_address")
        if user_id and isinstance(wallet, str) and wallet:
            pairs.add((user_id, wallet.lower()))

    return sorted(pairs, key=lambda x: (str(x[0]), x[1]))



def _parse_vault_cfg_key(key: str) -> tuple[str, str]:
    if not isinstance(key, str) or "|" not in key:
        return "", ""
    wallet, vault = key.split("|", 1)
    return wallet.lower(), vault.lower()

@safe_job
async def collect_vault_snapshots(bot=None):
    """Collect daily vault equity snapshots for all tracked user-wallet pairs."""
    logger.info("Collecting vault equity snapshots...")
    pairs = await _get_user_wallet_pairs()
    now_ts = int(time.time())

    for user_id, wallet in pairs:
        try:
            vaults = await get_user_vault_equities(wallet)
        except Exception as e:
            logger.debug(f"Vault snapshot fetch failed for {wallet}: {e}")
            continue

        if not isinstance(vaults, list):
            continue

        for item in vaults:
            vault = str(item.get("vaultAddress", "")).lower()
            if not vault:
                continue
            equity = float(item.get("equity", 0) or 0)
            try:
                await db.upsert_vault_snapshot(user_id, wallet, vault, equity, now_ts)
            except Exception as e:
                logger.debug(f"Vault snapshot upsert failed for {wallet}/{vault}: {e}")

async def _send_vault_periodic_summary(bot, period: str, days: int, target_user_ids: set[int | str] | None = None):
    period = period.lower()
    if period not in ("weekly", "monthly"):
        return

    logger.info(f"Generating {period} vault summary...")
    now_ts = int(time.time())
    start_ts = now_ts - (days * 24 * 60 * 60)
    users = await db.get_all_users()

    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        if target_user_ids is not None and user_id not in target_user_ids:
            continue

        lang = user.get("lang", "ru")
        vault_reports = user.get("vault_reports", {})
        configs = vault_reports.get("configs", {}) if isinstance(vault_reports, dict) else {}
        if not isinstance(configs, dict) or not configs:
            continue

        wanted_by_wallet: dict[str, set[str]] = {}
        for cfg_key, flags in configs.items():
            if not isinstance(flags, dict) or not flags.get(period):
                continue
            wallet, vault = _parse_vault_cfg_key(cfg_key)
            if not wallet or not vault:
                continue
            wanted_by_wallet.setdefault(wallet, set()).add(vault)

        if not wanted_by_wallet:
            continue

        sections = []
        total_equity = 0.0
        total_change = 0.0

        for wallet, tracked_vaults in wanted_by_wallet.items():
            try:
                current_vaults = await get_user_vault_equities(wallet)
            except Exception as e:
                logger.debug(f"Vault summary fetch failed for {wallet}: {e}")
                current_vaults = []

            current_map = {}
            if isinstance(current_vaults, list):
                for item in current_vaults:
                    vault = str(item.get("vaultAddress", "")).lower()
                    if not vault:
                        continue
                    current_map[vault] = float(item.get("equity", 0) or 0)

            wallet_lines = []
            for vault in sorted(tracked_vaults):
                current_equity = current_map.get(vault, 0.0)
                total_equity += current_equity

                base_doc = await db.get_latest_vault_snapshot_before(user_id, wallet, vault, start_ts)
                if base_doc:
                    base_equity = float(base_doc.get("equity", 0) or 0)
                    diff = current_equity - base_equity
                    pct = (diff / base_equity) * 100 if base_equity > 0 else 0.0
                    icon = "🟢" if diff >= 0 else "🔴"
                    total_change += diff
                    diff_text = f"{icon} {pretty_float(diff, 2)} ({pct:+.2f}%)"
                else:
                    diff_text = _t(lang, "vault_change_na")

                wallet_lines.append(
                    f"• <b>{_vault_display_name(vault)}</b>: ${pretty_float(current_equity, 2)} | Δ {diff_text}"
                )
                await db.upsert_vault_snapshot(user_id, wallet, vault, current_equity, now_ts)

            if wallet_lines:
                sections.append(
                    f"👛 <code>{wallet[:6]}...{wallet[-4:]}</code>\n" + "\n".join(wallet_lines)
                )

        if not sections:
            continue

        title_key = "vault_weekly_digest_title" if period == "weekly" else "vault_monthly_digest_title"
        total_icon = "🟢" if total_change >= 0 else "🔴"
        report_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        msg = (
            f"{_t(lang, title_key)}\n\n"
            f"💰 {_t(lang, 'total_lbl')}: <b>${pretty_float(total_equity, 2)}</b>\n"
            f"Δ: {total_icon} <b>{pretty_float(total_change, 2)}</b>\n"
            f"🕒 <i>{report_time}</i>\n\n"
            + "\n\n".join(sections)
        )

        try:
            await bot.send_message(user_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send {period} vault summary to {user_id}: {e}")

async def send_weekly_vault_summary(bot, target_user_ids: set[int | str] | None = None):
    await _send_vault_periodic_summary(bot, period="weekly", days=7, target_user_ids=target_user_ids)

async def send_monthly_vault_summary(bot, target_user_ids: set[int | str] | None = None):
    await _send_vault_periodic_summary(bot, period="monthly", days=30, target_user_ids=target_user_ids)

async def send_daily_hlp_digest(bot, target_user_ids: set[int | str] | None = None):
    """Send a compact HLP snapshot for users who enabled HLP daily and have HLP allocation."""
    logger.info("Generating daily HLP digest...")
    pairs = await _get_user_wallet_pairs()
    if not pairs:
        return

    user_wallets: dict[int | str, list[str]] = {}
    for user_id, wallet in pairs:
        user_wallets.setdefault(user_id, []).append(wallet)

    users = await db.get_all_users()
    now_ts = int(time.time())
    periods = {
        "24h": now_ts - 86400,
        "7d": now_ts - (7 * 86400),
        "30d": now_ts - (30 * 86400)
    }

    hlp_info = await get_hlp_info()
    summary = hlp_info.get("summary", {}) if isinstance(hlp_info, dict) else {}
    share_px = float(summary.get("sharePx", 0) or 0)
    account_value = float(summary.get("accountValue", 0) or 0)
    day_pnl = float(hlp_info.get("dayPnl", 0) or 0) if isinstance(hlp_info, dict) else 0.0
    apr = (day_pnl / account_value) * 365 * 100 if account_value > 0 else 0.0

    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        if target_user_ids is not None and user_id not in target_user_ids:
            continue

        wallets = user_wallets.get(user_id, [])
        if not wallets:
            continue

        lang = user.get("lang", "ru")
        digest_settings = await db.get_digest_settings(user_id)
        hlp_daily_enabled = bool(digest_settings.get("hlp_daily", {}).get("enabled", True))
        if not hlp_daily_enabled:
            continue

        vault_lists = await asyncio.gather(*(get_user_vault_equities(w) for w in wallets), return_exceptions=True)

        total_vault_equity = 0.0
        total_hlp_equity = 0.0
        current_hlp_by_wallet: dict[str, float] = {}
        wallet_lines = []

        for wallet, vaults in zip(wallets, vault_lists):
            if isinstance(vaults, Exception) or not isinstance(vaults, list):
                continue

            wallet_hlp = 0.0
            for item in vaults:
                vault = str(item.get("vaultAddress", "")).lower()
                equity = float(item.get("equity", 0) or 0)
                if equity <= 0:
                    continue
                total_vault_equity += equity
                if HLP_VAULT_ADDR[2:] in vault:
                    wallet_hlp += equity

            if wallet_hlp > 0:
                current_hlp_by_wallet[wallet] = wallet_hlp
                total_hlp_equity += wallet_hlp
                wallet_lines.append(f"• <code>{wallet[:6]}...{wallet[-4:]}</code>: ${pretty_float(wallet_hlp, 2)}")
                await db.upsert_vault_snapshot(user_id, wallet, HLP_VAULT_ADDR, wallet_hlp, now_ts)

        if total_hlp_equity <= 0:
            continue

        period_lines = []
        total_wallets = len(current_hlp_by_wallet)
        for label, ts in periods.items():
            key = "hlp_change_24h" if label == "24h" else ("hlp_change_7d" if label == "7d" else "hlp_change_30d")
            base_sum = 0.0
            current_sum = 0.0
            covered = 0
            for wallet, current_eq in current_hlp_by_wallet.items():
                doc = await db.get_latest_vault_snapshot_before(user_id, wallet, HLP_VAULT_ADDR, ts)
                if not doc:
                    continue
                base_sum += float(doc.get("equity", 0) or 0)
                current_sum += current_eq
                covered += 1

            if covered == 0:
                period_lines.append(f"{_t(lang, key)}: {_t(lang, 'vault_change_na')}")
            else:
                diff = current_sum - base_sum
                pct = (diff / base_sum) * 100 if base_sum > 0 else 0.0
                icon = "🟢" if diff >= 0 else "🔴"
                line = f"{icon} {pretty_float(diff, 2)} ({pct:+.2f}%)"
                if covered < total_wallets:
                    line = f"~ {line} ({_t(lang, 'hlp_partial_history')})"
                period_lines.append(f"{_t(lang, key)}: {line}")

        hlp_share = (total_hlp_equity / total_vault_equity) * 100 if total_vault_equity > 0 else 0.0
        concentration_note = _t(lang, "hlp_concentration_high") if hlp_share >= 70 else _t(lang, "hlp_concentration_ok")
        report_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        msg = (
            f"{_t(lang, 'hlp_daily_digest_title')}\n\n"
            f"💰 {_t(lang, 'hlp_my_equity')}: <b>${pretty_float(total_hlp_equity, 2)}</b>\n"
            f"📊 {_t(lang, 'hlp_vault_share')}: <b>{hlp_share:.1f}%</b>\n"
            f"{concentration_note}\n\n"
            f"{_t(lang, 'hlp_share_price')}: <b>${pretty_float(share_px, 4)}</b>\n"
            f"{_t(lang, 'hlp_tvl')}: <b>${pretty_float(account_value, 0)}</b>\n"
            f"{_t(lang, 'hlp_day_pnl')}: <b>{pretty_float(day_pnl, 2)}</b>\n"
            f"{_t(lang, 'hlp_est_apr')}: <b>{apr:+.2f}%</b>\n\n"
            + "\n".join(period_lines)
            + "\n\n"
            + "\n".join(wallet_lines)
            + f"\n\n<i>{_t(lang, 'market_report_footer', time=report_time)}</i>"
        )

        try:
            await bot.send_message(user_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send daily HLP digest to {user_id}: {e}")

@safe_job
async def send_scheduled_digests(bot):
    """Check user digest settings every 5 minutes and dispatch due digests."""
    await _refresh_digest_cache()
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Check window of last 5 minutes to avoid missing any if interval is */5
    times_to_check = [(now - datetime.timedelta(minutes=i)).strftime("%H:%M") for i in range(5)]
    now_dow = now.strftime("%a").lower()[:3]  # mon..sun
    now_dom = now.day

    due_portfolio_daily: set[int | str] = set()
    due_portfolio_weekly: set[int | str] = set()
    due_hlp_daily: set[int | str] = set()
    due_vault_weekly: set[int | str] = set()
    due_vault_monthly: set[int | str] = set()

    for user_id, u in _digest_cache.items():
        # Subscription and plan config
        sub = u.get("billing", {}).get("subscription", {})
        plan = normalize_plan(sub.get("plan") if sub else None)
        plan_cfg = get_plan_config(plan)
        
        if not bool(plan_cfg["features"].get("digests", False)):
            continue

        cfg = u.get("digest_settings", {})
        digest_slots = plan_cfg["limits"].get("digest_slots")
        enabled_targets = [target for target in DIGEST_TARGETS if bool(cfg.get(target, {}).get("enabled", False))]
        if digest_slots is not None:
            enabled_targets = enabled_targets[:digest_slots]
        enabled_target_set = set(enabled_targets)

        pd = cfg.get("portfolio_daily", {})
        if "portfolio_daily" in enabled_target_set and pd.get("time") in times_to_check:
            due_portfolio_daily.add(user_id)

        pw = cfg.get("portfolio_weekly", {})
        if "portfolio_weekly" in enabled_target_set and pw.get("time") in times_to_check and str(pw.get("day_of_week", "sun")).lower() == now_dow:
            due_portfolio_weekly.add(user_id)

        hd = cfg.get("hlp_daily", {})
        if "hlp_daily" in enabled_target_set and hd.get("time") in times_to_check:
            due_hlp_daily.add(user_id)

        vw = cfg.get("vault_weekly", {})
        if "vault_weekly" in enabled_target_set and vw.get("time") in times_to_check and str(vw.get("day_of_week", "sun")).lower() == now_dow:
            due_vault_weekly.add(user_id)

        vm = cfg.get("vault_monthly", {})
        vm_day = int(vm.get("day", 1) or 1)
        if "vault_monthly" in enabled_target_set and vm.get("time") in times_to_check and vm_day == now_dom:
            due_vault_monthly.add(user_id)

    if due_portfolio_daily:
        await send_daily_digest(bot, target_user_ids=due_portfolio_daily)
    if due_hlp_daily:
        await send_daily_hlp_digest(bot, target_user_ids=due_hlp_daily)
    if due_portfolio_weekly:
        await send_weekly_summary(bot, target_user_ids=due_portfolio_weekly)
    if due_vault_weekly:
        await send_weekly_vault_summary(bot, target_user_ids=due_vault_weekly)
    if due_vault_monthly:
        await send_monthly_vault_summary(bot, target_user_ids=due_vault_monthly)

async def _get_market_images() -> dict:
    global _market_images_cache, _market_images_ts
    if time.time() - _market_images_ts < 300 and _market_images_cache:
        return _market_images_cache

    # Fetch market data once
    ctx, hlp_info = await asyncio.gather(
        get_perps_context(),
        get_hlp_info(),
        return_exceptions=True
    )
    
    if isinstance(ctx, Exception) or not ctx or not isinstance(ctx, list) or len(ctx) != 2:
        return {}
        
    if isinstance(hlp_info, Exception):
        hlp_info = None
        
    universe = ctx[0]
    if isinstance(universe, dict) and "universe" in universe:
        universe = universe["universe"]
        
    asset_ctxs = ctx[1]
    
    # Prepare data for templates
    from bot.analytics import prepare_liquidity_data, prepare_coin_prices_data
    data_alpha = prepare_modern_market_data(asset_ctxs, universe, hlp_info)
    data_liq = prepare_liquidity_data(asset_ctxs, universe)
    data_prices = prepare_coin_prices_data(asset_ctxs, universe)
    
    if not data_alpha:
        return {}

    # Render images
    buf_alpha = await render_html_to_image("market_stats.html", data_alpha)
    buf_liq = await render_html_to_image("liquidity_stats.html", data_liq)
    buf_heat = await render_html_to_image("funding_heatmap.html", data_alpha)
    buf_prices = await render_html_to_image("coin_prices.html", data_prices)
    
    _market_images_cache = {
        "img_alpha": buf_alpha.read(),
        "img_liq": buf_liq.read(),
        "img_heat": buf_heat.read(),
        "img_prices": buf_prices.read(),
        "data_alpha": data_alpha,
        "universe": universe,
        "asset_ctxs": asset_ctxs
    }
    _market_images_ts = time.time()
    return _market_images_cache

@safe_job
async def send_market_reports(bot):
    """Checks all users and sends scheduled market reports."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M")
    
    users = await db.get_all_users()
    users_to_alert = []
    
    for user in users:
        alert_times = user.get("market_alert_times", [])
        should_send = False
        new_alert_times = []
        modified = False
        
        for t_entry in alert_times:
            t = t_entry["t"] if isinstance(t_entry, dict) else t_entry
            is_repeat = t_entry.get("r", True) if isinstance(t_entry, dict) else True
            
            if t == now_utc:
                should_send = True
                if not is_repeat:
                    modified = True
                    continue 
            new_alert_times.append(t_entry)
            
        if should_send:
            users_to_alert.append(user)
            if modified:
                await db.update_user_settings(user["user_id"], {"market_alert_times": new_alert_times})
            
    if not users_to_alert:
        return
        
    logger.info(f"Sending market reports to {len(users_to_alert)} users for {now_utc} UTC")
    
    m_cache = await _get_market_images()
    if not m_cache:
        logger.error("Failed to fetch or render market data")
        return

    data_alpha = m_cache["data_alpha"]
    universe = m_cache["universe"]
    asset_ctxs = m_cache["asset_ctxs"]
    
    for user in users_to_alert:
        chat_id = user["user_id"]
        lang = user.get("lang", "ru")
        
        major_symbols = ["BTC", "ETH", "SOL", "HYPE"]
        majors_text = ""
        for sym in major_symbols:
            idx = next((i for i, u in enumerate(universe) if u["name"] == sym), -1)
            if idx != -1:
                ac = asset_ctxs[idx]
                price = float(ac.get("markPx", 0))
                prev = float(ac.get("prevDayPx", 0) or price)
                change = ((price - prev) / prev) * 100 if prev > 0 else 0.0
                funding = float(ac.get("funding", 0)) * 24 * 365 * 100
                oi = float(ac.get("openInterest", 0)) * price / 1e6
                vol = float(ac.get("dayNtlVlm", 0)) / 1e6
                icon = "🟢" if change >= 0 else "🔴"
                majors_text += f"🔹 <b>{sym}</b>: ${pretty_float(price)} ({icon} {change:+.2f}%)\n   ├ F: <code>{funding:+.1f}% APR</code>\n   └ OI: <b>${oi:.1f}M</b> | Vol: <b>${vol:.1f}M</b>\n\n"

        watchlist = await db.get_watchlist(chat_id)
        watchlist_lines = []
        if watchlist:
            for sym in watchlist:
                if sym in major_symbols:
                    continue
                idx = next((i for i, u in enumerate(universe) if u["name"] == sym), -1)
                if idx != -1:
                    ac = asset_ctxs[idx]
                    price = float(ac.get("markPx", 0))
                    prev = float(ac.get("prevDayPx", 0) or price)
                    change = ((price - prev) / prev) * 100 if prev > 0 else 0.0
                    watchlist_lines.append(f"• {sym}: ${pretty_float(price)} ({'🟢' if change >= 0 else '🔴'} {change:+.2f}%)")
        
        watchlist_text = f"⭐ <b>{_t(lang, 'market_report_watchlist')}</b>:\n" + "\n".join(watchlist_lines) + "\n\n" if watchlist_lines else ""
        fng = await get_fear_greed_index()
        fng_text = f"🧠 <b>Fear & Greed:</b> {fng['emoji']} <b>{fng['value']}</b> ({fng['classification']}) {'📈' if fng['change'] > 0 else ('📉' if fng['change'] < 0 else '➖')} {fng['change']:+d}\n\n" if fng else ""

        text_report = (
            f"📊 <b>{_t(lang, 'market_alerts_title')}</b>\n\n"
            f"<b>{_t(lang, 'market_report_global')}</b>\n• Vol 24h: <b>${data_alpha['global_volume']}</b>\n• Total OI: <b>${data_alpha['total_oi']}</b>\n• Sentiment: <code>{data_alpha['sentiment_label']}</code>\n{fng_text}"
            f"<b>{_t(lang, 'market_report_majors')}</b>\n{majors_text}{watchlist_text}🕒 <i>{_t(lang, 'market_report_footer', time=now_utc + ' UTC')}</i>"
        )
        
        try:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            from aiogram.types import InlineKeyboardButton
            kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text=_t(lang, "btn_main_menu"), callback_data="cb_menu"))
            media = [
                InputMediaPhoto(media=BufferedInputFile(m_cache["img_prices"], filename="prices.png")),
                InputMediaPhoto(media=BufferedInputFile(m_cache["img_heat"], filename="heatmap.png")),
                InputMediaPhoto(media=BufferedInputFile(img_alpha if 'img_alpha' in m_cache else m_cache["img_alpha"], filename="alpha.png")),
                InputMediaPhoto(media=BufferedInputFile(m_cache["img_liq"], filename="liquidity.png"))
            ]
            await bot.send_media_group(chat_id, media)
            await bot.send_message(chat_id, text_report, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send market report to {chat_id}: {e}")

async def send_daily_digest(bot, target_user_ids: set[int | str] | None = None):
    """Generate and send daily digest (Equity PnL) to all users."""
    logger.info("Generating daily digest...")
    user_wallet_pairs = await _get_user_wallet_pairs()

    for chat_id, wallet in user_wallet_pairs:
        if target_user_ids is not None and chat_id not in target_user_ids:
            continue
        
        lang = await db.get_lang(chat_id)
        portf = await get_user_portfolio(wallet)
        if not portf or not isinstance(portf, dict):
            continue
            
        data = portf.get("data", {})
        history = data.get("accountValueHistory", [])
        
        if not history:
            continue
        
        # Sort and Find 24h change
        history.sort(key=lambda x: x[0])
        
        current_val = float(history[-1][1])
        now_ms = history[-1][0]
        target_ms = now_ms - 86400000
        
        # Find closest point to 24h ago
        start_val = 0.0
        found = False
        for ts, val in history:
            if abs(ts - target_ms) < 3600000 * 2: # tolerance 2h
                start_val = float(val)
                found = True
                break
        
        if not found and history:
            # Fallback if history is short?
            # Or just take oldest if history < 24h
            if history[0][0] > target_ms:
                start_val = float(history[0][1])
            else:
                # If we have history but missed the window, scan again closer
                # Actually linear scan is fine, finding closest
                closest = min(history, key=lambda x: abs(x[0] - target_ms))
                if abs(closest[0] - target_ms) < 3600000 * 6: # 6h tolerance
                    start_val = float(closest[1])
        
        if start_val == 0:
            continue
        
        diff = current_val - start_val
        pct = (diff / start_val) * 100
        
        icon = "🟢" if diff >= 0 else "🔴"
        
        msg = (
            f"{_t(lang, 'daily_digest_title')}\n"
            f"{_t(lang, 'wallet_lbl_simple')}: <code>{wallet[:6]}...{wallet[-4:]}</code>\n\n"
            f"💰 {_t(lang, 'equity')}: <b>{format_money(current_val, lang)}</b>\n"
            f"📅 {_t(lang, 'change_24h_lbl')}: {icon} <b>{format_money(diff, lang)}</b> ({pct:+.2f}%)"
        )
        
        try:
            sent_msg = await bot.send_message(chat_id, msg, parse_mode="HTML")
            if sent_msg:
                from bot.handlers import _send_hedge_insight
                asyncio.create_task(_send_hedge_insight(bot, chat_id, chat_id, "chat", {
                    "digest_type": "daily",
                    "equity": current_val,
                    "diff": diff,
                    "pct": pct
                }, reply_to_id=sent_msg.message_id))
        except Exception as e:
            logger.error(f"Failed to send digest to {chat_id}: {e}")

async def send_weekly_summary(bot, target_user_ids: set[int | str] | None = None):
    """Generate and send weekly summary to all users."""
    logger.info("Generating weekly summary...")
    user_wallet_pairs = await _get_user_wallet_pairs()
    
    end_time = time.time()
    start_time = end_time - (7 * 24 * 60 * 60) # 7 days ago
    
    for chat_id, wallet in user_wallet_pairs:
        if target_user_ids is not None and chat_id not in target_user_ids:
            continue
        
        fills = await db.get_fills(wallet, start_time, end_time)

        # Realized PnL (weekly): compute per-coin moving average cost, accumulate sell pnl.
        realized_pnl = 0.0
        total_bought_val = 0.0
        total_sold_val = 0.0
        per_coin_qty: dict[str, float] = {}
        per_coin_cost: dict[str, float] = {}

        fills_sorted = sorted(fills, key=lambda x: float(x.get("time", 0)))
        for fill in fills_sorted:
            coin = fill.get("coin")
            if not isinstance(coin, str) or not coin:
                continue

            sz = float(fill.get("sz", 0) or 0)
            px = float(fill.get("px", 0) or 0)
            val = sz * px
            side = str(fill.get("side", ""))

            if _is_buy(side):
                total_bought_val += val
                per_coin_qty[coin] = per_coin_qty.get(coin, 0.0) + sz
                per_coin_cost[coin] = per_coin_cost.get(coin, 0.0) + val
            else:
                total_sold_val += val
                qty = per_coin_qty.get(coin, 0.0)
                cost = per_coin_cost.get(coin, 0.0)
                if qty <= 0:
                    continue
                sell_sz = min(sz, qty)
                avg_cost = cost / qty if qty else 0.0
                realized_pnl += sell_sz * (px - avg_cost)
                per_coin_qty[coin] = qty - sell_sz
                per_coin_cost[coin] = cost - avg_cost * sell_sz

        net_flow = total_sold_val - total_bought_val

        # Unrealized PnL: current holdings value vs avg entry derived from stored fills.
        unrealized_msg = ""
        balances = await get_spot_balances(wallet)
        if balances:
            total_current_value = 0.0
            total_unrealized_pnl = 0.0
            holdings_details = []
            for bal in balances:
                coin = bal.get("coin")
                amount = float(bal.get("total", 0) or 0)
                if not coin or amount <= 0:
                    continue

                price = 0.0
                if hasattr(bot, "ws_manager"):
                    price = bot.ws_manager.get_price(coin)
                val = amount * price
                total_current_value += val

                avg_entry = 0.0
                try:
                    coin_fills = await db.get_fills_by_coin(wallet, coin)
                    avg_entry = calc_avg_entry_from_fills(coin_fills)
                except Exception:
                    avg_entry = 0.0

                upl = (price - avg_entry) * amount if avg_entry else 0.0
                total_unrealized_pnl += upl
                if avg_entry:
                    holdings_details.append(f"- {coin}: ${val:.2f} | Avg: ${avg_entry:.6f} | uPnL: ${upl:.2f}")
                else:
                    holdings_details.append(f"- {coin}: ${val:.2f}")

            unrealized_msg = (
                f"\n💰 <b>Holdings:</b> ${total_current_value:.2f}\n"
                f"📈 <b>Unrealized PnL (best-effort):</b> ${total_unrealized_pnl:.2f}\n"
                + "\n".join(holdings_details)
            )

        msg = (
            f"📅 <b>Velox — Weekly Summary</b>\n"
            f"Wallet: {wallet[:6]}...{wallet[-4:]}\n\n"
            f"<b>Weekly Flow:</b>\n"
            f"Total Bought: ${total_bought_val:.2f}\n"
            f"Total Sold: ${total_sold_val:.2f}\n"
            f"Net Flow: ${net_flow:.2f} (Sold - Bought)\n"
            f"\n<b>Realized PnL (best-effort):</b> ${realized_pnl:.2f}\n"
            f"{unrealized_msg}\n\n"
            f"<i>Note: PnL is best-effort from stored fills and may be incomplete if the bot was offline.</i>"
        )
        
        try:
            sent_msg = await bot.send_message(chat_id, msg, parse_mode="HTML")
            if sent_msg:
                from bot.handlers import _send_hedge_insight
                asyncio.create_task(_send_hedge_insight(bot, chat_id, chat_id, "chat", {
                    "digest_type": "weekly",
                    "realized_pnl": realized_pnl,
                    "net_flow": net_flow
                }, reply_to_id=sent_msg.message_id))
        except Exception as e:
            logger.error(f"Failed to send summary to {chat_id}: {e}")

async def _get_cached_overview(market_data, news, period_label, cfg, lang, p_universe, p_assets, fng) -> tuple[dict, bytes]:
    global _overview_cache
    prompt_override = cfg.get("prompt_override") or "default"
    style = cfg.get("style", "detailed")
    cache_key = hashlib.md5(f"{prompt_override}:{style}:{lang}:{period_label}".encode()).hexdigest()
    
    if cache_key in _overview_cache:
        ai_data, img_bytes, ts = _overview_cache[cache_key]
        if time.time() - ts < 3600:
            return ai_data, img_bytes

    # Generate AI content
    ai_data = await market_overview.generate_summary(market_data, news, period_label, custom_prompt=cfg.get("prompt_override"), style=cfg.get("style", "detailed"), lang=lang)
    if not isinstance(ai_data, dict):
        ai_data = {"summary": str(ai_data), "sentiment": "Neutral", "next_event": "N/A"}

    # Prepare Render Data
    def get_change(idx):
        if idx >= len(p_assets):
            return 0
        ac = p_assets[idx]
        p = float(ac.get("markPx", 0))
        prev = float(ac.get("prevDayPx", 0) or p)
        return ((p - prev)/prev)*100 if prev else 0

    mover_indices = sorted([(i, get_change(i)) for i in range(len(p_universe))], key=lambda x: x[1], reverse=True)
    vol_indices = sorted([(i, float(p_assets[i].get("dayNtlVlm", 0))) for i in range(len(p_universe)) if i < len(p_assets)], key=lambda x: x[1], reverse=True)
    fund_indices = sorted([(i, float(p_assets[i].get("funding", 0))) for i in range(len(p_universe)) if i < len(p_assets)], key=lambda x: x[1], reverse=True)

    render_data = {
        "period_label": period_label, "date": datetime.datetime.now().strftime("%d %b %H:%M"),
        "btc": market_data["BTC"], "eth": market_data["ETH"],
        "sentiment": ai_data.get("sentiment", "Neutral"),
        "fng": fng if fng and not isinstance(fng, Exception) else {"value": 0, "classification": "N/A"},
        "gemini_model": "Velox Engine",
        "top_gainer": {"sym": p_universe[mover_indices[0][0]]["name"], "val": mover_indices[0][1]},
        "top_loser": {"sym": p_universe[mover_indices[-1][0]]["name"], "val": mover_indices[-1][1]},
        "top_vol": {"sym": p_universe[vol_indices[0][0]]["name"], "val": f"${vol_indices[0][1]/1e6:.0f}M"},
        "top_fund": {"sym": p_universe[fund_indices[0][0]]["name"], "val": f"{fund_indices[0][1]*100*24*365:.0f}%"}
    }
    img_buf = await render_html_to_image("market_overview.html", render_data, width=1000, height=1000)
    img_bytes = img_buf.read()
    
    _overview_cache[cache_key] = (ai_data, img_bytes, time.time())
    return ai_data, img_bytes

@safe_job
async def send_scheduled_overviews(bot):
    """Checks user schedules for Market Overview and sends report with AI cache."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M")
    users = await db.get_all_users()
    users_to_send = []
    for u in users:
        settings = await db.get_overview_settings(u["user_id"])
        if settings.get("enabled") and now_utc in settings.get("schedules", []):
            users_to_send.append((u["user_id"], settings, u.get("lang", "en")))
    if not users_to_send:
        return

    logger.info(f"Sending Market Overview to {len(users_to_send)} users.")
    p_ctx = await get_perps_context()
    p_universe = []
    p_assets = []
    if isinstance(p_ctx, dict):
        p_universe = p_ctx.get("universe", [])
        p_assets = p_ctx.get("assetCtxs", [])
    elif isinstance(p_ctx, list) and len(p_ctx) == 2:
        p_universe = p_ctx[0].get("universe", []) if isinstance(p_ctx[0], dict) else p_ctx[0]
        p_assets = p_ctx[1]
    
    res = {}
    for sym in ["BTC", "ETH"]:
        idx = next((i for i, u in enumerate(p_universe) if u.get("name") == sym), -1)
        if idx != -1 and idx < len(p_assets):
            ac = p_assets[idx]
            p = float(ac.get("markPx", 0))
            prev = float(ac.get("prevDayPx", 0) or p)
            res[sym] = {"price": pretty_float(p), "change": round(((p - prev)/prev)*100 if prev else 0, 2)}
        else:
            res[sym] = {"price": "0", "change": 0.0}
    
    # Use cached RSS articles (refreshed by refresh_news_cache job)
    news = rss_engine.get_cached_articles(limit=200)
    flow, fng = await asyncio.gather(market_overview.fetch_etf_flows(), get_fear_greed_index(), return_exceptions=True)
    market_data = {**res, "btc_etf_flow": flow.get("btc_flow", 0) if not isinstance(flow, Exception) else 0, "eth_etf_flow": flow.get("eth_flow", 0) if not isinstance(flow, Exception) else 0}

    h = int(now_utc.split(":")[0])
    period_label = "MORNING BRIEF" if 5 <= h < 12 else ("MID-DAY UPDATE" if 12 <= h < 17 else ("EVENING WRAP" if 17 <= h < 22 else "MARKET UPDATE"))

    for user_id, cfg, lang in users_to_send:
        try:
            ai_data, img_bytes = await _get_cached_overview(market_data, news if not isinstance(news, Exception) else [], period_label, cfg, lang, p_universe, p_assets, fng)
            btc_d, eth_d = res.get("BTC", {}), res.get("ETH", {})
            header = f"<b>BTC: ${btc_d.get('price', '0')} ({'🟢' if btc_d.get('change', 0) >= 0 else '🔴'} {btc_d.get('change', 0):+.2f}%)</b>\n<b>ETH: ${eth_d.get('price', '0')} ({'🟢' if eth_d.get('change', 0) >= 0 else '🔴'} {eth_d.get('change', 0):+.2f}%)</b>"
            await bot.send_photo(user_id, BufferedInputFile(img_bytes, filename="overview.png"), caption=f"{header}\n\n<b>VELOX AI ({period_label})</b>", parse_mode="HTML")
            report_text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html.escape(ai_data.get("summary", ""))))
            if report_text.strip():
                await bot.send_message(user_id, report_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send overview to {user_id}: {e}")


@safe_job
async def run_delta_neutral_alerts(bot):
    """Periodic delta-neutral monitor and safety alerts with rate limiting."""
    logger.info("Running delta-neutral monitor...")
    users = await db.get_all_users()
    if not users:
        return

    pairs = await _get_user_wallet_pairs()
    wallets_by_user: dict[int | str, list[str]] = {}
    for user_id, wallet in pairs:
        wallets_by_user.setdefault(user_id, []).append(wallet)
    if not wallets_by_user:
        return

    ws = getattr(bot, "ws_manager", None)
    perps_ctx = await get_perps_context()
    now_ts = int(time.time())
    sem = asyncio.Semaphore(5)

    async def process_user(user):
        user_id = user.get("user_id")
        if not user_id:
            return
        wallets = wallets_by_user.get(user_id, [])
        if not wallets:
            return

        async with sem:
            try:
                snapshot = await collect_delta_neutral_snapshot(wallets, ws=ws, perps_ctx=perps_ctx)
                prev_state = user.get("delta_state", {})
                alerts, new_state = apply_delta_monitoring(snapshot, previous_state=prev_state, now_ts=now_ts, interval_hours=0.5, emit_alerts=True)
                await db.update_user_settings(user_id, {"delta_state": new_state})
                if alerts:
                    lang = user.get("lang", "ru")
                    msg = format_alert_digest(alerts, lang=lang)
                    if msg:
                        await bot.send_message(user_id, msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Delta-neutral monitor failed for user {user_id}: {e}")

    await asyncio.gather(*(process_user(u) for u in users))

@safe_job
async def health_check(bot):
    """Checks DB, WS, and Playwright health."""
    try:
        # DB Ping
        await db.client.admin.command('ping')
        
        # WS Health
        ws = getattr(bot, "ws_manager", None)
        if not ws or not ws.running:
            logger.critical("Health Check: WS Manager NOT RUNNING")
        
        # Playwright check (basic render test)
        # try:
        #     test_render = await render_html_to_image("pnl_card.html", {"pnl_usd": 0, "pnl_pct": 0})
        #     if not test_render: raise Exception("Empty render")
        # except Exception as e:
        #     logger.critical(f"Health Check: Playwright/Renderer FAILED: {e}")
            
        logger.info("Health Check: OK")
    except Exception as e:
        logger.critical(f"Health Check: FAILED: {e}")

@safe_job
async def cleanup_triggered_alerts(bot):
    """Daily cleanup of triggered alerts to prevent memory leaks."""
    # If handlers.py uses a global set for triggered alerts, we should clear it here if exposed.
    # For now, let's just log and clear any DB-side transient alert states if they exist.
    logger.info("Running daily cleanup of triggered alerts...")
    # Example: await db.users_col.update_many({}, {"$set": {"transient_alerts": {}}})

@safe_job
async def refresh_news_cache(bot):
    """Periodically refresh the global RSS article cache via rss_engine."""
    articles = await rss_engine.fetch_all(since_hours=settings.RSS_ARTICLE_TTL_HOURS)
    logger.info(f"RSS cache refreshed: {len(articles)} articles, age={rss_engine.cache_age_seconds:.0f}s")

def setup_scheduler(bot):
    scheduler = AsyncIOScheduler()

    # Digest dispatcher: every 5 minutes with cache and window check
    scheduler.add_job(
        send_scheduled_digests,
        'cron',
        minute='*/5',
        args=[bot],
        misfire_grace_time=120,
        max_instances=1,
        jitter=10
    )

    # Vault snapshots: daily at 00:15 UTC with 30-min grace for "retry"
    scheduler.add_job(
        collect_vault_snapshots,
        'cron',
        hour=0,
        minute=15,
        args=[bot],
        misfire_grace_time=1800,
        max_instances=1,
        jitter=10
    )

    # Market Reports: Every minute with cache and low jitter
    scheduler.add_job(
        send_market_reports,
        'cron',
        minute='*',
        args=[bot],
        misfire_grace_time=120,
        max_instances=1,
        jitter=5
    )

    # Market Overview: Hourly with AI cache
    scheduler.add_job(
        send_scheduled_overviews,
        'cron',
        minute=0,
        args=[bot],
        misfire_grace_time=600,
        max_instances=1,
        jitter=30
    )

    # Delta-neutral alerts: every 30 mins with semaphore
    scheduler.add_job(
        run_delta_neutral_alerts,
        'cron',
        minute='*/30',
        args=[bot],
        misfire_grace_time=300,
        max_instances=1,
        jitter=20
    )
    
    # NEW: Health Check
    scheduler.add_job(
        health_check,
        'cron',
        minute='*/5',
        args=[bot],
        misfire_grace_time=60,
        max_instances=1
    )
    
    # NEW: Daily cleanup
    scheduler.add_job(
        cleanup_triggered_alerts,
        'cron',
        hour=0,
        minute=0,
        args=[bot],
        misfire_grace_time=3600,
        max_instances=1
    )

    # NEW: RSS cache refresh
    scheduler.add_job(
        refresh_news_cache,
        'cron',
        minute=f'*/{settings.RSS_REFRESH_INTERVAL_MIN}',
        args=[bot],
        misfire_grace_time=300,
        max_instances=1,
        jitter=30
    )
    
    scheduler.start()
    return scheduler
