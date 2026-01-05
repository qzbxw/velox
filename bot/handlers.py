from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.services import (
    get_symbol_name, get_mid_price, get_open_orders, get_spot_balances, 
    get_perps_state, pretty_float, get_user_portfolio, get_perps_context,
    extract_avg_entry_from_balance
)
import logging
import time
import html

router = Router()
logger = logging.getLogger(__name__)

# --- UI Helpers ---

def _t(lang: str, key: str) -> str:
    l = (lang or "ru").lower()
    ru = {
        "welcome": "👋 <b>Velox Terminal</b>\n\nМониторинг портфеля Hyperliquid в реальном времени.",
        "set_wallet": "⚠️ Кошелёк не подключен. Используй /add_wallet <code>0x...</code>",
        "tracking": "✅ Отслеживаю: <code>{wallet}</code>",
        "alert_added": "✅ Алерт установлен: <b>{symbol}</b> {dir} <b>${price}</b>",
        "alert_usage": "⚠️ Используй: <code>/alert ETH 3500</code> (бот сам поймет выше/ниже)",
        "alert_error": "❌ Ошибка. Проверь формат.",
        "no_alerts": "📭 Активных алертов нет.",
        "alerts_list": "🔔 <b>Твои алерты:</b>",
        "deleted": "🗑️ Удалено.",
        "balance_title": "🏦 <b>Балансы</b>",
        "positions_title": "🎰 <b>Позиции</b>",
        "orders_title": "🧾 <b>Ордера</b>",
        "market_title": "📊 <b>Рынок</b>",
        "settings_title": "⚙️ <b>Настройки</b>",
        "lang_title": "🌍 <b>Язык / Language</b>",
        "wait": "⏳ Загрузка...",
        "need_wallet": "⛔ Сначала добавь кошелёк: /add_wallet",
        # Buttons
        "btn_balance": "🏦 Баланс",
        "btn_positions": "🎰 Позиции",
        "btn_orders": "🧾 Ордера",
        "btn_pnl": "🧮 PnL",
        "btn_market": "📊 Рынок",
        "btn_settings": "⚙️ Настройки",
        "btn_alerts": "🔔 Алерты",
        "btn_lang": "🌍 Язык",
        "btn_back": "🔙 Назад",
        # New
        "pnl_title": "🧮 <b>PnL Анализ</b>",
        "equity": "💰 Эквивалент (Equity)",
        "wallet_bal": "💵 Баланс кошелька",
        "upnl": "📊 Нереал. PnL",
        "day_change": "📅 Изм. 24ч",
        "week_change": "📅 Изм. 7д",
        "month_change": "📅 Изм. 30д",
        "cum_pnl": "📈 Совок. PnL",
        "empty_pnl": "📭 Нет данных истории.",
        "liq_price": "💀 Liq",
        "roi": "ROI",
        "margin": "Margin",
        "leverage": "⚙️ Плечо",
        "funding": "Funding",
        "withdrawable": "💳 Доступно",
        "margin_ratio": "⚠️ M.Ratio",
    }
    en = {
        "welcome": "👋 <b>Velox Terminal</b>\n\nReal-time Hyperliquid portfolio monitoring.",
        "set_wallet": "⚠️ No wallet connected. Use /add_wallet <code>0x...</code>",
        "tracking": "✅ Tracking: <code>{wallet}</code>",
        "alert_added": "✅ Alert set: <b>{symbol}</b> {dir} <b>${price}</b>",
        "alert_usage": "⚠️ Usage: <code>/alert ETH 3500</code> (auto-detects above/below)",
        "alert_error": "❌ Error. Check format.",
        "no_alerts": "📭 No active alerts.",
        "alerts_list": "🔔 <b>Your Alerts:</b>",
        "deleted": "🗑️ Deleted.",
        "balance_title": "🏦 <b>Balances</b>",
        "positions_title": "🎰 <b>Positions</b>",
        "orders_title": "🧾 <b>Orders</b>",
        "market_title": "📊 <b>Market</b>",
        "settings_title": "⚙️ <b>Settings</b>",
        "lang_title": "🌍 <b>Language</b>",
        "wait": "⏳ Loading...",
        "need_wallet": "⛔ Add wallet first: /add_wallet",
        # Buttons
        "btn_balance": "🏦 Balance",
        "btn_positions": "🎰 Positions",
        "btn_orders": "🧾 Orders",
        "btn_pnl": "🧮 PnL",
        "btn_market": "📊 Market",
        "btn_settings": "⚙️ Settings",
        "btn_alerts": "🔔 Alerts",
        "btn_lang": "🌍 Language",
        "btn_back": "🔙 Back",
        # New
        "pnl_title": "🧮 <b>PnL Analysis</b>",
        "equity": "💰 Equity",
        "wallet_bal": "💵 Wallet Balance",
        "upnl": "📊 Unreal. PnL",
        "day_change": "📅 24h Change",
        "week_change": "📅 7d Change",
        "month_change": "📅 30d Change",
        "cum_pnl": "📈 Cum. PnL",
        "empty_pnl": "📭 No history data.",
        "liq_price": "💀 Liq",
        "roi": "ROI",
        "margin": "Margin",
        "leverage": "⚙️ Leverage",
        "funding": "Funding",
        "withdrawable": "💳 Withdr.",
        "margin_ratio": "⚠️ M.Ratio",
    }
    table = ru if l == "ru" else en
    return table.get(key, key)

