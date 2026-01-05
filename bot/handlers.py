from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.services import (
    get_symbol_name, get_mid_price, get_open_orders, get_spot_balances, 
    get_perps_state, pretty_float, get_user_portfolio, get_perps_context
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
        "alert_usage": "⚠️ Используй: <code>/alert ETH 3500</code> (бот сам поймет > или <)",
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
    }
    en = {
        "welcome": "👋 <b>Velox Terminal</b>\n\nReal-time Hyperliquid portfolio monitoring.",
        "set_wallet": "⚠️ No wallet connected. Use /add_wallet <code>0x...</code>",
        "tracking": "✅ Tracking: <code>{wallet}</code>",
        "alert_added": "✅ Alert set: <b>{symbol}</b> {dir} <b>${price}</b>",
        "alert_usage": "⚠️ Usage: <code>/alert ETH 3500</code> (auto-detects > or <)",
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
                if amount <= 0: continue
                
                px = 0.0
                if ws: px = ws.get_price(coin_name)
                if not px: px = await get_mid_price(coin_name)
                
                val = amount * px
                wallet_total += val
                wallet_lines.append(f"▫️ <b>{coin_name}</b>: {amount:.4f} (${val:.0f})")

        perps_equity = 0.0
        margin_used = 0.0
        if perps_state and "marginSummary" in perps_state:
            ms = perps_state["marginSummary"]
            perps_equity = float(ms.get("accountValue", 0) or 0)
            margin_used = float(ms.get("totalMarginUsed", 0) or 0)

        header = f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b>"
        body = ""
        if wallet_lines:
            body += f"\n   <b>Spot:</b> ${pretty_float(wallet_total, 2)}\n   " + "\n   ".join(wallet_lines)
        if perps_equity > 1:
             body += f"\n   <b>Perps Eq:</b> ${pretty_float(perps_equity, 2)}"
             body += f"\n   ⚠️ Margin: ${pretty_float(margin_used, 2)}"
        
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

@router.callback_query(F.data == "cb_market")
async def cb_market(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    ws = getattr(call.message.bot, "ws_manager", None)
    symbols = ["BTC", "ETH", "HYPE", "SOL", "PURR"]
    lines = []
    for sym in symbols:
        p = 0.0
        if ws: p = ws.get_price(sym)
        if not p: p = await get_mid_price(sym)
        lines.append(f"🔹 <b>{sym}</b>: ${pretty_float(p, 4)}")
    
    # Add timestamp
    ts = time.strftime("%H:%M:%S", time.gmtime())
    text = f"{_t(lang, 'market_title')} (updated {ts})\n\n" + "\n".join(lines)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Refresh", callback_data="cb_market")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_menu")
    kb.adjust(1)
    
    # Use suppress=True for same content error if user spams refresh
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.answer()


@router.callback_query(F.data == "cb_pnl")
async def cb_pnl_placeholder(call: CallbackQuery):
    await call.answer("Coming soon!")
