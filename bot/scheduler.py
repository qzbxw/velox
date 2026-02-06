from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.database import db
from bot.services import (
    get_spot_balances, get_user_portfolio, pretty_float, get_perps_context, 
    get_hlp_info, _is_buy, calc_avg_entry_from_fills, get_all_assets_meta,
    get_fear_greed_index
)
from bot.analytics import prepare_modern_market_data
from bot.market_overview import market_overview
from bot.renderer import render_html_to_image
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

async def send_daily_digest(bot):
    """Generate and send daily digest (Equity PnL) to all users."""
    logger.info("Generating daily digest...")
    user_wallet_pairs = await _get_user_wallet_pairs()

    for chat_id, wallet in user_wallet_pairs:
        
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

async def send_weekly_summary(bot):
    """Generate and send weekly summary to all users."""
    logger.info("Generating weekly summary...")
    user_wallet_pairs = await _get_user_wallet_pairs()
    
    end_time = time.time()
    start_time = end_time - (7 * 24 * 60 * 60) # 7 days ago
    
    for chat_id, wallet in user_wallet_pairs:
        
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
    
    scheduler.start()
    return scheduler
