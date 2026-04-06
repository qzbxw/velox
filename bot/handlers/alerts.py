import logging
import html
import time
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_mid_price, pretty_float, get_perps_context
)
from bot.handlers._common import (
    smart_edit, _back_kb, _ensure_billing_quota, _settings_kb
)
from bot.handlers.states import AlertStates

router = Router(name="alerts")
logger = logging.getLogger(__name__)

@router.message(Command("alert"))
async def cmd_alert(message: Message):
    lang = await db.get_lang(message.chat.id)
    alerts = await db.get_user_alerts(message.chat.id)
    if not await _ensure_billing_quota(message, message.chat.id, lang, "alerts", len(alerts), "billing_feature_alerts"):
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer(_t(lang, "alert_usage"), parse_mode="HTML")
        return
    symbol = html.escape(args[1].upper())
    ws = getattr(message.bot, "ws_manager", None)
    try:
        target = float(args[2].replace(",", "."))
    except ValueError:
        await message.answer(_t(lang, "alert_error"))
        return
    current = (ws.get_price(symbol) if ws else 0.0) or await get_mid_price(symbol)
    if not current:
        await message.answer(_t(lang, "unknown_price", symbol=symbol), parse_mode="HTML")
        return
    direction = "above" if target > current else "below"
    await db.add_price_alert(message.chat.id, symbol, target, direction)
    await message.answer(_t(lang, "alert_added").format(symbol=symbol, dir="📈" if direction == "above" else "📉", price=pretty_float(target)), parse_mode="HTML")

@router.callback_query(F.data.startswith("cb_alerts"))
async def cb_alerts(call: CallbackQuery):
    parts = call.data.split(":")
    back_target = parts[1] if len(parts) > 1 else "sub:market"
    lang = await db.get_lang(call.message.chat.id)
    alerts = await db.get_user_alerts(call.message.chat.id)
    if not alerts:
        text = f"{_t(lang, 'market_title')} > <b>{_t(lang, 'btn_price_alerts')}</b>\n\n{_t(lang, 'no_alerts')}\n{_t(lang, 'alert_usage')}\n\n<i>Last update: {time.strftime('%H:%M:%S')}</i>"
        await smart_edit(call, text, reply_markup=_back_kb(lang, back_target))
        return
    
    kb = InlineKeyboardBuilder()
    text = _t(lang, "alerts_list") + "\n"
    for a in alerts:
        aid = str(a["_id"])
        s = a.get("symbol", "???")
        p = pretty_float(a.get("target", 0))
        d = "📈" if a.get("direction") == "above" else "📉"
        text += f"\n• {s} {d} {p}"
        kb.button(text=f"❌ {s} {p}", callback_data=f"del_alert:{aid}:{back_target}")
    
    kb.button(text="🗑️ Clear All", callback_data=f"clear_all_alerts:{back_target}")
    kb.button(text=_t(lang, "btn_back"), callback_data=back_target)
    kb.adjust(1)
    await smart_edit(call, text + f"\n\n<i>Last update: {time.strftime('%H:%M:%S')}</i>", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("clear_all_alerts"))
async def cb_clear_all_alerts(call: CallbackQuery):
    parts = call.data.split(":")
    back_target = parts[1] if len(parts) > 1 else "sub:market"
    await db.delete_all_user_alerts(call.message.chat.id)
    await call.answer(_t(await db.get_lang(call.message.chat.id), "deleted"))
    call.data = f"cb_alerts:{back_target}"
    await cb_alerts(call)

@router.callback_query(F.data.startswith("del_alert:"))
async def cb_del_alert(call: CallbackQuery):
    parts = call.data.split(":")
    aid = parts[1]
    back_target = parts[2] if len(parts) > 2 else "sub:market"
    if await db.delete_alert(aid):
        await call.answer(_t(await db.get_lang(call.message.chat.id), "deleted"))
    else:
        await call.answer("🗑️ Alert already removed or error")
    call.data = f"cb_alerts:{back_target}"
    await cb_alerts(call)

