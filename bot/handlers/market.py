import logging
import asyncio
import time
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_mid_price, get_perps_context, get_hlp_info, get_fear_greed_index,
    get_symbol_name, get_spot_balances, get_perps_state, extract_avg_entry_from_balance
)
from bot.utils import pretty_float
from bot.analytics import (
    prepare_modern_market_data, prepare_liquidity_data, prepare_coin_prices_data,
    generate_market_overview_image, prepare_terminal_dashboard_data_clean
)
from bot.renderer import render_html_to_image
from bot.handlers._common import (
    smart_edit, smart_edit_media, _back_kb, _get_billing_state, _ensure_billing_quota, _consume_billing_usage,
    BILLING_USAGE_OVERVIEW, _build_delta_neutral_dashboard, _ensure_billing_feature
)
from bot.handlers.states import MarketAlertStates

router = Router(name="market")
logger = logging.getLogger(__name__)

@router.callback_query(F.data == "cb_market")
async def cb_market(call: CallbackQuery):
    await call.answer("Loading...")
    lang, ws, watchlist = await db.get_lang(call.message.chat.id), getattr(call.message.bot, "ws_manager", None), await db.get_watchlist(call.message.chat.id)
    if not watchlist: watchlist = ["BTC", "ETH"]
    ctx = await get_perps_context()
    universe = (ctx[0].get("universe", []) if isinstance(ctx[0], dict) else ctx[0]) if ctx else []
    asset_ctxs = ctx[1] if ctx else []
    lines = []
    for sym in watchlist:
        idx = next((i for i, u in enumerate(universe) if (u["name"] if isinstance(u, dict) else u) == sym), -1)
        price, funding_rate, volume, ac = 0.0, 0.0, 0.0, {}
        if idx != -1 and idx < len(asset_ctxs):
            ac = asset_ctxs[idx]; price, funding_rate, volume = float(ac.get("markPx", 0)), float(ac.get("funding", 0)), float(ac.get("dayNtlVlm", 0))
        if price == 0: price = (ws.get_price(sym) if ws else 0.0) or await get_mid_price(sym)
        change_24h = ((price - float(ac.get("prevDayPx", 0 or price))) / float(ac.get("prevDayPx", 0 or price))) * 100 if float(ac.get("prevDayPx", 0 or price)) > 0 else 0.0
        lines.append(f"🔹 <b>{sym}</b>: ${pretty_float(price, 4)} ({'🟢' if change_24h >= 0 else '🔴'} {change_24h:+.2f}%)\n   F: {funding_rate*100:.4f}% ({funding_rate*24*365*100:.1f}% APR) | Vol: ${pretty_float(volume/1e6, 1)}M")
    text = f"{_t(lang, 'market_title')} (updated {time.strftime('%H:%M:%S', time.gmtime())})\n\n" + "\n\n".join(lines) + "\n\nℹ️ <i>/watch SYM | /unwatch SYM</i>"
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_market_overview"), callback_data="cb_market_overview")
    kb.button(text=_t(lang, "btn_refresh"), callback_data="cb_market")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_market_overview")
