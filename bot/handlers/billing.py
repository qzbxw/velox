import logging
import time
import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery
from bot.database import db
from bot.locales import _t
from bot.billing import (
    normalize_plan, get_plan_star_price, get_plan_title, TEST_BILLING_ADMIN_IDS
)
from bot.handlers._common import (
    smart_edit, _build_billing_ui, _build_stars_invoice_payload, _parse_stars_invoice_payload,
    LabeledPrice
)

router = Router(name="billing")
logger = logging.getLogger(__name__)

@router.message(Command("billing"))
async def cmd_billing(message: Message):
    lang = await db.get_lang(message.chat.id)
    text, kb = await _build_billing_ui(message.chat.id, lang)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "cb_billing")
async def cb_billing(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    text, kb = await _build_billing_ui(call.message.chat.id, lang)
    await smart_edit(call, text, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("bill_buy:"))
async def cb_billing_buy(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    _, plan, months_str = call.data.split(":")
    months = int(months_str)
    plan = normalize_plan(plan)
    amount = get_plan_star_price(plan, months)
    if amount <= 0:
        await call.answer("Stars price not configured.", show_alert=True)
        return
    await call.message.bot.send_invoice(
        chat_id=call.message.chat.id,
        title=_t(lang, "billing_invoice_title", plan=get_plan_title(plan, lang)),
        description=_t(lang, "billing_invoice_desc", plan=get_plan_title(plan, lang), months=months),
        payload=_build_stars_invoice_payload(call.message.chat.id, plan, months),
        currency="XTR",
        prices=[LabeledPrice(label=f"{get_plan_title(plan, lang)} {months}M", amount=amount)],
        provider_token=""
    )
    await call.answer()

@router.pre_checkout_query()
async def on_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    payload = _parse_stars_invoice_payload(pre_checkout_query.invoice_payload)
    if not payload:
        await pre_checkout_query.answer(ok=False, error_message="Invalid payload.")
        return
    if (payload[0] != pre_checkout_query.from_user.id or 
        get_plan_star_price(payload[1], payload[2]) != int(pre_checkout_query.total_amount)):
        await pre_checkout_query.answer(ok=False, error_message="Validation failed.")
        return
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    payment = message.successful_payment
    if not payment:
        return
    payload = _parse_stars_invoice_payload(payment.invoice_payload)
    if not payload or payload[0] != message.chat.id:
        return
    if await db.record_billing_payment({
        "user_id": message.chat.id,
        "plan": payload[1],
        "months": payload[2],
        "currency": payment.currency,
        "total_amount": int(payment.total_amount),
        "telegram_payment_charge_id": payment.telegram_payment_charge_id,
        "invoice_payload": payment.invoice_payload,
        "created_at": int(time.time()),
        "source": "telegram_stars"
    }):
        until = await db.activate_billing_subscription(message.chat.id, payload[1], payload[2], source="telegram_stars")
        await message.answer(
            _t(
                await db.get_lang(message.chat.id),
                "billing_payment_success",
                plan=get_plan_title(payload[1], await db.get_lang(message.chat.id)),
                months=payload[2],
                date=datetime.datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
            ),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("bill_test:"))
async def cb_billing_test(call: CallbackQuery):
    if call.message.chat.id not in TEST_BILLING_ADMIN_IDS:
        await call.answer("Forbidden", show_alert=True)
        return
    lang = await db.get_lang(call.message.chat.id)
    parts = call.data.split(":")
    action = parts[1]
    if action == "set":
        p = normalize_plan(parts[2] if len(parts) > 2 else "free")
        await db.set_billing_subscription(call.message.chat.id, p, source="manual_test")
        await call.answer(_t(lang, "billing_plan_set", plan=get_plan_title(p, lang)), show_alert=True)
    elif action == "reset_usage":
        await db.reset_daily_usage(call.message.chat.id)
        await call.answer(_t(lang, "billing_usage_reset"), show_alert=True)
    
    text, kb = await _build_billing_ui(call.message.chat.id, lang)
    await smart_edit(call, text, reply_markup=kb)
