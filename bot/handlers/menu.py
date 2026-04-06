from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.database import db
from bot.locales import _t
from bot.config import settings
from bot.handlers._common import (
    smart_edit, _main_menu_text, _main_menu_kb, _overview_kb, 
    _portfolio_kb, _trading_kb, _market_kb, _vaults_kb,
    _dashboard_kb, _alerts_kb, _ai_market_kb
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="menu")

@router.message(Command("start"))
async def cmd_start(message: Message):
    lang = await db.get_lang(message.chat.id)
    wallets = await db.list_wallets(message.chat.id)

    if not wallets:
        # Onboarding for new users
        text = _t(lang, "welcome") + "\n\n" + _t(lang, "set_wallet")
        builder = InlineKeyboardBuilder()
        builder.button(text=_t(lang, "btn_wallets"), callback_data="cb_add_wallet_prompt")
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        text = _main_menu_text(lang, wallets)
        kb = _main_menu_kb(lang)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    
    await db.add_user(message.chat.id, None)

@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()

@router.callback_query(F.data == "cb_menu")
async def cb_menu(call: CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    
    if not wallets:
        text = _t(lang, "welcome") + "\n\n" + _t(lang, "set_wallet")
        builder = InlineKeyboardBuilder()
        builder.button(text=_t(lang, "btn_wallets"), callback_data="cb_add_wallet_prompt")
        await smart_edit(call, text, reply_markup=builder.as_markup())
    else:
        text = _main_menu_text(lang, wallets)
        await smart_edit(call, text, reply_markup=_main_menu_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:dashboard")
async def cb_sub_dashboard(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "cat_dashboard"), reply_markup=_dashboard_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:alerts")
async def cb_sub_alerts(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "cat_alerts"), reply_markup=_alerts_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:ai_market")
async def cb_sub_ai_market(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "cat_ai_market"), reply_markup=_ai_market_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:market")
async def cb_sub_market(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "cat_market"), reply_markup=_market_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:overview")
async def cb_sub_overview(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "menu_overview"), reply_markup=_overview_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:portfolio")
async def cb_sub_portfolio(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "menu_portfolio"), reply_markup=_portfolio_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:trading")
async def cb_sub_trading(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "menu_trading"), reply_markup=_trading_kb(lang))
    await call.answer()

@router.callback_query(F.data == "sub:vaults")
async def cb_sub_vaults(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "menu_vaults"), reply_markup=_vaults_kb(lang))
    await call.answer()

@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = await db.get_lang(message.chat.id)
    await message.answer(_t(lang, "help_msg"), parse_mode="HTML")

@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message):
    lang = await db.get_lang(message.chat.id)
    contact = (settings.PAY_SUPPORT_CONTACT or "").strip()
    if not contact:
        contact = "@BotFather"
    await message.answer(_t(lang, "pay_support_msg", contact=contact), parse_mode="HTML")