async def cb_market_overview(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    if not await _consume_billing_usage(call, call.message.chat.id, lang, BILLING_USAGE_OVERVIEW, "overview_runs_daily", "billing_feature_overview_runs", is_callback=True): return
    await call.answer("Generating Market Insights...")
    ctx, hlp_info = await asyncio.gather(get_perps_context(), get_hlp_info(), return_exceptions=True)
    if isinstance(ctx, Exception) or not ctx: await call.message.answer("❌ Error fetching market data."); return
    universe, asset_ctxs = (ctx[0].get("universe", []) if isinstance(ctx[0], dict) else ctx[0]), ctx[1]
    data_alpha, data_liq, data_prices, fng = prepare_modern_market_data(asset_ctxs, universe, hlp_info if not isinstance(hlp_info, Exception) else None), prepare_liquidity_data(asset_ctxs, universe), prepare_coin_prices_data(asset_ctxs, universe), await get_fear_greed_index()
    try:
        buf_alpha, buf_liq, buf_heat, buf_prices = await asyncio.gather(render_html_to_image("market_stats.html", data_alpha, lang=lang), render_html_to_image("liquidity_stats.html", data_liq, lang=lang), render_html_to_image("funding_heatmap.html", data_alpha, lang=lang), render_html_to_image("coin_prices.html", data_prices, lang=lang))
        majors_text = ""
        for sym in ["BTC", "ETH", "SOL", "HYPE"]:
            idx = next((i for i, u in enumerate(universe) if (u["name"] if isinstance(u, dict) else u) == sym), -1)
            if idx != -1:
                ac = asset_ctxs[idx]; p = float(ac.get("markPx", 0)); change = ((p - float(ac.get("prevDayPx", p))) / float(ac.get("prevDayPx", p))) * 100 if float(ac.get("prevDayPx", p)) > 0 else 0.0
                majors_text += f"🔹 <b>{sym}</b>: ${pretty_float(p)} ({'🟢' if change>=0 else '🔴'} {change:+.2f}%)\n   ├ F: <code>{float(ac.get('funding', 0))*24*365*100:+.1f}% APR</code>\n   └ OI: <b>${float(ac.get('openInterest', 0))*p/1e6:.1f}M</b> | Vol: <b>${float(ac.get('dayNtlVlm', 0))/1e6:.1f}M</b>\n\n"
        watchlist, watchlist_lines = await db.get_watchlist(call.message.chat.id), []
        if watchlist:
            for sym in watchlist:
                if sym in ["BTC", "ETH", "SOL", "HYPE"]: continue
                idx = next((i for i, u in enumerate(universe) if (u["name"] if isinstance(u, dict) else u) == sym), -1)
                if idx != -1:
                    ac = asset_ctxs[idx]; p = float(ac.get("markPx", 0)); change = ((p - float(ac.get("prevDayPx", p))) / float(ac.get("prevDayPx", p))) * 100 if float(ac.get("prevDayPx", p)) > 0 else 0.0
                    watchlist_lines.append(f"• {sym}: ${pretty_float(p)} ({'🟢' if change>=0 else '🔴'} {change:+.2f}%)")
        text_report = f"📊 <b>{_t(lang, 'market_alerts_title')}</b>\n\n<b>{_t(lang, 'market_report_global')}</b>\n• Vol 24h: <b>${data_alpha['global_volume']}</b>\n• Total OI: <b>${data_alpha['total_oi']}</b>\n• Sentiment: <code>{data_alpha['sentiment_label']}</code>\n{f'• Fear/Greed: {fng[chr(101)]} <b>{fng[chr(118)]}</b> ({fng[chr(99)]})' if fng else ''}\n<b>{_t(lang, 'market_report_majors')}</b>\n{majors_text}{f'⭐ <b>{_t(lang, chr(109)) + _t(lang, chr(97)) + _t(lang, chr(114)) + _t(lang, chr(107)) + _t(lang, chr(101)) + _t(lang, chr(116)) + _t(lang, chr(95)) + _t(lang, chr(114)) + _t(lang, chr(101)) + _t(lang, chr(112)) + _t(lang, chr(111)) + _t(lang, chr(114)) + _t(lang, chr(116)) + _t(lang, chr(95)) + _t(lang, chr(119)) + _t(lang, chr(97)) + _t(lang, chr(116)) + _t(lang, chr(99)) + _t(lang, chr(104)) + _t(lang, chr(108)) + _t(lang, chr(105)) + _t(lang, chr(115)) + _t(lang, chr(116))}</b>:' + chr(10) + chr(10).join(watchlist_lines) + chr(10) + chr(10) if watchlist_lines else ''}🕒 <i>{_t(lang, 'market_report_footer', time=time.strftime('%H:%M') + ' UTC')}</i>"
        await call.message.delete()
        mids = await call.message.answer_media_group([InputMediaPhoto(media=BufferedInputFile(buf_prices.read(), filename="i1.png")), InputMediaPhoto(media=BufferedInputFile(buf_heat.read(), filename="i2.png")), InputMediaPhoto(media=BufferedInputFile(buf_alpha.read(), filename="i3.png")), InputMediaPhoto(media=BufferedInputFile(buf_liq.read(), filename="i4.png"))])
        await state.update_data(market_media_ids=[m.message_id for m in mids])
        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "btn_back"), callback_data="cb_market_cleanup")
        await call.message.answer(text_report, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception as e: logger.error(f"Error generating images: {e}"); await call.message.answer("❌ Error generating images.")

@router.callback_query(F.data == "cb_market_cleanup")
async def cb_market_cleanup(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    for mid in data.get("market_media_ids", []):
        try: await call.message.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)
        except Exception: pass
    await state.update_data(market_media_ids=None)
    from bot.handlers.menu import cb_sub_market
    await cb_sub_market(call)

@router.callback_query(F.data.startswith("cb_heatmap_sort:"))
async def cb_heatmap_sort(call: CallbackQuery):
    sort_by = call.data.split(":")[1]
    await call.answer(f"Sorting by {sort_by}...")
    lang, ctx = await db.get_lang(call.message.chat.id), await get_perps_context()
    buf = generate_market_overview_image(ctx[1], ctx[0].get("universe", []) if isinstance(ctx[0], dict) else ctx[0], sort_by=sort_by)
    kb = InlineKeyboardBuilder()
    for s in ["vol", "funding", "oi", "change"]:
        if s != sort_by: kb.button(text=_t(lang, f"sort_{s}"), callback_data=f"cb_heatmap_sort:{s}")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_market")
    kb.adjust(2, 2)
    if buf: await call.message.edit_media(media=InputMediaPhoto(media=BufferedInputFile(buf.read(), filename="mo.png"), caption=f"📊 <b>Market Fundamentals ({sort_by.upper()})</b>", parse_mode="HTML"), reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_market_alerts")
async def cb_market_alerts(call: CallbackQuery):
    lang, user_settings = await db.get_lang(call.message.chat.id), await db.get_user_settings(call.message.chat.id)
    alert_times = user_settings.get("market_alert_times", [])
    text = f"{_t(lang, 'market_alerts_title')}\n\n{_t(lang, 'market_alerts_msg')}\n\n"
    kb = InlineKeyboardBuilder()
    if not alert_times: text += f"<i>{_t(lang, 'no_market_alerts')}</i>"
    else:
        for t_entry in sorted(alert_times, key=lambda x: x["t"] if isinstance(x, dict) else x):
            t, is_repeat = (t_entry["t"], t_entry.get("r", True)) if isinstance(t_entry, dict) else (t_entry, True)
            text += f"{'🔄' if is_repeat else '📍'} <b>{t} UTC</b>\n"; kb.button(text=f"❌ {t}", callback_data=f"del_market_alert:{t}")
    kb.button(text=_t(lang, "btn_add_time"), callback_data="cb_add_market_alert_time")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    await smart_edit(call, text + f"\n\n<i>Last update: {time.strftime('%H:%M:%S')}</i>", reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_add_market_alert_time")
async def cb_add_market_alert_time(call: CallbackQuery, state: FSMContext):
    lang, billing_state = await db.get_lang(call.message.chat.id), await _get_billing_state(call.message.chat.id)
    if not await _ensure_billing_quota(call, call.message.chat.id, lang, "market_reports", billing_state["counts"]["market_reports"], "billing_feature_market_reports", is_callback=True): return
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(_t(lang, "add_time_prompt"), reply_markup=_back_kb(lang, "cb_market_alerts"), parse_mode="HTML")
    await state.set_state(MarketAlertStates.waiting_for_time)
    await call.answer()

@router.message(MarketAlertStates.waiting_for_time)
async def process_market_alert_time(message: Message, state: FSMContext):
    lang, time_str = await db.get_lang(message.chat.id), message.text.strip()
    try:
        parts = time_str.split(":")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
        time_str = f"{h:02d}:{m:02d}"
    except Exception: await message.answer(_t(lang, "invalid_time")); return
    await state.update_data(pending_time=time_str)
    try:
        await message.delete()
    except Exception: pass
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 " + _t(lang, "daily"), callback_data="ma_type:daily")
    kb.button(text="📍 " + _t(lang, "once"), callback_data="ma_type:once")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_market_alerts")
    kb.adjust(1)
    msg_id = (await state.get_data()).get("menu_msg_id")
    if msg_id:
        try:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=f"⏰ Time: <b>{time_str} UTC</b>\n\nChoose frequency:", reply_markup=kb.as_markup(), parse_mode="HTML")
            await state.set_state(MarketAlertStates.waiting_for_type)
            return
        except Exception: pass
    await message.answer(f"⏰ Time: <b>{time_str} UTC</b>\n\nChoose frequency:", reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(MarketAlertStates.waiting_for_type)

@router.callback_query(MarketAlertStates.waiting_for_type, F.data.startswith("ma_type:"))
async def process_market_alert_type(call: CallbackQuery, state: FSMContext):
    lang, data = await db.get_lang(call.message.chat.id), await state.get_data()
    time_str, alert_type = data.get("pending_time"), call.data.split(":")[1]
    user_settings = await db.get_user_settings(call.message.chat.id)
    alert_times = [t for t in user_settings.get("market_alert_times", []) if (t["t"] if isinstance(t, dict) else t) != time_str]
    alert_times.append({"t": time_str, "r": (alert_type == "daily")})
    await db.update_user_settings(call.message.chat.id, {"market_alert_times": alert_times})
    await state.clear(); await call.answer(_t(lang, "market_alert_added").format(time=time_str)); await cb_market_alerts(call)

@router.callback_query(F.data.startswith("del_market_alert:"))
async def cb_del_market_alert(call: CallbackQuery):
    time_str, lang = call.data.split(":")[1], await db.get_lang(call.message.chat.id)
    user_settings = await db.get_user_settings(call.message.chat.id)
    alert_times = [t for t in user_settings.get("market_alert_times", []) if (t["t"] if isinstance(t, dict) else t) != time_str]
    if len(alert_times) < len(user_settings.get("market_alert_times", [])):
        await db.update_user_settings(call.message.chat.id, {"market_alert_times": alert_times})
        await call.answer(_t(lang, "market_alert_removed").format(time=time_str))
    else: await call.answer("🗑️ Alert not found")
    await cb_market_alerts(call)

@router.callback_query(F.data == "cb_whales")
async def cb_whales(call: CallbackQuery):
    lang, user_settings = await db.get_lang(call.message.chat.id), await db.get_user_settings(call.message.chat.id)
    is_on, threshold, wl_only = user_settings.get("whale_alerts", False), user_settings.get("whale_threshold", 50_000), user_settings.get("whale_watchlist_only", False)
    text = f"{_t(lang, 'whales_title')}\n\n{_t(lang, 'whale_intro')}\n\n{_t(lang, 'whale_alerts_on' if is_on else 'whale_alerts_off')}\n{_t(lang, 'whale_watchlist_only_on' if wl_only else 'whales_all_assets')}\n{_t(lang, 'min_val')}: <b>${pretty_float(threshold, 0)}</b>"
    kb = InlineKeyboardBuilder(); kb.button(text=_t(lang, "disable" if is_on else "enable"), callback_data=f"toggle_whales:{'off' if is_on else 'on'}")
    kb.button(text="🔔 Show All Assets" if wl_only else "👁️ Watchlist Only", callback_data=f"toggle_whale_wl:{'off' if wl_only else 'on'}")
    kb.button(text="✏️ Threshold", callback_data="set_whale_thr_prompt"); kb.button(text=_t(lang, "btn_back"), callback_data="sub:market"); kb.adjust(1)
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("toggle_whale_wl:"))
async def cb_toggle_whale_wl(call: CallbackQuery):
    await db.update_user_settings(call.message.chat.id, {"whale_watchlist_only": call.data.split(":")[1] == "on"}); await cb_whales(call)

@router.callback_query(F.data.startswith("toggle_whales:"))
async def cb_toggle_whales(call: CallbackQuery):
    await db.update_user_settings(call.message.chat.id, {"whale_alerts": call.data.split(":")[1] == "on"}); await cb_whales(call)

@router.callback_query(F.data == "cb_fear_greed")
async def cb_fear_greed(call: CallbackQuery):
    lang, fng = await db.get_lang(call.message.chat.id), await get_fear_greed_index()
    if not fng: await smart_edit(call, "❌ Unable to fetch Fear & Greed data.", reply_markup=_back_kb(lang, "sub:market")); await call.answer(); return
    val, change = fng["value"], fng["change"]
    text = f"{_t(lang, 'fng_title')}\n\n{fng['emoji']} <b>{val}</b> — {fng['classification']}\n\n<code>[{'█' * int(val/5) + '░' * (20 - int(val/5))}]</code>\n<code>0   Fear         Greed   100</code>\n\n{'📈' if change > 0 else ('📉' if change < 0 else '➖')} {_t(lang, 'fng_change', change=change)}\n\n<i>Source: Alternative.me Crypto Fear & Greed Index</i>"
    kb = InlineKeyboardBuilder(); kb.button(text=_t(lang, "btn_refresh"), callback_data="cb_fear_greed"); kb.button(text=_t(lang, "btn_back"), callback_data="sub:market"); kb.adjust(1); await smart_edit(call, text, reply_markup=kb.as_markup()); await call.answer()

@router.callback_query(F.data == "cb_delta_neutral")
async def cb_delta_neutral(call: CallbackQuery):
    await call.answer("Loading..."); lang = await db.get_lang(call.message.chat.id)
    text, _ = await _build_delta_neutral_dashboard(call.message.chat.id, call.message.bot, interval_hours=0.0, emit_alerts=False)
    if not text: await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, "sub:overview")); return
    kb = InlineKeyboardBuilder(); kb.row(InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data="cb_delta_neutral_refresh")); kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="sub:overview")); await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_delta_neutral_refresh")