def _main_menu_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_balance"), callback_data="cb_balance"),
        InlineKeyboardButton(text=_t(lang, "btn_positions"), callback_data="cb_positions")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_orders"), callback_data="cb_orders"),
        InlineKeyboardButton(text=_t(lang, "btn_pnl"), callback_data="cb_pnl")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_market"), callback_data="cb_market"),
        InlineKeyboardButton(text=_t(lang, "btn_settings"), callback_data="cb_settings")
    )
    return kb.as_markup()

def _back_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_menu")
    return kb.as_markup()

def _settings_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_alerts"), callback_data="cb_alerts"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_lang"), callback_data="cb_lang_menu"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

# --- COMMANDS ---

@router.message(Command("start"))
async def cmd_start(message: Message):
    lang = await db.get_lang(message.chat.id)
    wallets = await db.list_wallets(message.chat.id)
    
    text = _t(lang, "welcome")
    if not wallets:
        text += "\n\n" + _t(lang, "set_wallet")
    else:
        text += "\n\n" + _t(lang, "tracking").format(wallet=f"{wallets[0][:6]}...{wallets[0][-4:]}")

    await message.answer(text, reply_markup=_main_menu_kb(lang), parse_mode="HTML")
    await db.add_user(message.chat.id, None)

@router.message(Command("add_wallet"))
async def cmd_add_wallet(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /add_wallet 0x...")
        return
    wallet = args[1].lower()
    await db.add_wallet(message.chat.id, wallet)
    
    ws = getattr(message.bot, "ws_manager", None)
    if ws:
        ws.track_wallet(wallet)
        await ws.subscribe_user(wallet)
        
    await message.answer(_t(lang, "tracking").format(wallet=wallet), reply_markup=_back_kb(lang), parse_mode="HTML")

@router.message(Command("alert"))
async def cmd_alert(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 3:
        await message.answer(_t(lang, "alert_usage"), parse_mode="HTML")
        return
    
    symbol = html.escape(args[1].upper())
    try:
        target = float(args[2])
    except:
        await message.answer(_t(lang, "alert_error"))
        return

    current = 0.0
    ws = getattr(message.bot, "ws_manager", None)
    if ws: current = ws.get_price(symbol)
    if not current: current = await get_mid_price(symbol)
    
    if not current:
        await message.answer(f"❌ Unknown price for {symbol}")
        return
        
    direction = "above" if target > current else "below"
    
    await db.add_price_alert(message.chat.id, symbol, target, direction)
    
    dir_icon = "📈" if direction == "above" else "📉"
    msg = _t(lang, "alert_added").format(symbol=symbol, dir=dir_icon, price=pretty_float(target))
    await message.answer(msg, parse_mode="HTML")

# --- CALLBACKS ---

@router.callback_query(F.data == "cb_menu")
async def cb_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    text = _t(lang, "welcome")
    if wallets:
        text += "\n\n" + _t(lang, "tracking").format(wallet=f"{wallets[0][:6]}...{wallets[0][-4:]}")
    
    await call.message.edit_text(text, reply_markup=_main_menu_kb(lang), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "cb_balance")
async def cb_balance(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang), parse_mode="HTML")
        return

    msg_parts = []
    ws = getattr(call.message.bot, "ws_manager", None)

    for wallet in wallets:
        spot_bals = await get_spot_balances(wallet)
        perps_state = await get_perps_state(wallet)
        
        wallet_lines = []
        wallet_total = 0.0
        
        if spot_bals:
            for b in spot_bals:
                coin_id = b.get("coin")
                coin_name = await get_symbol_name(coin_id)
                amount = float(b.get("total", 0) or 0)
                hold = float(b.get("hold", 0) or 0)
                
                if amount <= 0: continue
                
                px = 0.0
                if ws: px = ws.get_price(coin_name)
                if not px: px = await get_mid_price(coin_name)
                
                val = amount * px
                wallet_total += val
                
                line = f"▫️ <b>{coin_name}</b>: {amount:.4f} (${pretty_float(val, 0)})"
                if hold > 0:
                    line += f" (🔒 {hold:.4f})"
                wallet_lines.append(line)

        perps_equity = 0.0
        margin_used = 0.0
        total_ntl = 0.0
        total_upnl = 0.0
        withdrawable = 0.0
        maint_margin = 0.0
        
        if perps_state:
            withdrawable = float(perps_state.get("withdrawable", 0) or 0)
            maint_margin = float(perps_state.get("crossMaintenanceMarginUsed", 0) or 0)
            
            # Margin Summary
            if "marginSummary" in perps_state:
                ms = perps_state["marginSummary"]
                perps_equity = float(ms.get("accountValue", 0) or 0)
                margin_used = float(ms.get("totalMarginUsed", 0) or 0)
                total_ntl = float(ms.get("totalNtlPos", 0) or 0)
            
            # Calculate Total uPnL
            for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {})
                coin_id = pos.get("coin")
                szi = float(pos.get("szi", 0))
                entry_px = float(pos.get("entryPx", 0))
                
                if szi == 0: continue
                
                sym = await get_symbol_name(coin_id)
                mark_px = 0.0
                if ws: mark_px = ws.get_price(sym)
                if not mark_px: mark_px = await get_mid_price(sym)
                
                if mark_px:
                     total_upnl += (mark_px - entry_px) * szi

        header = f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b>"
        body = ""
        if wallet_lines:
            body += f"\n   <b>Spot:</b> ${pretty_float(wallet_total, 2)}\n   " + "\n   ".join(wallet_lines)
        if perps_equity > 1 or margin_used > 0:
             body += f"\n   <b>Perps Eq:</b> ${pretty_float(perps_equity, 2)}"
             body += f"\n   {_t(lang, 'withdrawable')}: ${pretty_float(withdrawable, 2)}"
             body += f"\n   ⚠️ Margin: ${pretty_float(margin_used, 2)}"
             
             if perps_equity > 0:
                 lev = total_ntl / perps_equity
                 m_ratio = (maint_margin / perps_equity) * 100
                 body += f"\n   {_t(lang, 'leverage')}: {lev:.1f}x | {_t(lang, 'margin_ratio')}: {m_ratio:.1f}%"
             
             upnl_icon = "🟢" if total_upnl >= 0 else "🔴"
             body += f"\n   {upnl_icon} <b>uPnL:</b> ${pretty_float(total_upnl, 2)}"
        
        if not body: body = "\n   <i>Empty</i>"
        msg_parts.append(header + body)

    text = _t(lang, "balance_title") + "\n\n" + "\n\n".join(msg_parts)
    await call.message.edit_text(text, reply_markup=_back_kb(lang), parse_mode="HTML")

