import logging
import html
import time
import re
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.services import (
    pretty_float, get_user_portfolio
)
from bot.handlers._common import (
    smart_edit, smart_edit_media, _back_kb, _settings_kb, _ensure_billing_feature,
    _ensure_billing_quota, _valid_hhmm, _build_digest_settings_ui, DIGEST_TARGETS
)
from bot.handlers.states import SettingsStates

router = Router(name="settings")
logger = logging.getLogger(__name__)

@router.callback_query(F.data == "cb_settings")
async def cb_settings(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "settings_title"), reply_markup=_settings_kb(lang))
    await call.answer()

@router.callback_query(F.data == "cb_wallets_alerts_menu")
async def cb_wallets_alerts_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    from bot.handlers._common import _wallets_alerts_settings_kb
    await smart_edit(call, _t(lang, "btn_wallets_alerts"), reply_markup=_wallets_alerts_settings_kb(lang))
    await call.answer()

@router.callback_query(F.data == "cb_ai_config_menu")
async def cb_ai_config_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    from bot.handlers._common import _ai_config_kb
    await smart_edit(call, _t(lang, "btn_ai_config"), reply_markup=_ai_config_kb(lang))
    await call.answer()

@router.callback_query(F.data == "cb_digests_reports_menu")
async def cb_digests_reports_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    from bot.handlers._common import _digests_reports_kb
    await smart_edit(call, _t(lang, "btn_digests_reports"), reply_markup=_digests_reports_kb(lang))
    await call.answer()

@router.callback_query(F.data == "cb_lang_menu")
async def cb_lang_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="lang:ru")
    kb.button(text="🇬🇧 English", callback_data="lang:en")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
    kb.adjust(2, 1)
    await smart_edit(call, _t(lang, "lang_title"), reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("lang:"))
async def cb_set_lang(call: CallbackQuery):
    await db.set_lang(call.message.chat.id, call.data.split(":")[1])
    await cb_settings(call)

@router.callback_query(F.data == "cb_wallets_menu")
async def cb_wallets_menu(call: CallbackQuery):
    lang, wallets = await db.get_lang(call.message.chat.id), await db.list_wallets_full(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    if not wallets:
        kb.button(text="➕ Add Wallet", callback_data="cb_add_wallet_prompt")
        kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
        kb.adjust(1)
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=kb.as_markup(), parse_mode="HTML")
        return
    text = f"<b>{_t(lang, 'btn_wallets')}</b>\n\n"
    for w in wallets:
        addr, tag, thresh = w["address"], html.escape(w.get("tag") or "No Tag"), w.get("threshold", 0.0)
        text += f"• <code>{addr[:6]}...{addr[-4:]}</code>\n  Tag: <b>{tag}</b> | Min: <b>${thresh}</b>\n\n"
        kb.button(text=f"❌ Del {tag if tag != 'No Tag' else addr[:6]}", callback_data=f"cb_del_wallet:{addr}")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
    kb.adjust(1)
    await call.message.edit_text(text + "ℹ️ <i>Use /tag &lt;0x...&gt; &lt;Name&gt;\nUse /threshold &lt;0x...&gt; &lt;USD&gt;</i>", reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("cb_del_wallet:"))
async def cb_del_wallet(call: CallbackQuery):
    await db.remove_wallet(call.message.chat.id, call.data.split(":")[1])
    await cb_wallets_menu(call)

@router.callback_query(F.data.startswith("cb_add_wallet_prompt"))
async def cb_add_wallet_prompt(call: CallbackQuery, state: FSMContext = None):
    parts = call.data.split(":")
    back_target = parts[1] if len(parts) > 1 else "cb_wallets_menu"
    lang = await db.get_lang(call.message.chat.id)
    text = _t(lang, "add_wallet_prompt")
    await call.message.edit_text(text, reply_markup=_back_kb(lang, back_target), parse_mode="HTML")
    await call.answer()

@router.message(Command("add_wallet"))
async def cmd_add_wallet(message: Message):
    lang, args = await db.get_lang(message.chat.id), message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "add_wallet_usage"), parse_mode="HTML")
        return
    wallet = args[1].lower()
    if not wallet.startswith("0x") or len(wallet) != 42:
        await message.answer(_t(lang, "invalid_wallet_addr"), parse_mode="HTML")
        return
    wallets = await db.list_wallets(message.chat.id)
    if wallet not in wallets:
        if not await _ensure_billing_quota(message, message.chat.id, lang, "wallets", len(wallets), "billing_feature_wallets"):
            return
    await db.add_wallet(message.chat.id, wallet)
    ws = getattr(message.bot, "ws_manager", None)
    if ws:
        ws.track_wallet(wallet)
        await ws.subscribe_user(wallet)
    
    # After adding, if it was the first wallet, show main menu
    if len(wallets) == 0:
        from bot.handlers._common import _main_menu_text, _main_menu_kb
        await message.answer(_t(lang, "tracking").format(wallet=wallet), parse_mode="HTML")
        await message.answer(_main_menu_text(lang, [wallet]), reply_markup=_main_menu_kb(lang), parse_mode="HTML")
    else:
        await message.answer(_t(lang, "tracking").format(wallet=wallet), reply_markup=_back_kb(lang, "cb_wallets_menu"), parse_mode="HTML")

