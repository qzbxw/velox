from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.database import db
from bot.services import (
    get_spot_balances, get_user_portfolio, pretty_float, get_perps_context, 
    get_hlp_info, _is_buy, calc_avg_entry_from_fills
)
from bot.analytics import prepare_modern_market_data
from bot.renderer import render_html_to_image
import datetime
import asyncio
import logging
import time
from aiogram.types import BufferedInputFile, InputMediaPhoto
from bot.locales import _t

logger = logging.getLogger(__name__)

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

        # Build beautiful text report
        text_report = (
            f"📊 <b>{_t(lang, 'market_alerts_title')}</b>\n\n"
            f"<b>{_t(lang, 'market_report_global')}</b>\n"
            f"• Vol 24h: <b>${data_alpha['global_volume']}</b>\n"
            f"• Total OI: <b>${data_alpha['total_oi']}</b>\n"
            f"• Sentiment: <code>{data_alpha['sentiment_label']}</code>\n\n"
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

async def send_daily_digest(bot):
    """Generate and send daily digest (Equity PnL) to all users."""
    logger.info("Generating daily digest...")
    users = await db.get_all_users()
    
    for user in users:
        chat_id = user.get("chat_id")
        wallet = user.get("wallet_address")
        
        if not wallet or not chat_id: continue
        
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
            await bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send digest to {chat_id}: {e}")

async def send_weekly_summary(bot):
    """Generate and send weekly summary to all users."""
    logger.info("Generating weekly summary...")
    users = await db.get_all_users()
    
    end_time = time.time()
    start_time = end_time - (7 * 24 * 60 * 60) # 7 days ago
    
    for user in users:
        chat_id = user.get("chat_id")
        wallet = user.get("wallet_address")
        
        if not wallet: continue
        
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
            await bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send summary to {chat_id}: {e}")

def setup_scheduler(bot):
    scheduler = AsyncIOScheduler()
    
    # Weekly Summary: Sunday 23:59 UTC
    scheduler.add_job(
        send_weekly_summary, 
        'cron', 
        day_of_week='sun', 
        hour=23, 
        minute=59, 
        args=[bot]
    )
    
    # Daily Digest: Every day at 09:00 UTC
    scheduler.add_job(
        send_daily_digest,
        'cron',
        hour=9,
        minute=0,
        args=[bot]
    )

    # Market Reports: Every minute
    scheduler.add_job(
        send_market_reports,
        'cron',
        minute='*',
        args=[bot]
    )
    
    scheduler.start()
    return scheduler