@router.callback_query(F.data == "cb_positions")
async def cb_positions(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang), parse_mode="HTML")
        return

    msg_parts = []
    has_pos = False
    ws = getattr(call.message.bot, "ws_manager", None)

    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        positions = state.get("assetPositions", [])
        if not positions: continue
        
        has_pos = True
        lines = []
        for p in positions:
            pos = p.get("position", {})
            coin_id = pos.get("coin")
            sym = await get_symbol_name(coin_id)
            szi = float(pos.get("szi", 0))
            if szi == 0: continue
            
            entry_px = float(pos.get("entryPx", 0))
            leverage = float(pos.get("leverage", {}).get("value", 0))
            liq_px = float(pos.get("liquidationPx", 0) or 0)
            
            mark_px = 0.0
            if ws: mark_px = ws.get_price(sym)
            if not mark_px: mark_px = await get_mid_price(sym)
            
            upnl = (mark_px - entry_px) * szi if mark_px else 0.0
            roi = 0.0
            if leverage and szi and entry_px:
                 roi = (upnl / (abs(szi) * entry_px / leverage)) * 100
            
            icon = "🟢" if szi > 0 else "🔴"
            lines.append(
                f"{icon} <b>{sym}</b> {leverage}x\n"
                f"   Sz: {szi:.4f} @ ${pretty_float(entry_px)}\n"
                f"   Liq: ${pretty_float(liq_px)} | uPnL: <b>${pretty_float(upnl, 2)}</b> ({roi:+.0f}%)"
            )
            
        if lines:
            msg_parts.append(f"👛 <b>{wallet[:6]}...</b>\n" + "\n".join(lines))

    if not has_pos:
        text = _t(lang, "positions_title") + "\n\n📭 No open positions."
    else:
        text = _t(lang, "positions_title") + "\n\n" + "\n\n".join(msg_parts)
        
    await call.message.edit_text(text, reply_markup=_back_kb(lang), parse_mode="HTML")

