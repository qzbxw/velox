import asyncio
import logging
import time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.config import HLP_VAULT_ADDR
from bot.services import (
    get_user_vault_equities, get_hlp_info, pretty_float
)
from bot.handlers._common import (
    smart_edit, _back_kb, _vault_display_name, _is_hlp_vault, _fmt_period_change,
    _ensure_billing_feature, _ensure_billing_digest_slot, _count_enabled_digests,
    _collect_user_vault_catalog, _vault_cfg_key
)

router = Router(name="vaults")
logger = logging.getLogger(__name__)

@router.callback_query(F.data == "cb_vaults_overview")
async def cb_vaults_overview(call: CallbackQuery):
    await call.answer("Loading vaults...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, "sub:vaults"))
        return

    sections = []
    global_total = 0.0
    vault_count = 0

    vault_lists = await asyncio.gather(*(get_user_vault_equities(w) for w in wallets), return_exceptions=True)
    for wallet, vault_equities in zip(wallets, vault_lists):
        if isinstance(vault_equities, Exception) or not isinstance(vault_equities, list):
            continue

        rows = []
        wallet_total = 0.0
        for v in sorted(vault_equities, key=lambda x: float(x.get("equity", 0) or 0), reverse=True):
            v_addr = str(v.get("vaultAddress", "")).lower()
            equity = float(v.get("equity", 0) or 0)
            if not v_addr or equity <= 0:
                continue
            wallet_total += equity
            global_total += equity
            vault_count += 1
            rows.append(
                f"🏛 <b>{_vault_display_name(v_addr)}</b>: ${pretty_float(equity, 2)}\n"
                f"   <code>{v_addr[:10]}...{v_addr[-8:]}</code>"
            )

        if rows:
            sections.append(
                f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b> • ${pretty_float(wallet_total, 2)}\n" + "\n".join(rows)
            )

    if not sections:
        text = f"{_t(lang, 'vaults_title')}\n\n<i>{_t(lang, 'no_vaults')}</i>"
    else:
        text = (
            f"{_t(lang, 'vaults_title')}\n\n"
            f"💰 <b>{_t(lang, 'total_lbl')}:</b> ${pretty_float(global_total, 2)}\n"
            f"🏛 <b>{_t(lang, 'vault_positions')}:</b> {vault_count}\n\n"
            + "\n\n".join(sections)
        )

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data="cb_vaults_overview"),
        InlineKeyboardButton(text=_t(lang, "btn_hlp_snapshot"), callback_data="cb_hlp_snapshot")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_vault_reports"), callback_data="cb_vault_reports_menu")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="sub:vaults"))
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_hlp_snapshot")
async def cb_hlp_snapshot(call: CallbackQuery):
    await call.answer("Loading HLP...")
    lang = await db.get_lang(call.message.chat.id)
    user_id = call.message.chat.id
    wallets = await db.list_wallets(user_id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, "sub:vaults"))
        return

    now_ts = int(time.time())
    periods = {
        "24h": now_ts - 86400,
        "7d": now_ts - (7 * 86400),
        "30d": now_ts - (30 * 86400)
    }

    vault_lists = await asyncio.gather(*(get_user_vault_equities(w) for w in wallets), return_exceptions=True)
    hlp_info = await get_hlp_info()

    total_vault_equity = 0.0
    total_hlp_equity = 0.0
    wallet_hlp_rows = []
    current_hlp_by_wallet = {}

    for wallet, vaults in zip(wallets, vault_lists):
        if isinstance(vaults, Exception) or not isinstance(vaults, list):
            continue

        wallet_hlp = 0.0
        for v in vaults:
            v_addr = str(v.get("vaultAddress", "")).lower()
            v_eq = float(v.get("equity", 0) or 0)
            if v_eq <= 0:
                continue
            total_vault_equity += v_eq
            if _is_hlp_vault(v_addr):
                wallet_hlp += v_eq

        if wallet_hlp > 0:
            current_hlp_by_wallet[wallet.lower()] = wallet_hlp
            total_hlp_equity += wallet_hlp
            wallet_hlp_rows.append(f"• <code>{wallet[:6]}...{wallet[-4:]}</code>: ${pretty_float(wallet_hlp, 2)}")
            await db.upsert_vault_snapshot(user_id, wallet, HLP_VAULT_ADDR, wallet_hlp, now_ts)

    if total_hlp_equity <= 0:
        await smart_edit(call, f"{_t(lang, 'hlp_title')}\n\n<i>{_t(lang, 'hlp_not_found')}</i>", reply_markup=_back_kb(lang, "sub:vaults"))
        return

    period_lines = []
    for label, ts in periods.items():
        base_sum = 0.0
        current_sum = 0.0
        covered = 0
        total = len(current_hlp_by_wallet)
        for wallet, current_eq in current_hlp_by_wallet.items():
            doc = await db.get_latest_vault_snapshot_before(user_id, wallet, HLP_VAULT_ADDR, ts)
            if not doc:
                continue
            base_sum += float(doc.get("equity", 0) or 0)
            current_sum += current_eq
            covered += 1

        key = "hlp_change_24h" if label == "24h" else ("hlp_change_7d" if label == "7d" else "hlp_change_30d")
        if covered == 0:
            period_lines.append(f"{_t(lang, key)}: {_t(lang, 'vault_change_na')}")
        else:
            change = _fmt_period_change(current_sum, base_sum)
            if covered < total:
                change = f"~ {change} ({_t(lang, 'hlp_partial_history')})"
            period_lines.append(f"{_t(lang, key)}: {change}")

    summary = hlp_info.get("summary", {}) if isinstance(hlp_info, dict) else {}
    share_px = float(summary.get("sharePx", 0) or 0)
    account_value = float(summary.get("accountValue", 0) or 0)
    day_pnl = float(hlp_info.get("dayPnl", 0) or 0) if isinstance(hlp_info, dict) else 0.0
    apr = (day_pnl / account_value) * 365 * 100 if account_value > 0 else 0.0

    hlp_share = (total_hlp_equity / total_vault_equity) * 100 if total_vault_equity > 0 else 0.0
    concentration_note = _t(lang, "hlp_concentration_high") if hlp_share >= 70 else _t(lang, "hlp_concentration_ok")

    text = (
        f"{_t(lang, 'hlp_title')}\n\n"
        f"💰 {_t(lang, 'hlp_my_equity')}: <b>${pretty_float(total_hlp_equity, 2)}</b>\n"
        f"📊 {_t(lang, 'hlp_vault_share')}: <b>{hlp_share:.1f}%</b>\n"
        f"{concentration_note}\n\n"
        f"{_t(lang, 'hlp_share_price')}: <b>${pretty_float(share_px, 4)}</b>\n"
        f"{_t(lang, 'hlp_tvl')}: <b>${pretty_float(account_value, 0)}</b>\n"
        f"{_t(lang, 'hlp_day_pnl')}: <b>{pretty_float(day_pnl, 2)}</b>\n"
        f"{_t(lang, 'hlp_est_apr')}: <b>{apr:+.2f}%</b>\n\n"
        + "\n".join(period_lines)
        + "\n\n"
        + "\n".join(wallet_hlp_rows)
    )

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data="cb_hlp_snapshot"),
        InlineKeyboardButton(text=_t(lang, "btn_vault_reports"), callback_data="cb_vault_reports_menu")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="sub:vaults"))
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_vault_reports_menu")
async def cb_vault_reports_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "vault_reports", "billing_feature_vault_reports", is_callback=True):
        return

    try:
        await call.answer()
    except Exception:
        pass
    user_id = call.message.chat.id

    catalog = await _collect_user_vault_catalog(user_id)
    await db.set_vault_report_catalog(user_id, catalog)
    cfg = await db.get_vault_report_settings(user_id)
    configs = cfg.get("configs", {})
    digest_cfg = await db.get_digest_settings(user_id)
    hlp_daily_enabled = bool(digest_cfg.get("hlp_daily", {}).get("enabled", True))
    hlp_daily_time = str(digest_cfg.get("hlp_daily", {}).get("time", "09:05"))

    text = f"{_t(lang, 'vault_reports_title')}\n\n{_t(lang, 'vault_reports_msg')}\n\n"
    kb = InlineKeyboardBuilder()
    text += f"{_t(lang, 'vault_reports_hlp_daily')}: <b>{'ON' if hlp_daily_enabled else 'OFF'}</b> • <code>{hlp_daily_time} UTC</code>\n\n"
    kb.row(
        InlineKeyboardButton(
            text=f"☀️ HLP Daily {'✅' if hlp_daily_enabled else '➕'}",
            callback_data="vrep:hlp_daily"
        )
    )

    if not catalog:
        text += f"<i>{_t(lang, 'no_vaults')}</i>"
    else:
        for idx, item in enumerate(catalog):
            wallet = item["wallet"]
            vault = item["vault"]
            eq = float(item.get("equity", 0) or 0)
            key = _vault_cfg_key(wallet, vault)
            flags = configs.get(key, {})
            weekly_on = bool(flags.get("weekly", False))
            monthly_on = bool(flags.get("monthly", False))

            text += (
                f"{idx + 1}. <b>{_vault_display_name(vault)}</b> • <code>{wallet[:6]}...{wallet[-4:]}</code>\n"
                f"   {_t(lang, 'equity')}: ${pretty_float(eq, 2)}\n"
            )
            kb.row(
                InlineKeyboardButton(
                    text=f"W {'✅' if weekly_on else '➕'}",
                    callback_data=f"vrep:w:{idx}"
                ),
                InlineKeyboardButton(
                    text=f"M {'✅' if monthly_on else '➕'}",
                    callback_data=f"vrep:m:{idx}"
                )
            )

    kb.row(InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data="cb_vault_reports_menu"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_digest_settings"), callback_data="cb_digest_settings_menu"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="sub:vaults"))
    text += f"\n<i>{_t(lang, 'vault_reports_hint')}</i>"
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("vrep:"))
async def cb_toggle_vault_report(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "vault_reports", "billing_feature_vault_reports", is_callback=True):
        return

    if call.data == "vrep:hlp_daily":
        digest_cfg = await db.get_digest_settings(call.message.chat.id)
        if not bool(digest_cfg.get("hlp_daily", {}).get("enabled", False)):
            if not await _ensure_billing_feature(call, call.message.chat.id, lang, "digests", "billing_feature_digests", is_callback=True):
                return
            if not await _ensure_billing_digest_slot(call, call.message.chat.id, lang, _count_enabled_digests(digest_cfg), is_callback=True):
                return
        enabled = await db.toggle_digest_enabled(call.message.chat.id, "hlp_daily")
        state_lbl = "ON" if enabled else "OFF"
        await call.answer(_t(lang, "vault_report_daily_toggled").format(state=state_lbl))
        await cb_vault_reports_menu(call)
        return

    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer("Invalid toggle")
        return

    period_short = parts[1]
    try:
        idx = int(parts[2])
    except ValueError:
        await call.answer("Invalid toggle")
        return

    period = "weekly" if period_short == "w" else ("monthly" if period_short == "m" else "")
    if not period:
        await call.answer("Invalid period")
        return

    cfg = await db.get_vault_report_settings(call.message.chat.id)
    catalog = cfg.get("catalog", [])
    if idx < 0 or idx >= len(catalog):
        await call.answer(_t(lang, "vault_catalog_expired"))
        await cb_vault_reports_menu(call)
        return

    item = catalog[idx]
    wallet = str(item.get("wallet", "")).lower()
    vault = str(item.get("vault", "")).lower()
    if not wallet or not vault:
        await call.answer("Invalid vault")
        return

    enabled = await db.toggle_vault_report_setting(call.message.chat.id, wallet, vault, period)
    period_lbl = _t(lang, "vault_reports_weekly") if period == "weekly" else _t(lang, "vault_reports_monthly")
    state_lbl = "ON" if enabled else "OFF"
    await call.answer(_t(lang, "vault_report_toggled").format(period=period_lbl, state=state_lbl))
    await cb_vault_reports_menu(call)
