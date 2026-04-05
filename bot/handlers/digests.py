import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.database import db
from bot.locales import _t
from bot.config import DIGEST_TARGETS
from bot.services import (
    get_user_portfolio
)
from bot.utils import pretty_float
from bot.handlers._common import (
    smart_edit, _back_kb, _ensure_billing_feature, _ensure_billing_digest_slot,
    _count_enabled_digests, _build_digest_settings_ui, _digest_label_key, _valid_hhmm
)
from bot.handlers.states import SettingsStates

router = Router(name="digests")
logger = logging.getLogger(__name__)

@router.callback_query(F.data == "cb_digest_settings_menu")
async def cb_digest_settings_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "digests", "billing_feature_digests", is_callback=True): return
    text, kb = await _build_digest_settings_ui(call.message.chat.id, lang)
    await smart_edit(call, text, reply_markup=kb); await call.answer()

@router.callback_query(F.data.startswith("dg_toggle:"))
async def cb_digest_toggle(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "digests", "billing_feature_digests", is_callback=True): return
    target = call.data.split(":", 1)[1]
    if target not in DIGEST_TARGETS: await call.answer("Invalid digest"); return
    cfg = await db.get_digest_settings(call.message.chat.id)
    if not bool(cfg.get(target, {}).get("enabled", False)):
        if not await _ensure_billing_digest_slot(call, call.message.chat.id, lang, _count_enabled_digests(cfg), is_callback=True): return
    enabled = await db.toggle_digest_enabled(call.message.chat.id, target)
    await call.answer(_t(lang, "digest_toggle_done").format(state="ON" if enabled else "OFF"))
    text, kb = await _build_digest_settings_ui(call.message.chat.id, lang)
    await smart_edit(call, text, reply_markup=kb)

@router.callback_query(F.data.startswith("dg_set_time:"))
async def cb_digest_set_time(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "digests", "billing_feature_digests", is_callback=True): return
    target = call.data.split(":", 1)[1]
    if target not in DIGEST_TARGETS: await call.answer("Invalid digest"); return
    await state.update_data(digest_target=target, digest_menu_msg_id=call.message.message_id)
    await smart_edit(call, _t(lang, "digest_time_prompt").format(name=_t(lang, _digest_label_key(target))), reply_markup=_back_kb(lang, "cb_digest_settings_menu"))
    await state.set_state(SettingsStates.waiting_for_digest_time); await call.answer()

@router.message(SettingsStates.waiting_for_digest_time)
async def process_digest_time_state(message: Message, state: FSMContext):
    lang, data = await db.get_lang(message.chat.id), await state.get_data()
    target = data.get("digest_target")
    if target not in DIGEST_TARGETS: await state.clear(); await message.answer("❌ Invalid digest target."); return
    parsed = _valid_hhmm(message.text.strip())
    if not parsed:
        await message.answer(_t(lang, "digest_invalid_time"), parse_mode="HTML")
        return
    await db.set_digest_time(message.chat.id, target, parsed)
    await state.clear()
    try:
        await message.delete()
    except Exception: pass
    text, kb = await _build_digest_settings_ui(message.chat.id, lang)
    msg_id = data.get("digest_menu_msg_id")
    if msg_id:
        try:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception: pass
    await message.answer(f"{_t(lang, 'digest_time_saved').format(time=parsed)}\n\n{text}", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "cb_manual_digest")
async def cb_manual_digest(call: CallbackQuery):
    await call.answer("Generating Digest..."); lang, wallets = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id)
    if not wallets: await call.message.answer("No wallet tracked."); return
    portf = await get_user_portfolio(wallets[0])
    if not portf or not isinstance(portf, dict): await call.message.answer("No data available."); return
    h = portf.get("data", {}).get("accountValueHistory", [])
    if not h: await call.message.answer("No history available."); return
    h.sort(key=lambda x: x[0]); current_val, prev_val = float(h[-1][1]), float(h[0][1]); diff = current_val - prev_val; pct = (diff / prev_val * 100) if prev_val > 0 else 0.0
    from bot.locales import _t; text = f"📊 <b>Manual Digest</b>\n\nWallet: <code>{wallets[0][:6]}...</code>\nNet Worth: <b>${pretty_float(current_val, 2)}</b>\nAll-time PnL: {'🟢' if diff >= 0 else '🔴'} <b>${pretty_float(diff, 2)}</b> ({pct:+.2f}%)\n\n<i>Generated manually.</i>"
    await call.message.answer(text, parse_mode="HTML")