@router.callback_query(F.data == "cb_orders")
async def cb_orders(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang))
        return

    msg_parts = []
    for wallet in wallets:
        orders = await get_open_orders(wallet)
        if isinstance(orders, dict): orders = orders.get("orders", [])
        if not orders: continue
        
        lines = []
        for o in orders:
            coin = o.get("coin")
            sym = await get_symbol_name(coin)
            sz = float(o.get("sz", 0))
            px = float(o.get("limitPx", 0))
            side = o.get("side")
            icon = "🟢" if str(side).lower().startswith("b") else "🔴"
            lines.append(f"{icon} <b>{sym}</b>: {sz} @ ${pretty_float(px)}")
            
        if lines:
             msg_parts.append(f"👛 <b>{wallet[:6]}...</b>\n" + "\n".join(lines))

    text = _t(lang, "orders_title") + "\n\n" + ("\n\n".join(msg_parts) if msg_parts else "📭 No open orders.")
    await call.message.edit_text(text, reply_markup=_back_kb(lang), parse_mode="HTML")

@router.callback_query(F.data == "cb_settings")
async def cb_settings(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.edit_text(_t(lang, "settings_title"), reply_markup=_settings_kb(lang), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "cb_lang_menu")
async def cb_lang_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="lang:ru")
    kb.button(text="🇬🇧 English", callback_data="lang:en")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
    kb.adjust(2, 1)
    await call.message.edit_text(_t(lang, "lang_title"), reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("lang:"))
async def cb_set_lang(call: CallbackQuery):
    lang_code = call.data.split(":")[1]
    await db.set_lang(call.message.chat.id, lang_code)
    await cb_settings(call)

@router.callback_query(F.data == "cb_alerts")
async def cb_alerts(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    alerts = await db.get_user_alerts(call.message.chat.id)
    
    if not alerts:
        await call.message.edit_text(
            f"{_t(lang, 'settings_title')} > <b>Alerts</b>\n\n{_t(lang, 'no_alerts')}\n{_t(lang, 'alert_usage')}",
            reply_markup=_settings_kb(lang),
            parse_mode="HTML"
        )
        return

    kb = InlineKeyboardBuilder()
    text = _t(lang, "alerts_list") + "\n"
    
    for a in alerts:
        aid = str(a["_id"])
        s = str(a.get("symbol", "???"))
        p = pretty_float(a.get("price", 0))
        d = "📈" if a.get("direction") == "above" else "📉"
        
        # Plain text format
        text += f"\n• {s} {d} {p}"
        kb.button(text=f"❌ Del {s}", callback_data=f"del_alert:{aid}")
        
    kb.button(text="🗑️ Clear All", callback_data="clear_all_alerts")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
    kb.adjust(1)
    
    # Send as plain text to be safe
    await call.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "clear_all_alerts")
async def cb_clear_all_alerts(call: CallbackQuery):
    alerts = await db.get_user_alerts(call.message.chat.id)
    for a in alerts:
        await db.delete_alert(str(a["_id"]))
    await cb_alerts(call)

@router.callback_query(F.data.startswith("del_alert:"))
async def cb_del_alert(call: CallbackQuery):
    aid = call.data.split(":")[1]
    await db.delete_alert(aid)
    await cb_alerts(call)

