from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.database import db
from bot.services import (
    get_spot_balances, get_user_portfolio, pretty_float, get_perps_context, 
    get_hlp_info, _is_buy, calc_avg_entry_from_fills, get_all_assets_meta,
    get_fear_greed_index, get_user_vault_equities
)
from bot.analytics import prepare_modern_market_data
from bot.market_overview import market_overview
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
from aiogram.types import BufferedInputFile, InputMediaPhoto
from bot.locales import _t

logger = logging.getLogger(__name__)
HLP_VAULT_ADDR = "0xdf13098394e1832014b0df3f91285497"

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

def _vault_display_name(vault_address: str) -> str:
    v = str(vault_address or "").lower()
    if not v:
        return "Vault"
    if HLP_VAULT_ADDR[2:] in v:
        return "HLP"
    return f"Vault {v[:6]}"

def _parse_vault_cfg_key(key: str) -> tuple[str, str]:
    if not isinstance(key, str) or "|" not in key:
        return "", ""
    wallet, vault = key.split("|", 1)
    return wallet.lower(), vault.lower()

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

        lang = user.get("lang", "en")
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

        lang = user.get("lang", "en")
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

async def send_scheduled_digests(bot):
    """Check user digest settings every minute and dispatch due digests."""
    now = datetime.datetime.now(datetime.timezone.utc)
    now_hhmm = now.strftime("%H:%M")
    now_dow = now.strftime("%a").lower()[:3]  # mon..sun
    now_dom = now.day

    users = await db.get_all_users()
    due_portfolio_daily: set[int | str] = set()
    due_portfolio_weekly: set[int | str] = set()
    due_hlp_daily: set[int | str] = set()
    due_vault_weekly: set[int | str] = set()
    due_vault_monthly: set[int | str] = set()

    for u in users:
        user_id = u.get("user_id")
        if not user_id:
            continue
        cfg = await db.get_digest_settings(user_id)

        pd = cfg.get("portfolio_daily", {})
        if pd.get("enabled") and pd.get("time") == now_hhmm:
            due_portfolio_daily.add(user_id)

        pw = cfg.get("portfolio_weekly", {})
        if pw.get("enabled") and pw.get("time") == now_hhmm and str(pw.get("day_of_week", "sun")).lower() == now_dow:
            due_portfolio_weekly.add(user_id)

        hd = cfg.get("hlp_daily", {})
        if hd.get("enabled") and hd.get("time") == now_hhmm:
            due_hlp_daily.add(user_id)

        vw = cfg.get("vault_weekly", {})
        if vw.get("enabled") and vw.get("time") == now_hhmm and str(vw.get("day_of_week", "sun")).lower() == now_dow:
            due_vault_weekly.add(user_id)

        vm = cfg.get("vault_monthly", {})
        vm_day = int(vm.get("day", 1) or 1)
        if vm.get("enabled") and vm.get("time") == now_hhmm and vm_day == now_dom:
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
            if isinstance(t_entry, dict):
                t = t_entry["t"]
                is_repeat = t_entry.get("r", True)
            else:
                t = t_entry
                is_repeat = True
            
            if t == now_utc:
                should_send = True
                if not is_repeat:
                    modified = True
                    continue # Don't keep in list if one-time
            
            new_alert_times.append(t_entry)
            
        if should_send:
            users_to_alert.append(user)
            if modified:
                # Update DB to remove one-time alert
                await db.update_user_settings(user["user_id"], {"market_alert_times": new_alert_times})
            
    if not users_to_alert:
        return
        
    logger.info(f"Sending modern market reports to {len(users_to_alert)} users for {now_utc} UTC")
    
    # Fetch market data once
    ctx, hlp_info = await asyncio.gather(
        get_perps_context(),
        get_hlp_info(),
        return_exceptions=True
    )
    
    if isinstance(ctx, Exception) or not ctx or not isinstance(ctx, list) or len(ctx) != 2:
        logger.error("Failed to fetch market context for scheduled reports")
        return
        
    if isinstance(hlp_info, Exception):
        hlp_info = None
        
    universe = []
    if isinstance(ctx[0], dict) and "universe" in ctx[0]:
        universe = ctx[0]["universe"]
    elif isinstance(ctx[0], list):
        universe = ctx[0]
        
    asset_ctxs = ctx[1]
    
    # Prepare data for new templates
    from bot.analytics import prepare_liquidity_data, prepare_coin_prices_data
    data_alpha = prepare_modern_market_data(asset_ctxs, universe, hlp_info)
    data_liq = prepare_liquidity_data(asset_ctxs, universe)
    data_prices = prepare_coin_prices_data(asset_ctxs, universe)
    
    if not data_alpha:
        logger.error("Failed to prepare market data")
        return

    # Render images
    try:
        buf_alpha = await render_html_to_image("market_stats.html", data_alpha)
        buf_liq = await render_html_to_image("liquidity_stats.html", data_liq)
        buf_heat = await render_html_to_image("funding_heatmap.html", data_alpha)
        buf_prices = await render_html_to_image("coin_prices.html", data_prices)
        
        img_alpha = buf_alpha.read()
        img_liq = buf_liq.read()
        img_heat = buf_heat.read()
        img_prices = buf_prices.read()
    except Exception as e:
        logger.error(f"Failed to render market images: {e}")
        return
    
    for user in users_to_alert:
        chat_id = user["user_id"]
        lang = user.get("lang", "en")
        
        # 1. Get detailed info for Majors
        majors_text = ""
        major_symbols = ["BTC", "ETH", "SOL", "HYPE"]
        for sym in major_symbols:
            idx = next((i for i, u in enumerate(universe) if u["name"] == sym), -1)
            if idx != -1:
                ac = asset_ctxs[idx]
                price = float(ac.get("markPx", 0))
                prev_day = float(ac.get("prevDayPx", 0) or price)
                change = ((price - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
                funding = float(ac.get("funding", 0)) * 24 * 365 * 100
                oi = float(ac.get("openInterest", 0)) * price / 1e6
                vol = float(ac.get("dayNtlVlm", 0)) / 1e6
                
                icon = "🟢" if change >= 0 else "🔴"
                majors_text += (
                    f"🔹 <b>{sym}</b>: ${pretty_float(price)} ({icon} {change:+.2f}%)\n"
                    f"   ├ F: <code>{funding:+.1f}% APR</code>\n"
                    f"   └ OI: <b>${oi:.1f}M</b> | Vol: <b>${vol:.1f}M</b>\n\n"
                )

        # 2. Build watchlist text
        watchlist = await db.get_watchlist(chat_id)
        watchlist_lines = []
        if watchlist:
            for sym in watchlist:
                if sym in major_symbols: continue
                idx = next((i for i, u in enumerate(universe) if u["name"] == sym), -1)
                if idx != -1:
                    ac = asset_ctxs[idx]
                    price = float(ac.get("markPx", 0))
                    prev_day = float(ac.get("prevDayPx", 0) or price)
                    change = ((price - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
                    icon = "🟢" if change >= 0 else "🔴"
                    watchlist_lines.append(f"• {sym}: ${pretty_float(price)} ({icon} {change:+.2f}%)")
        
        watchlist_text = ""
        if watchlist_lines:
            watchlist_text = f"⭐ <b>{_t(lang, 'market_report_watchlist')}</b>:\n" + "\n".join(watchlist_lines) + "\n\n"

        # Fetch Fear & Greed Index
        from bot.services import get_fear_greed_index
        fng = await get_fear_greed_index()
        fng_text = ""
        if fng:
            fng_emoji = fng["emoji"]
            fng_val = fng["value"]
            fng_class = fng["classification"]
            fng_change = fng["change"]
            change_icon = "📈" if fng_change > 0 else ("📉" if fng_change < 0 else "➖")
            fng_text = f"🧠 <b>Fear & Greed:</b> {fng_emoji} <b>{fng_val}</b> ({fng_class}) {change_icon} {fng_change:+d}\n\n"

        # Build beautiful text report
        text_report = (
            f"📊 <b>{_t(lang, 'market_alerts_title')}</b>\n\n"
            f"<b>{_t(lang, 'market_report_global')}</b>\n"
            f"• Vol 24h: <b>${data_alpha['global_volume']}</b>\n"
            f"• Total OI: <b>${data_alpha['total_oi']}</b>\n"
            f"• Sentiment: <code>{data_alpha['sentiment_label']}</code>\n"
            f"{fng_text}"
            f"<b>{_t(lang, 'market_report_majors')}</b>\n"
            f"{majors_text}"
            f"{watchlist_text}"
            f"🕒 <i>{_t(lang, 'market_report_footer', time=now_utc + ' UTC')}</i>"
        )
        
        try:
            from aiogram.types import InlineKeyboardButton
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(text=_t(lang, "btn_main_menu"), callback_data="cb_menu"))

            media = [
                InputMediaPhoto(media=BufferedInputFile(img_prices, filename="prices.png")),
                InputMediaPhoto(media=BufferedInputFile(img_heat, filename="heatmap.png")),
                InputMediaPhoto(media=BufferedInputFile(img_alpha, filename="alpha.png")),
                InputMediaPhoto(media=BufferedInputFile(img_liq, filename="liquidity.png"))
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
        
        portf = await get_user_portfolio(wallet)
        if not portf or not isinstance(portf, dict):
            continue
            
        data = portf.get("data", {})
        history = data.get("accountValueHistory", [])
        
        if not history: continue
        
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
        
        if start_val == 0: continue
        
        diff = current_val - start_val
        pct = (diff / start_val) * 100
        
        icon = "🟢" if diff >= 0 else "🔴"
        
        msg = (
            f"☀️ <b>Daily Digest</b>\n"
            f"Wallet: <code>{wallet[:6]}...{wallet[-4:]}</code>\n\n"
            f"💰 Equity: <b>${pretty_float(current_val, 2)}</b>\n"
            f"📅 24h Change: {icon} <b>${pretty_float(diff, 2)}</b> ({pct:+.2f}%)"
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

async def send_scheduled_overviews(bot):
    """
    Checks user schedules for Market Overview and sends report.
    Runs hourly at minute 0 (or close to).
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M")
    logger.info(f"Checking Market Overview schedules for {now_utc} UTC")
    
    users = await db.get_all_users()
    tasks = []
    
    # Pre-filter to see if we need data
    users_to_send = []
    for u in users:
        settings = await db.get_overview_settings(u["user_id"])
        if settings.get("enabled") and now_utc in settings.get("schedules", []):
            users_to_send.append((u["user_id"], settings, u.get("lang", "en")))
            
    if not users_to_send:
        return

    logger.info(f"Sending Market Overview to {len(users_to_send)} users.")

    # 1. Fetch Market Data Global
    try:
        metas = await get_all_assets_meta()
        
        # We prefer Perps prices for the overview
        universe = []
        if metas.get("perps") and "universe" in metas["perps"]:
            universe = metas["perps"]["universe"]
            
        res = {}
        for sym in ["BTC", "ETH"]:
            meta = next((m for m in universe if m.get("name") == sym), None)
            if meta:
                # Perps meta usually has 'markPx' if it's from metaAndAssetCtxs? 
                # Wait, get_perps_meta (type="meta") only returns static info (universe).
                # We need context (prices) which comes from "metaAndAssetCtxs" or "allMids".
                # The scheduler imports 'get_all_assets_meta' which calls 'get_perps_meta' (type='meta').
                # This does NOT contain current price (markPx).
                # We should use 'get_perps_context' or 'get_all_mids' for prices.
                pass 
                
        # Let's fix the fetching strategy completely:
        # We need PRICES and CHANGES. 'get_perps_context' gives us everything for Perps.
        ctx = await get_perps_context() # returns [universe, assetCtxs] usually?
        # get_perps_context implementation: returns json of "metaAndAssetCtxs".
        # This response is usually [universe_list, asset_ctxs_list] (older API) or {"universe": ..., "assetCtxs": ...} (newer)
        # Let's check get_perps_context in services.py... it returns response.json().
        
        # Actually, let's use get_perps_context() as used in send_market_reports:
        # ctx, hlp_info = await asyncio.gather(get_perps_context(), ...)
        # ... universe = ctx[0]["universe"] ...
        
        p_ctx = await get_perps_context()
        p_universe = []
        p_assets = []
        
        if isinstance(p_ctx, list) and len(p_ctx) == 2:
            # Format: [universe, assetCtxs]
            p_universe = p_ctx[0]
            if isinstance(p_universe, dict) and "universe" in p_universe:
                 p_universe = p_universe["universe"]
            p_assets = p_ctx[1]
        elif isinstance(p_ctx, dict):
            p_universe = p_ctx.get("universe", [])
            p_assets = p_ctx.get("assetCtxs", [])
            
        for sym in ["BTC", "ETH"]:
            # Find index
            idx = next((i for i, u in enumerate(p_universe) if u.get("name") == sym), -1)
            if idx != -1 and idx < len(p_assets):
                ac = p_assets[idx]
                p = float(ac.get("markPx", 0))
                prev = float(ac.get("prevDayPx", 0) or p)
                change = ((p - prev)/prev)*100 if prev else 0
                res[sym] = {"price": pretty_float(p), "change": round(change, 2)}
            else:
                res[sym] = {"price": "0", "change": 0.0}
        
        # 24h news/flows (Assume morning = last night news, etc. or just last 24h context)
        # Simplify: Always look back 12-24h for simplicity, or period based.
        # "Morning" implies overnight news. "Evening" implies day news.
        # Let's just fetch last 24h news and let AI decide relevance or fetch smaller window?
        # RSS fetch is fast.
        
        news, flow, fng = await asyncio.gather(
            market_overview.fetch_news_rss(since_timestamp=time.time() - 43200), # 12 hours check
            market_overview.fetch_etf_flows(),
            get_fear_greed_index(),
            return_exceptions=True
        )
        
        if isinstance(news, Exception): news = []
        if isinstance(flow, Exception): flow = {"btc_flow": 0, "eth_flow": 0}
        
        market_data = res
        market_data["btc_etf_flow"] = flow.get("btc_flow", 0)
        market_data["eth_etf_flow"] = flow.get("eth_flow", 0)
        market_data["btc_etf_date"] = flow.get("btc_date", "N/A")
        market_data["eth_etf_date"] = flow.get("eth_date", "N/A")

        # 2. Iterate and Send
        # Optimization: process in batches or individually if prompt differs
        for user_id, cfg, lang in users_to_send:
            try:
                period_label = "MARKET UPDATE"
                h = int(now_utc.split(":")[0])
                if 5 <= h < 12: period_label = "MORNING BRIEF"
                elif 12 <= h < 17: period_label = "MID-DAY UPDATE"
                elif 17 <= h < 22: period_label = "EVENING WRAP"
                
                # ai_summary is now a dict
                ai_data = await market_overview.generate_summary(
                    market_data, 
                    news, 
                    period_label,
                    custom_prompt=cfg.get("prompt_override"),
                    style=cfg.get("style", "detailed"),
                    lang=lang
                )
                
                # Fallback if dict is not returned (error case handled in generate_summary returns dict too)
                if not isinstance(ai_data, dict):
                     ai_data = {"summary": str(ai_data), "sentiment": "Neutral", "next_event": "N/A"}

                summary_text = ai_data.get("summary", "No summary available.")
                sentiment = ai_data.get("sentiment", "Neutral")
                next_event = ai_data.get("next_event", "N/A")

                # --- Calculate Top Movers for Image ---
                def get_change(idx):
                    if idx >= len(p_assets): return 0
                    ac = p_assets[idx]
                    p = float(ac.get("markPx", 0))
                    prev = float(ac.get("prevDayPx", 0) or p)
                    return ((p - prev)/prev)*100 if prev else 0

                mover_indices = [(i, get_change(i)) for i in range(len(p_universe))]
                mover_indices.sort(key=lambda x: x[1], reverse=True)
                
                top_gainer = p_universe[mover_indices[0][0]]["name"]
                top_gainer_pct = mover_indices[0][1]
                
                top_loser = p_universe[mover_indices[-1][0]]["name"]
                top_loser_pct = mover_indices[-1][1]
                
                # Sort by Volume
                vol_indices = [(i, float(p_assets[i].get("dayNtlVlm", 0))) for i in range(len(p_universe)) if i < len(p_assets)]
                vol_indices.sort(key=lambda x: x[1], reverse=True)
                top_vol = p_universe[vol_indices[0][0]]["name"]
                top_vol_val = vol_indices[0][1]
                
                # Sort by Funding
                fund_indices = [(i, float(p_assets[i].get("funding", 0))) for i in range(len(p_universe)) if i < len(p_assets)]
                fund_indices.sort(key=lambda x: x[1], reverse=True)
                top_fund = p_universe[fund_indices[0][0]]["name"]
                top_fund_val = fund_indices[0][1] * 100 * 24 * 365 # APR

                render_data = {
                    "period_label": period_label,
                    "date": datetime.datetime.now().strftime("%d %b %H:%M"),
                    "btc": market_data["BTC"],
                    "eth": market_data["ETH"],
                    "sentiment": sentiment,
                    "fng": fng if fng and not isinstance(fng, Exception) else {"value": 0, "classification": "N/A"},
                    "gemini_model": "3 Flash Preview",
                    
                    # New Data Fields
                    "top_gainer": {"sym": top_gainer, "val": top_gainer_pct},
                    "top_loser": {"sym": top_loser, "val": top_loser_pct},
                    "top_vol": {"sym": top_vol, "val": f"${top_vol_val/1e6:.0f}M"},
                    "top_fund": {"sym": top_fund, "val": f"{top_fund_val:.0f}%"}
                }

                img_buf = await render_html_to_image("market_overview.html", render_data, width=1000, height=1000)
                
                # Construct Header
                btc_d = market_data.get("BTC", {})
                eth_d = market_data.get("ETH", {})
                btc_c = btc_d.get("change", 0.0)
                eth_c = eth_d.get("change", 0.0)
                btc_icon = "🟢" if btc_c >= 0 else "🔴"
                eth_icon = "🟢" if eth_c >= 0 else "🔴"
                
                header = (
                    f"<b>BTC: ${btc_d.get('price', '0')} ({btc_icon} {btc_c:+.2f}%)</b>\n"
                    f"<b>ETH: ${eth_d.get('price', '0')} ({eth_icon} {eth_c:+.2f}%)</b>"
                )
                
                await bot.send_photo(
                    chat_id=user_id,
                    photo=BufferedInputFile(img_buf.read(), filename="overview.png"),
                    caption=f"{header}\n\n<b>VELOX AI ({period_label})</b>",
                    parse_mode="HTML"
                )
                
                # Full Text
                report_text = html.escape(summary_text)
                report_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', report_text)
                report_text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', report_text)
                
                if report_text.strip():
                    await bot.send_message(
                        chat_id=user_id,
                        text=report_text,
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.error(f"Failed to send overview to {user_id}: {e}")
                
    except Exception as e:
        logger.error(f"Scheduled overview broadcast failed: {e}", exc_info=True)


async def run_delta_neutral_alerts(bot):
    """Periodic delta-neutral monitor and safety alerts."""
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

    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        wallets = wallets_by_user.get(user_id, [])
        if not wallets:
            continue

        try:
            snapshot = await collect_delta_neutral_snapshot(wallets, ws=ws, perps_ctx=perps_ctx)
            prev_state = user.get("delta_state", {})
            alerts, new_state = apply_delta_monitoring(
                snapshot,
                previous_state=prev_state,
                now_ts=now_ts,
                interval_hours=0.5,
                emit_alerts=True,
            )
            await db.update_user_settings(user_id, {"delta_state": new_state})

            if not alerts:
                continue

            lang = user.get("lang", "en")
            msg = format_alert_digest(alerts, lang=lang)
            if msg:
                await bot.send_message(user_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Delta-neutral monitor failed for user {user_id}: {e}")

def setup_scheduler(bot):
    scheduler = AsyncIOScheduler()

    # Digest dispatcher: checks user-defined digest times every minute (UTC)
    scheduler.add_job(
        send_scheduled_digests,
        'cron',
        minute='*',
        args=[bot]
    )

    # Vault snapshots: daily at 00:15 UTC
    scheduler.add_job(
        collect_vault_snapshots,
        'cron',
        hour=0,
        minute=15,
        args=[bot]
    )

    scheduler.add_job(
        send_market_reports,
        'cron',
        minute='*', # Every minute
        args=[bot]
    )

    # Market Overview: Hourly check
    scheduler.add_job(
        send_scheduled_overviews,
        'cron',
        minute=0, # Check at top of every hour
        args=[bot]
    )

    scheduler.add_job(
        run_delta_neutral_alerts,
        'cron',
        minute='*/30',
        args=[bot]
    )
    
    scheduler.start()
    return scheduler