@router.message(Command("tag"))
async def cmd_tag(message: Message):
    lang, args = await db.get_lang(message.chat.id), message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(_t(lang, "tag_usage"), parse_mode="HTML")
        return
    await db.update_wallet_settings(message.chat.id, args[1].lower(), tag=args[2])
    await message.answer(_t(lang, "settings_updated"))

@router.message(Command("threshold"))
async def cmd_threshold(message: Message):
    lang, args = await db.get_lang(message.chat.id), message.text.split()
    if len(args) < 3:
        await message.answer(_t(lang, "threshold_usage"), parse_mode="HTML")
        return
    try:
        val = float(args[2].replace(",", "."))
        await db.update_wallet_settings(message.chat.id, args[1].lower(), threshold=val)
        await message.answer(_t(lang, "settings_updated"))
    except ValueError:
        await message.answer(_t(lang, "invalid_number"))

@router.callback_query(F.data == "set_prox_prompt")
async def cb_set_prox_prompt(call: CallbackQuery, state: FSMContext):
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(
        _t(await db.get_lang(call.message.chat.id), "prox_input"),
        reply_markup=_back_kb(await db.get_lang(call.message.chat.id), "cb_wallets_alerts_menu"),
        parse_mode="HTML"
    )
    await state.set_state(SettingsStates.waiting_for_prox)
    await call.answer()

@router.callback_query(F.data == "set_vol_prompt")
async def cb_set_vol_prompt(call: CallbackQuery, state: FSMContext):
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(
        _t(await db.get_lang(call.message.chat.id), "vol_input"),
        reply_markup=_back_kb(await db.get_lang(call.message.chat.id), "cb_wallets_alerts_menu"),
        parse_mode="HTML"
    )
    await state.set_state(SettingsStates.waiting_for_vol)
    await call.answer()

@router.callback_query(F.data == "set_whale_prompt")
async def cb_set_whale_prompt(call: CallbackQuery, state: FSMContext):
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(
        _t(await db.get_lang(call.message.chat.id), "whale_input"),
        reply_markup=_back_kb(await db.get_lang(call.message.chat.id), "cb_wallets_alerts_menu"),
        parse_mode="HTML"
    )
    await state.set_state(SettingsStates.waiting_for_whale)
    await call.answer()

@router.message(SettingsStates.waiting_for_prox)
async def process_set_prox_state(message: Message, state: FSMContext):
    lang, data = await db.get_lang(message.chat.id), await state.get_data()
    try:
        val = float(message.text.replace(",", ".")) / 100.0
        await db.update_user_settings(message.chat.id, {"prox_alert_pct": val})
        res = "✅ " + _t(lang, "prox_set", val=val*100)
    except ValueError:
        res = "❌ " + _t(lang, "invalid_number")
    
    back_target = data.get("back_target") or data.get("market_back_target") or "cb_wallets_alerts_menu"
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    
    if back_target == "cb_whales":
        from bot.handlers.market import cb_whales as target_handler
    else:
        from bot.handlers.settings import cb_wallets_alerts_menu as target_handler
    
    await message.answer(res)
    dummy_call = CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=back_target)
    await target_handler(dummy_call)

@router.message(SettingsStates.waiting_for_vol)
async def process_set_vol_state(message: Message, state: FSMContext):
    lang, data = await db.get_lang(message.chat.id), await state.get_data()
    try:
        val = float(message.text.replace(",", ".")) / 100.0
        await db.update_user_settings(message.chat.id, {"watch_alert_pct": val})
        res = "✅ " + _t(lang, "vol_set", val=val*100)
    except ValueError:
        res = "❌ " + _t(lang, "invalid_number")
    
    back_target = data.get("back_target") or data.get("market_back_target") or "cb_wallets_alerts_menu"
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    
    if back_target == "cb_whales":
        from bot.handlers.market import cb_whales as target_handler
    else:
        from bot.handlers.settings import cb_wallets_alerts_menu as target_handler
    
    await message.answer(res)
    dummy_call = CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=back_target)
    await target_handler(dummy_call)

@router.message(SettingsStates.waiting_for_whale)
async def process_set_whale_state(message: Message, state: FSMContext):
    lang, data = await db.get_lang(message.chat.id), await state.get_data()
    try:
        val = float(message.text.replace(",", "."))
        await db.update_user_settings(message.chat.id, {"whale_threshold": val})
        res = "✅ " + _t(lang, "whale_set", val=pretty_float(val))
    except ValueError:
        res = "❌ " + _t(lang, "invalid_number")
    
    back_target = data.get("back_target") or data.get("market_back_target") or "cb_wallets_alerts_menu"
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    
    if back_target == "cb_whales":
        from bot.handlers.market import cb_whales as target_handler
    else:
        from bot.handlers.settings import cb_wallets_alerts_menu as target_handler
    
    await message.answer(res)
    dummy_call = CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=back_target)
    await target_handler(dummy_call)