async def cb_delta_neutral_refresh(call: CallbackQuery): await cb_delta_neutral(call)

@router.message(Command("status"))
async def cmd_status(message: Message):
    lang = await db.get_lang(message.chat.id)
    text, _ = await _build_delta_neutral_dashboard(message.chat.id, message.bot, interval_hours=0.0, emit_alerts=False)
    if not text: await message.answer(_t(lang, "need_wallet"), parse_mode="HTML"); return
    await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "cb_terminal")
async def cb_terminal(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "terminal", "billing_feature_terminal", is_callback=True): return
    await call.answer("Loading Terminal..."); wallets = await db.list_wallets(call.message.chat.id)
    if not wallets: await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, "sub:overview")); return
    ws, total_equity, total_upnl, total_margin_used, total_withdrawable, total_ntl, combined_assets, combined_positions = getattr(call.message.bot, "ws_manager", None), 0.0, 0.0, 0.0, 0.0, 0.0, [], []
    for wallet in wallets:
        spot_bals, perps_state = await get_spot_balances(wallet), await get_perps_state(wallet)
        if spot_bals:
            for b in spot_bals:
                coin_id, amount = b.get("coin"), float(b.get("total", 0) or 0)
                if amount <= 0: continue
                name = await get_symbol_name(coin_id, is_spot=True)
                px = (ws.get_price(name, coin_id) if ws else 0.0) or await get_mid_price(name, coin_id)
                val = amount * px; total_equity += val
                entry = extract_avg_entry_from_balance(b)
                if not entry or entry <= 0:
                    try: entry = (lambda x: sum(float(f['px'])*float(f['sz']) for f in x)/sum(float(f['sz']) for f in x) if x else 0.0)(await db.get_fills_by_coin(wallet, coin_id))
                    except Exception: entry = 0.0
                if entry > 0 and px > 0:
                    spot_pnl = (px - entry) * amount; total_upnl += spot_pnl
                    combined_positions.append({"symbol": name, "side": "SPOT", "leverage": "SPOT", "size_usd": abs(val), "entry": entry, "mark": px, "liq": 0.0, "pnl": spot_pnl, "roi": ((px / entry) - 1) * 100})
                if val > 5: combined_assets.append({"name": name, "value": val})
        if perps_state:
             if "marginSummary" in perps_state:
                 ms = perps_state["marginSummary"]; p_eq, m_used, ntl = float(ms.get("accountValue", 0) or 0), float(ms.get("totalMarginUsed", 0) or 0), float(ms.get("totalNtlPos", 0) or 0)
                 total_equity += p_eq; total_margin_used += m_used; total_ntl += ntl
             total_withdrawable += float(perps_state.get("withdrawable", 0) or 0)
             for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {}); szi, coin_id = float(pos.get("szi", 0)), pos.get("coin")
                if szi == 0: continue
                sym = await get_symbol_name(coin_id, is_spot=False); entry, leverage, liq = float(pos.get("entryPx", 0)), float(pos.get("leverage", {}).get("value", 0)), float(pos.get("liquidationPx", 0) or 0)
                mark = (ws.get_price(sym, coin_id) if ws else 0.0) or await get_mid_price(sym, coin_id)
                pnl = (mark - entry) * szi if mark else 0.0; total_upnl += pnl
                combined_positions.append({"symbol": sym, "side": "LONG" if szi > 0 else "SHORT", "leverage": leverage, "size_usd": abs(szi * mark), "entry": entry, "mark": mark, "liq": liq, "pnl": pnl, "roi": (pnl / (abs(szi) * entry / leverage)) * 100 if (leverage and szi and entry) else 0.0})
    data = prepare_terminal_dashboard_data_clean(wallet_label=wallets[0] if len(wallets) == 1 else "Total Portfolio", wallet_address=wallets[0], total_equity=total_equity, upnl=total_upnl, margin_usage=(total_margin_used / total_equity * 100) if total_equity > 0 else 0.0, leverage=(total_ntl / total_equity) if total_equity > 0 else 0.0, withdrawable=total_withdrawable, assets=combined_assets, positions=combined_positions)
    try:
        buf = await render_html_to_image("terminal_dashboard.html", data, width=1000, height=600, lang=lang); caption = "🖥️ <b>Velox Terminal</b>" + (f" ({len(wallets)} wallets)" if len(wallets) > 1 else "")
        await smart_edit_media(call, BufferedInputFile(buf.read(), filename="terminal.png"), caption, reply_markup=_back_kb(lang, "sub:overview"))
    except Exception as e: logger.error(f"Error rendering terminal: {e}"); await call.message.answer("❌ Error generating terminal.")