@router.callback_query(F.data.startswith("quick_alert:"))
async def cb_quick_alert(call: CallbackQuery):
    symbol = call.data.split(":")[1]
    lang = await db.get_lang(call.message.chat.id)
    current_price = await get_mid_price(symbol)
    if not current_price:
        await call.answer("❌ Cannot get price", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"📈 Above ${pretty_float(current_price * 1.03)}", callback_data=f"set_quick_alert:{symbol}:above:{current_price * 1.03}"),
        InlineKeyboardButton(text=f"📉 Below ${pretty_float(current_price * 0.97)}", callback_data=f"set_quick_alert:{symbol}:below:{current_price * 0.97}")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    await call.message.edit_text(
        f"🔔 <b>Quick Alert: {symbol}</b>\n\nCurrent price: <b>${pretty_float(current_price)}</b>\n\nChoose alert type:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("set_quick_alert:"))
async def cb_set_quick_alert(call: CallbackQuery):
    parts = call.data.split(":")
    symbol = parts[1]
    direction = parts[2]
    target = float(parts[3])
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_quota(call, call.message.chat.id, lang, "alerts", len(await db.get_user_alerts(call.message.chat.id)), "billing_feature_alerts", is_callback=True):
        return
    await db.add_price_alert(call.message.chat.id, symbol, target, direction)
    await call.answer(_t(lang, "alert_added", symbol=symbol, dir=direction, price=pretty_float(target)), show_alert=True)
    await cb_alerts(call)

@router.message(Command("watch"))
async def cmd_watch(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "watch_usage"), parse_mode="HTML")
        return
    symbol = args[1].upper()
    if len(symbol) > 10 or not symbol.isalnum():
        await message.answer(_t(lang, "watch_invalid"))
        return
    watchlist = await db.get_watchlist(message.chat.id)
    if symbol not in watchlist:
        if not await _ensure_billing_quota(message, message.chat.id, lang, "watchlist", len(watchlist), "billing_feature_watchlist"):
            return
    await db.add_watch_symbol(message.chat.id, symbol)
    ws = getattr(message.bot, "ws_manager", None)
    if ws:
        if symbol not in ws.watch_subscribers:
            ws.watch_subscribers[symbol] = set()
        ws.watch_subscribers[symbol].add(message.chat.id)
    await message.answer(_t(lang, "watch_added").format(symbol=symbol), parse_mode="HTML")

@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "unwatch_usage"), parse_mode="HTML")
        return
    symbol = args[1].upper()
    await db.remove_watch_symbol(message.chat.id, symbol)
    ws = getattr(message.bot, "ws_manager", None)
    if ws and symbol in ws.watch_subscribers:
        ws.watch_subscribers[symbol].discard(message.chat.id)
    await message.answer(_t(lang, "watch_removed").format(symbol=symbol), parse_mode="HTML")