@router.message(Command("set_prox"))
async def cmd_set_prox(message: Message):
    lang, args = await db.get_lang(message.chat.id), message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "set_prox_usage"), parse_mode="HTML")
        return
    try:
        val = float(args[1].replace(",", ".")) / 100.0
        await db.update_user_settings(message.chat.id, {"prox_alert_pct": val})
        await message.answer(_t(lang, "prox_set", val=val*100), parse_mode="HTML")
    except ValueError:
        await message.answer(_t(lang, "invalid_number"))

@router.message(Command("set_vol"))
async def cmd_set_vol(message: Message):
    lang, args = await db.get_lang(message.chat.id), message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "set_vol_usage"), parse_mode="HTML")
        return
    try:
        val = float(args[1].replace(",", ".")) / 100.0
        await db.update_user_settings(message.chat.id, {"watch_alert_pct": val})
        await message.answer(_t(lang, "vol_set", val=val*100), parse_mode="HTML")
    except ValueError:
        await message.answer(_t(lang, "invalid_number"))

@router.message(Command("set_whale"))
async def cmd_set_whale(message: Message):
    lang, args = await db.get_lang(message.chat.id), message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "set_whale_usage"), parse_mode="HTML")
        return
    try:
        val = float(args[1].replace(",", "."))
        await db.update_user_settings(message.chat.id, {"whale_threshold": val})
        await message.answer(_t(lang, "whale_set", val=pretty_float(val)), parse_mode="HTML")
    except ValueError:
        await message.answer(_t(lang, "invalid_number"))

@router.callback_query(F.data == "cb_flex_menu")
async def cb_flex_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "flex", "billing_feature_flex", is_callback=True):
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "flex_period_day"), callback_data="cb_flex_gen:day")
    kb.button(text=_t(lang, "flex_period_week"), callback_data="cb_flex_gen:week")
    kb.button(text=_t(lang, "flex_period_month"), callback_data="cb_flex_gen:month")
    kb.button(text=_t(lang, "flex_period_all"), callback_data="cb_flex_gen:all")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
    kb.adjust(2, 2, 1)
    await smart_edit(call, _t(lang, "flex_title"), reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("cb_flex_gen:"))
async def cb_flex_gen(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "flex", "billing_feature_flex", is_callback=True):
        return
    period = call.data.split(":")[1]
    await call.answer("Generating...")
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.answer(_t(lang, "need_wallet"))
        return
    period_label = {
        "day": _t(lang, "flex_period_day"),
        "week": _t(lang, "flex_period_week"),
        "month": _t(lang, "flex_period_month"),
        "all": _t(lang, "flex_period_all")
    }.get(period, "Period")
    wallet_label, total_period_pnl, total_start_equity, has_data = (f"{wallets[0][:6]}...{wallets[0][-4:]}" if len(wallets) == 1 else f"{len(wallets)} Wallets"), 0.0, 0.0, False
    target_time = time.time() * 1000 - {"day": 86400000, "week": 86400000 * 7, "month": 86400000 * 30, "all": 9999999999999}.get(period, 0)
    for wallet in wallets:
        portf = await get_user_portfolio(wallet)
        if not portf:
            continue
        target_data = next((i[1] for i in portf if isinstance(i, list) and len(i) == 2 and i[0] == "allTime"), portf[0][1] if portf and isinstance(portf[0], list) else portf.get("data", {}) if isinstance(portf, dict) else {})
        equity_hist, pnl_hist = target_data.get("accountValueHistory", []), target_data.get("pnlHistory", [])
        if not equity_hist or not pnl_hist:
            continue
        equity_hist.sort(key=lambda x: x[0])
        pnl_hist.sort(key=lambda x: x[0])
        if period == "all":
            p_start, e_start = 0.0, float(equity_hist[0][1]) - float(pnl_hist[0][1])
        else:
            closest_p = min(pnl_hist, key=lambda x: abs(x[0] - target_time))
            p_start = float(closest_p[1])
            e_start = float(min(equity_hist, key=lambda x: abs(x[0] - closest_p[0]))[1])
        total_period_pnl += (float(pnl_hist[-1][1]) - p_start)
        total_start_equity += max(0, (float(equity_hist[-1][1]) - float(pnl_hist[-1][1])) if period == "all" else e_start)
        has_data = True
    if not has_data:
        await call.message.answer("❌ Not enough history data.")
        return
    from bot.analytics import prepare_account_flex_data
    from bot.renderer import render_html_to_image
    try:
        buf = await render_html_to_image("account_flex.html", prepare_account_flex_data(total_period_pnl, (total_period_pnl / total_start_equity * 100) if total_start_equity > 0 else (100.0 if total_period_pnl > 0 else 0.0), period_label, total_period_pnl >= 0, wallet_label))
        await smart_edit_media(call, BufferedInputFile(buf.read(), filename="equity_flex.png"), f"📊 <b>{period_label} Account Summary</b>", reply_markup=_back_kb(lang, "cb_flex_menu"))
    except Exception as e:
        logger.error(f"Error rendering flex card: {e}")
        await call.message.answer("❌ Error generating image.")