@router.message(Command("watch"))
async def cmd_watch(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /watch <SYMBOL> (e.g. /watch SOL)")
        return
    
    symbol = args[1].upper()
    # Basic validation
    if len(symbol) > 10 or not symbol.isalnum():
        await message.answer("❌ Invalid symbol.")
        return

    await db.add_watch_symbol(message.chat.id, symbol)
    
    # Update WS subscription if needed (optional, for volatility alerts)
    ws = getattr(message.bot, "ws_manager", None)
    if ws:
        if symbol not in ws.watch_subscribers:
            ws.watch_subscribers[symbol] = set()
        ws.watch_subscribers[symbol].add(message.chat.id)

    await message.answer(f"✅ Added <b>{symbol}</b> to watchlist.", parse_mode="HTML")

@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /unwatch <SYMBOL>")
        return
    
    symbol = args[1].upper()
    await db.remove_watch_symbol(message.chat.id, symbol)
    
    # Update WS subscription
    ws = getattr(message.bot, "ws_manager", None)
    if ws and symbol in ws.watch_subscribers:
        ws.watch_subscribers[symbol].discard(message.chat.id)
        
    await message.answer(f"🗑️ Removed <b>{symbol}</b> from watchlist.", parse_mode="HTML")

@router.callback_query(F.data == "cb_market")
async def cb_market(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    ws = getattr(call.message.bot, "ws_manager", None)
    
    # Get Watchlist
    watchlist = await db.get_watchlist(call.message.chat.id)
    if not watchlist:
        watchlist = ["BTC", "ETH"]
    
    # Get Market Context
    ctx = await get_perps_context()
    universe = []
    asset_ctxs = []
    if ctx and isinstance(ctx, list) and len(ctx) == 2:
         if isinstance(ctx[0], dict) and "universe" in ctx[0]:
             universe = ctx[0]["universe"]
         elif isinstance(ctx[0], list):
             universe = ctx[0]
         
         asset_ctxs = ctx[1]

    lines = []
    
    for sym in watchlist:
        # Find index
        idx = -1
        for i, u in enumerate(universe):
            u_name = u["name"] if isinstance(u, dict) else u
            if u_name == sym:
                idx = i
                break
        
        price = 0.0
        funding_rate = 0.0
        volume = 0.0
        
        if idx != -1 and idx < len(asset_ctxs):
            ac = asset_ctxs[idx]
            price = float(ac.get("markPx", 0))
            funding_rate = float(ac.get("funding", 0))
            volume = float(ac.get("dayNtlVlm", 0))
        
        # Fallback price
        if price == 0:
            if ws: price = ws.get_price(sym)
            if not price: price = await get_mid_price(sym)

        # Format
        apr = funding_rate * 24 * 365 * 100
        vol_str = f"{volume/1_000_000:.1f}M" if volume > 1_000_000 else f"{volume/1000:.0f}K"
        
        lines.append(
            f"🔹 <b>{sym}</b>: ${pretty_float(price, 4)}\n"
            f"   F: {funding_rate*100:.4f}% ({apr:.1f}% APR) | Vol: ${vol_str}"
        )
    
    # Add timestamp
    ts = time.strftime("%H:%M:%S", time.gmtime())
    text = f"{_t(lang, 'market_title')} (updated {ts})\n\n" + "\n\n".join(lines)
    text += "\n\nℹ️ <i>/watch SYM | /unwatch SYM</i>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Refresh", callback_data="cb_market")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_menu")
    kb.adjust(1)
    
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.answer()


@router.callback_query(F.data == "cb_pnl")
async def cb_pnl(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang), parse_mode="HTML")
        return

    ws = getattr(call.message.bot, "ws_manager", None)
    
    # Global Totals
    g_spot_eq = 0.0
    g_perps_eq = 0.0
    g_spot_upnl = 0.0
    g_perps_upnl = 0.0
    
    wallet_cards = []
    
    for wallet in wallets:
        # --- SPOT ---
        spot_bals = await get_spot_balances(wallet)
        w_spot_eq = 0.0
        w_spot_upnl = 0.0
        
        if spot_bals:
            for b in spot_bals:
                coin = b.get("coin")
                amount = float(b.get("total", 0) or 0)
                if amount <= 0: continue
                
                # Get Price
                sym = await get_symbol_name(coin)
                px = 0.0
                if ws: px = ws.get_price(sym)
                if not px: px = await get_mid_price(sym)
                
                val = amount * px
                w_spot_eq += val
                
                # uPnL for Spot (Approximate)
                entry = extract_avg_entry_from_balance(b)
                if entry > 0 and px > 0:
                     w_spot_upnl += (px - entry) * amount
                
        # --- PERPS ---
        perps_state = await get_perps_state(wallet)
        portf = await get_user_portfolio(wallet)
        
        w_perps_eq = 0.0
        w_perps_upnl = 0.0
        
        if perps_state and "marginSummary" in perps_state:
             w_perps_eq = float(perps_state["marginSummary"].get("accountValue", 0) or 0)
             
        if perps_state:
            for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {})
                szi = float(pos.get("szi", 0))
                entry_px = float(pos.get("entryPx", 0))
                coin_id = pos.get("coin")
                if szi != 0:
                    sym = await get_symbol_name(coin_id)
                    mark = 0.0
                    if ws: mark = ws.get_price(sym)
                    if not mark: mark = await get_mid_price(sym)
                    if mark:
                        w_perps_upnl += (mark - entry_px) * szi

        # --- History (Perps only usually) ---
        history_points = []
        if isinstance(portf, dict) and "data" in portf:
             if "accountValueHistory" in portf["data"]:
                 history_points = portf["data"]["accountValueHistory"]
        elif isinstance(portf, list):
             history_points = portf

        pnl_stats = ""
        if history_points and len(history_points) > 1:
            try:
                history_points.sort(key=lambda x: x[0])
                current_val = float(history_points[-1][1])
                now_ms = history_points[-1][0]
                
                def get_change(ms_delta):
                    target_time = now_ms - ms_delta
                    closest = min(history_points, key=lambda x: abs(x[0] - target_time))
                    if abs(closest[0] - target_time) > 86400000 * 2: return 0.0
                    start_val = float(closest[1])
                    if start_val == 0: return 0.0
                    return (current_val - start_val)

                ch_24h = get_change(86400000)
                ch_7d = get_change(86400000 * 7)
                ch_30d = get_change(86400000 * 30)
                
                def fmt_ch(v):
                    c = "🟢" if v >= 0 else "🔴"
                    return f"{c} ${pretty_float(v, 2)}"

                pnl_stats += f"\n   24h: {fmt_ch(ch_24h)} | 7d: {fmt_ch(ch_7d)} | 30d: {fmt_ch(ch_30d)}"
            except Exception:
                pass
        
        # Aggregate
        g_spot_eq += w_spot_eq
        g_perps_eq += w_perps_eq
        g_spot_upnl += w_spot_upnl
        g_perps_upnl += w_perps_upnl
        
        # Build Wallet Card
        w_total = w_spot_eq + w_perps_eq
        
        card = f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b>"
        card += f"\n   <b>Total: ${pretty_float(w_total, 2)}</b>"
        if w_spot_eq > 1:
            s_u_icon = "🟢" if w_spot_upnl >= 0 else "🔴"
            card += f"\n   🔹 Spot: ${pretty_float(w_spot_eq, 2)} (uPnL: {s_u_icon}${pretty_float(w_spot_upnl, 2)})"
        if w_perps_eq > 1 or w_perps_upnl != 0:
            p_u_icon = "🟢" if w_perps_upnl >= 0 else "🔴"
            card += f"\n   🔸 Perps: ${pretty_float(w_perps_eq, 2)} (uPnL: {p_u_icon}${pretty_float(w_perps_upnl, 2)})"
        
        if pnl_stats:
            card += pnl_stats
            
        wallet_cards.append(card)

    # Global Stats Card
    g_total = g_spot_eq + g_perps_eq
    g_upnl = g_spot_upnl + g_perps_upnl
    g_u_icon = "🟢" if g_upnl >= 0 else "🔴"
    
    header = f"{_t(lang, 'pnl_title')}\n\n"
    header += f"💰 <b>Global Net Worth: ${pretty_float(g_total, 2)}</b>\n"
    header += f"   🔹 Spot: ${pretty_float(g_spot_eq, 2)}\n"
    header += f"   🔸 Perps: ${pretty_float(g_perps_eq, 2)}\n"
    header += f"   📊 Total uPnL: {g_u_icon} <b>${pretty_float(g_upnl, 2)}</b>"
    
    text = header + "\n\n" + "\n\n".join(wallet_cards)
    await call.message.edit_text(text, reply_markup=_back_kb(lang), parse_mode="HTML")