@router.callback_query(F.data.startswith("cb_funding_alert_prompt"))
async def cb_funding_alert_prompt(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    back_target = parts[1] if len(parts) > 1 else "cb_settings"
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(alert_type="funding", menu_msg_id=call.message.message_id, back_target=back_target)
    await call.message.edit_text(_t(lang, "prompt_symbol"), reply_markup=_back_kb(lang, back_target), parse_mode="HTML")
    await state.set_state(AlertStates.waiting_for_symbol)
    await call.answer()

@router.callback_query(F.data.startswith("cb_oi_alert_prompt"))
async def cb_oi_alert_prompt(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    back_target = parts[1] if len(parts) > 1 else "cb_settings"
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(alert_type="oi", menu_msg_id=call.message.message_id, back_target=back_target)
    await call.message.edit_text(_t(lang, "prompt_symbol"), reply_markup=_back_kb(lang, back_target), parse_mode="HTML")
    await state.set_state(AlertStates.waiting_for_symbol)
    await call.answer()

@router.message(AlertStates.waiting_for_symbol)
async def process_alert_symbol(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    symbol = message.text.strip().upper()
    data = await state.get_data()
    back_target = data.get("back_target", "cb_settings")
    if len(symbol) > 10 or not symbol.isalnum():
        await message.answer(_t(lang, "watch_invalid"))
        return
    await state.update_data(symbol=symbol)
    prompt = _t(lang, "prompt_target_funding") if data.get("alert_type") == "funding" else _t(lang, "prompt_target_oi")
    msg_id = data.get("menu_msg_id")
    try:
        await message.delete()
    except Exception:
        pass
    if msg_id:
        try:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=prompt, reply_markup=_back_kb(lang, back_target), parse_mode="HTML")
            await state.set_state(AlertStates.waiting_for_target)
            return
        except Exception:
            pass
    await message.answer(prompt, reply_markup=_back_kb(lang, back_target), parse_mode="HTML")
    await state.set_state(AlertStates.waiting_for_target)

@router.message(AlertStates.waiting_for_target)
async def process_alert_target(message: Message, state: FSMContext):
    try:
        await message.delete()
    except Exception:
        pass
    lang = await db.get_lang(message.chat.id)
    try:
        target = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer(_t(lang, "invalid_number"))
        return
    data = await state.get_data()
    symbol = data.get("symbol")
    a_type = data.get("alert_type")
    msg_id = data.get("menu_msg_id")
    back_target = data.get("back_target", "cb_settings")
    if not await _ensure_billing_quota(message, message.chat.id, lang, "alerts", len(await db.get_user_alerts(message.chat.id)), "billing_feature_alerts"):
        return
    ctx = await get_perps_context()
    universe = ctx[0].get("universe", []) if isinstance(ctx[0], dict) else ctx[0]
    asset_ctxs = ctx[1]
    idx = next((i for i, u in enumerate(universe) if (u["name"] if isinstance(u, dict) else u) == symbol), -1)
    current_val = 0.0
    if idx != -1 and idx < len(asset_ctxs):
        if a_type == "funding":
            current_val = float(asset_ctxs[idx].get("funding", 0)) * 24 * 365 * 100
        else:
            current_val = float(asset_ctxs[idx].get("openInterest", 0)) * float(asset_ctxs[idx].get("markPx", 0)) / 1e6
    direction = "above" if target > current_val else "below"
    await db.add_alert(message.chat.id, symbol, target, direction, a_type)
    success_msg = _t(lang, "funding_alert_set" if a_type == "funding" else "oi_alert_set", symbol=symbol, dir="📈" if direction == "above" else "📉", val=target)
    
    # After setting alert, we might want to go back to the sub-menu we came from
    target_kb = _settings_kb(lang)
    if back_target == "sub:alerts":
        from bot.handlers._common import _alerts_kb
        target_kb = _alerts_kb(lang)
    elif back_target == "cb_wallets_alerts_menu":
        from bot.handlers._common import _wallets_alerts_settings_kb
        target_kb = _wallets_alerts_settings_kb(lang)

    if msg_id:
        try:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=success_msg, reply_markup=target_kb, parse_mode="HTML")
            await state.clear()
            return
        except Exception:
            pass
    await message.answer(success_msg, reply_markup=target_kb, parse_mode="HTML")
    await state.clear()

@router.message(Command("f_alert"))
async def cmd_f_alert(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 3:
        await message.answer(_t(lang, "f_alert_usage"), parse_mode="HTML")
        return
    symbol = args[1].upper()
    target = float(args[2].replace(",", "."))
    if not await _ensure_billing_quota(message, message.chat.id, lang, "alerts", len(await db.get_user_alerts(message.chat.id)), "billing_feature_alerts"):
        return
    ctx = await get_perps_context()
    universe = ctx[0].get("universe", []) if isinstance(ctx[0], dict) else ctx[0]
    asset_ctxs = ctx[1]
    idx = next((i for i, u in enumerate(universe) if (u["name"] if isinstance(u, dict) else u) == symbol), -1)
    curr = float(asset_ctxs[idx].get("funding", 0)) * 24 * 365 * 100 if idx != -1 else 0.0
    direction = "above" if target > curr else "below"
    await db.add_alert(message.chat.id, symbol, target, direction, "funding")
    await message.answer(_t(lang, "funding_alert_set", symbol=symbol, dir="📈" if direction == "above" else "📉", val=target), parse_mode="HTML")

@router.message(Command("oi_alert"))
async def cmd_oi_alert(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 3:
        await message.answer(_t(lang, "oi_alert_usage"), parse_mode="HTML")
        return
    symbol = args[1].upper()
    target = float(args[2].replace(",", "."))
    if not await _ensure_billing_quota(message, message.chat.id, lang, "alerts", len(await db.get_user_alerts(message.chat.id)), "billing_feature_alerts"):
        return
    ctx = await get_perps_context()
    universe = ctx[0].get("universe", []) if isinstance(ctx[0], dict) else ctx[0]
    asset_ctxs = ctx[1]
    idx = next((i for i, u in enumerate(universe) if (u["name"] if isinstance(u, dict) else u) == symbol), -1)
    curr = float(asset_ctxs[idx].get("openInterest", 0)) * float(asset_ctxs[idx].get("markPx", 0)) / 1e6 if idx != -1 else 0.0
    direction = "above" if target > curr else "below"
    await db.add_alert(message.chat.id, symbol, target, direction, "oi")
    await message.answer(_t(lang, "oi_alert_set", symbol=symbol, dir="📈" if direction == "above" else "📉", val=target), parse_mode="HTML")
