import asyncio
import logging
import datetime
import time
from aiogram import F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, InputMediaPhoto, LabeledPrice, PreCheckoutQuery, ErrorEvent
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.billing import TEST_BILLING_ADMIN_IDS, PLAN_MONTH_OPTIONS, get_plan_config, get_plan_price, get_plan_price_options, get_plan_star_price, get_plan_star_price_options, get_plan_title, normalize_plan
from bot.config import settings, HLP_VAULT_ADDR, DIGEST_TARGETS
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_user_vault_equities
)
from bot.utils import (
    format_money, pretty_float, _vault_display_name
)
from bot.delta_neutral import (
    collect_delta_neutral_snapshot,
    apply_delta_monitoring,
    format_dashboard_text,
)

logger = logging.getLogger(__name__)

# --- MIDDLEWARE ---

class CallbackThrottleMiddleware(BaseMiddleware):
    def __init__(self, cooldown: float = 3.0):
        self.cooldown = cooldown
        self._last: dict[tuple[int, str], float] = {}
    
    async def __call__(self, handler, event: CallbackQuery, data: dict):
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)
        key = (event.from_user.id, event.data)
        now = time.time()
        if key in self._last and now - self._last[key] < self.cooldown:
            try:
                await event.answer("⏳")
            except Exception:
                pass
            return
        self._last[key] = now
        return await handler(event, data)

# --- ERROR HANDLER ---

async def global_error_handler(event: ErrorEvent):
    logger.error(f"Critical Error in Handler: {event.exception}", exc_info=True)
    try:
        if event.update.message:
            await event.update.message.answer("❌ Internal Bot Error. Please try again later.")
        elif event.update.callback_query:
            await event.update.callback_query.answer("❌ Internal Error.", show_alert=True)
    except Exception as e:
        logger.debug(f"Global error handler response failed: {e}")

# --- UTILS ---

async def smart_edit(call: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None):
    """Edits text message or deletes photo and sends new text message."""
    try:
        if call.message.photo or call.message.document:
            try:
                await call.message.delete()
            except Exception as e:
                logger.debug(f"smart_edit delete failed: {e}")
            return await call.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        
        try:
            return await call.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            if "message is not modified" in str(e):
                return call.message
            return await call.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        return await call.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")

async def smart_edit_media(call: CallbackQuery, photo: BufferedInputFile, caption: str, reply_markup: InlineKeyboardMarkup = None):
    """Edits current media or deletes text and sends photo."""
    try:
        new_media = InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML")
        if call.message.photo or call.message.document:
            return await call.message.edit_media(media=new_media, reply_markup=reply_markup)
        else:
            try:
                await call.message.delete()
            except Exception as e:
                logger.debug(f"smart_edit_media delete failed: {e}")
            return await call.message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        return await call.message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML")

# --- UI Helpers ---

BILLING_USAGE_OVERVIEW = "overview_runs"
BILLING_USAGE_ASSISTANT = "assistant_messages"
BILLING_USAGE_EXPORTS = "exports"
BILLING_USAGE_SHARE_PNL = "share_pnl_cards"


def _count_enabled_digests(cfg: dict) -> int:
    return sum(1 for target in DIGEST_TARGETS if bool((cfg.get(target) or {}).get("enabled", False)))


async def _get_billing_state(user_id: int) -> dict:
    subscription = await db.get_billing_subscription(user_id)
    plan = normalize_plan(subscription.get("plan"))
    usage = await db.get_daily_usage(user_id)
    wallets = await db.list_wallets(user_id)
    watchlist = await db.get_watchlist(user_id)
    alerts = await db.get_user_alerts(user_id)
    user_settings = await db.get_user_settings(user_id)
    digest_settings = await db.get_digest_settings(user_id)
    market_reports = user_settings.get("market_alert_times", []) or []

    return {
        "plan": plan,
        "plan_cfg": get_plan_config(plan),
        "plan_title_en": get_plan_title(plan, "en"),
        "subscription": subscription,
        "usage": usage.get("counts", {}),
        "counts": {
            "wallets": len(wallets),
            "watchlist": len(watchlist),
            "alerts": len(alerts),
            "market_reports": len(market_reports),
            "digest_slots": _count_enabled_digests(digest_settings),
        }
    }


def _limit_value(limit_value) -> str:
    return "∞" if limit_value is None else str(limit_value)


async def _send_billing_gate_message(target, lang: str, text: str, is_callback: bool = False):
    if is_callback:
        await target.answer(text, show_alert=True)
    else:
        await target.answer(text, parse_mode="HTML")


async def _ensure_billing_feature(target, user_id: int, lang: str, feature_key: str, feature_name_key: str, is_callback: bool = False) -> bool:
    state = await _get_billing_state(user_id)
    allowed = bool(state["plan_cfg"]["features"].get(feature_key, False))
    if allowed:
        return True

    text = _t(
        lang,
        "billing_feature_locked",
        feature=_t(lang, feature_name_key),
        plan=get_plan_title("pro", lang)
    )
    await _send_billing_gate_message(target, lang, text, is_callback=is_callback)
    return False


async def _ensure_billing_quota(target, user_id: int, lang: str, quota_key: str, current_value: int, feature_name_key: str, is_callback: bool = False) -> bool:
    state = await _get_billing_state(user_id)
    limit_value = state["plan_cfg"]["limits"].get(quota_key)
    if limit_value is None or current_value < limit_value:
        return True

    text = _t(
        lang,
        "billing_limit_reached",
        feature=_t(lang, feature_name_key),
        current=current_value,
        limit=limit_value,
        plan=get_plan_title("pro", lang)
    )
    await _send_billing_gate_message(target, lang, text, is_callback=is_callback)
    return False


async def _consume_billing_usage(target, user_id: int, lang: str, usage_key: str, limit_key: str, feature_name_key: str, is_callback: bool = False) -> bool:
    state = await _get_billing_state(user_id)
    current_value = int(state["usage"].get(usage_key, 0) or 0)
    limit_value = state["plan_cfg"]["limits"].get(limit_key)
    if limit_value is not None and current_value >= limit_value:
        text = _t(
            lang,
            "billing_daily_limit_reached",
            feature=_t(lang, feature_name_key),
            current=current_value,
            limit=limit_value,
            plan=get_plan_title("pro", lang)
        )
        await _send_billing_gate_message(target, lang, text, is_callback=is_callback)
        return False

    await db.increment_daily_usage(user_id, usage_key, 1)
    return True


async def _ensure_billing_digest_slot(target, user_id: int, lang: str, current_value: int, is_callback: bool = False) -> bool:
    state = await _get_billing_state(user_id)
    limit_value = state["plan_cfg"]["limits"].get("digest_slots")
    if limit_value is None or current_value < limit_value:
        return True

    text = _t(
        lang,
        "billing_digest_limit_reached",
        feature=_t(lang, "billing_feature_digest_slots"),
        current=current_value,
        limit=limit_value,
        plan=get_plan_title("pro_plus", lang)
    )
    await _send_billing_gate_message(target, lang, text, is_callback=is_callback)
    return False


def _build_stars_invoice_payload(user_id: int, plan: str, months: int) -> str:
    return f"billing:stars:{int(user_id)}:{normalize_plan(plan)}:{int(months)}"


def _parse_stars_invoice_payload(payload: str) -> tuple[int, str, int] | None:
    try:
        prefix, kind, user_id, plan, months = str(payload).split(":")
        if prefix != "billing" or kind != "stars":
            return None
        return int(user_id), normalize_plan(plan), int(months)
    except Exception:
        return None

def _main_menu_text(lang, wallets):
    text = _t(lang, "welcome")
    if wallets:
        text += "\n\n" + _t(lang, "tracking").format(wallet=f"{wallets[0][:6]}...{wallets[0][-4:]}")
    else:
        text += "\n\n" + _t(lang, "set_wallet")
    return text

def _main_menu_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "cat_dashboard"), callback_data="sub:dashboard"),
        InlineKeyboardButton(text=_t(lang, "cat_alerts"), callback_data="sub:alerts")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "cat_market"), callback_data="sub:market"),
        InlineKeyboardButton(text=_t(lang, "cat_settings"), callback_data="cb_settings")
    )
    return kb.as_markup()

def _dashboard_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_balance"), callback_data="cb_balance:portfolio"),
        InlineKeyboardButton(text=_t(lang, "btn_pnl"), callback_data="cb_pnl:portfolio")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_positions"), callback_data="cb_positions:portfolio:0"),
        InlineKeyboardButton(text=_t(lang, "btn_orders"), callback_data="cb_orders:portfolio:0")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_terminal"), callback_data="cb_terminal:dashboard"),
        InlineKeyboardButton(text=_t(lang, "btn_delta_neutral"), callback_data="cb_delta_neutral:dashboard")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _alerts_kb(lang):
    this_path = "sub:alerts"
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_price_alerts"), callback_data=f"cb_alerts:{this_path}"),
        InlineKeyboardButton(text=_t(lang, "btn_market"), callback_data="sub:market:alerts") # For watchlist?
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_funding_alert"), callback_data="cb_funding_alert_prompt"),
        InlineKeyboardButton(text=_t(lang, "btn_oi_alert"), callback_data="cb_oi_alert_prompt")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_whales"), callback_data=f"cb_whales:alerts:{this_path}"),
        InlineKeyboardButton(text=_t(lang, "btn_hedge_chat"), callback_data=f"cb_hedge_chat_start:{this_path}")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _overview_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_terminal"), callback_data="cb_terminal:overview"),
        InlineKeyboardButton(text=_t(lang, "btn_delta_neutral"), callback_data="cb_delta_neutral:overview")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_hedge_ai"), callback_data="cb_ai_overview_menu:overview"),
        InlineKeyboardButton(text=_t(lang, "btn_hedge_chat"), callback_data="cb_hedge_chat_start:overview")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _portfolio_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_balance"), callback_data="cb_balance:portfolio"),
        InlineKeyboardButton(text=_t(lang, "btn_pnl"), callback_data="cb_pnl:portfolio")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_positions"), callback_data="cb_positions:portfolio:0"),
        InlineKeyboardButton(text=_t(lang, "btn_orders"), callback_data="cb_orders:portfolio:0")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _trading_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_balance"), callback_data="cb_balance:trading"))
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_positions"), callback_data="cb_positions:trading:0"),
        InlineKeyboardButton(text=_t(lang, "btn_orders"), callback_data="cb_orders:trading:0")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_history"), callback_data="cb_fills"),
        InlineKeyboardButton(text=_t(lang, "btn_stats"), callback_data="cb_stats:trading")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "calc_btn"), callback_data="calc_start"),
        InlineKeyboardButton(text=_t(lang, "btn_risk_check"), callback_data="cb_risk_check")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _market_kb(lang, back_target="cb_menu"):
    # Reconstruct path to this menu
    this_path = "sub:market"
    if back_target.startswith("sub:"):
        ctx = back_target.split(":")[1]
        this_path = f"sub:market:{ctx}"
        
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_market"), callback_data=f"cb_market:market:{this_path}"),
        InlineKeyboardButton(text=_t(lang, "btn_market_overview"), callback_data=f"cb_ai_overview_menu:{this_path}")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_whales"), callback_data=f"cb_whales:market:{this_path}"),
        InlineKeyboardButton(text=_t(lang, "btn_fear_greed"), callback_data=f"cb_fear_greed:market:{this_path}")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_price_alerts"), callback_data=f"cb_alerts:{this_path}"),
        InlineKeyboardButton(text=_t(lang, "btn_hlp_snapshot"), callback_data=f"cb_hlp_snapshot:market:{this_path}")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_vaults_overview"), callback_data=f"sub:vaults:market"),
        InlineKeyboardButton(text=_t(lang, "btn_market_alerts"), callback_data=f"cb_market_alerts:market:{this_path}")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data=back_target))
    return kb.as_markup()

def _vaults_kb(lang, back_target="cb_menu"):
    # Reconstruct path to this menu
    this_path = "sub:vaults"
    if back_target.startswith("sub:"):
        ctx = back_target.split(":")[1]
        this_path = f"sub:vaults:{ctx}"
        
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_vaults_overview"), callback_data=f"cb_vaults_overview:{this_path}"),
        InlineKeyboardButton(text=_t(lang, "btn_hlp_snapshot"), callback_data=f"cb_hlp_snapshot:vaults:{this_path}")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_vault_reports"), callback_data=f"cb_vault_reports_menu:{this_path}"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data=back_target))
    return kb.as_markup()

def _is_hlp_vault(vault_address: str) -> bool:
    return HLP_VAULT_ADDR[2:] in str(vault_address or "").lower()

def _vault_cfg_key(wallet: str, vault: str) -> str:
    return f"{wallet.lower()}|{vault.lower()}"

def _fmt_period_change(current: float, base: float) -> str:
    diff = current - base
    pct = (diff / base) * 100 if base > 0 else 0.0
    icon = "🟢" if diff >= 0 else "🔴"
    return f"{icon} {pretty_float(diff, 2)} ({pct:+.2f}%)"

async def _collect_user_vault_catalog(user_id: int) -> list[dict]:
    wallets = await db.list_wallets(user_id)
    if not wallets:
        return []

    entries = []
    seen = set()
    vault_lists = await asyncio.gather(*(get_user_vault_equities(w) for w in wallets), return_exceptions=True)

    for wallet, vault_equities in zip(wallets, vault_lists):
        if isinstance(vault_equities, Exception) or not isinstance(vault_equities, list):
            continue
        for v in vault_equities:
            vault = str(v.get("vaultAddress", "")).lower()
            if not vault:
                continue
            key = (wallet.lower(), vault)
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "wallet": wallet.lower(),
                "vault": vault,
                "equity": float(v.get("equity", 0) or 0)
            })

    entries.sort(key=lambda x: x.get("equity", 0), reverse=True)
    return entries

def _valid_hhmm(time_str: str) -> str | None:
    try:
        parts = str(time_str).strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
        return None
    except Exception:
        return None

def _digest_label_key(target: str) -> str:
    return {
        "portfolio_daily": "digest_portfolio_daily",
        "portfolio_weekly": "digest_portfolio_weekly",
        "hlp_daily": "digest_hlp_daily",
        "vault_weekly": "digest_vault_weekly",
        "vault_monthly": "digest_vault_monthly",
    }.get(target, target)

def _back_kb(lang, target="cb_menu"):
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data=target)
    return kb.as_markup()

async def _build_delta_neutral_dashboard(user_id: int, bot, interval_hours: float = 0.0, emit_alerts: bool = False):
    wallets = await db.list_wallets(user_id)
    if not wallets:
        return None, None

    ws = getattr(bot, "ws_manager", None) if bot else None
    user_cfg = await db.get_user_settings(user_id)
    prev_state = user_cfg.get("delta_state", {}) if isinstance(user_cfg, dict) else {}

    snapshot = await collect_delta_neutral_snapshot(wallets, ws=ws)
    _, new_state = apply_delta_monitoring(
        snapshot,
        previous_state=prev_state,
        interval_hours=interval_hours,
        emit_alerts=emit_alerts,
    )
    await db.update_user_settings(user_id, {"delta_state": new_state})

    lang = await db.get_lang(user_id)
    text = format_dashboard_text(snapshot, lang=lang)
    return text, snapshot

def _settings_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_wallets_alerts"), callback_data="cb_wallets_alerts_menu"),
        InlineKeyboardButton(text=_t(lang, "btn_ai_config"), callback_data="cb_ai_config_menu")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_digests_reports"), callback_data="cb_digests_reports_menu"),
        InlineKeyboardButton(text=_t(lang, "btn_export"), callback_data="cb_export")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_billing"), callback_data="cb_billing"),
        InlineKeyboardButton(text=_t(lang, "btn_lang"), callback_data="cb_lang_menu")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _wallets_alerts_settings_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_wallets"), callback_data="cb_wallets_menu"))
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_prox"), callback_data="set_prox_prompt"),
        InlineKeyboardButton(text=_t(lang, "btn_vol"), callback_data="set_vol_prompt"),
        InlineKeyboardButton(text=_t(lang, "btn_whale"), callback_data="set_whale_prompt")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_funding_alert"), callback_data="cb_funding_alert_prompt"),
        InlineKeyboardButton(text=_t(lang, "btn_oi_alert"), callback_data="cb_oi_alert_prompt")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))
    return kb.as_markup()

def _ai_config_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_velox_ai_settings"), callback_data="cb_overview_settings_menu"),
        InlineKeyboardButton(text=_t(lang, "btn_velox_hedge_settings"), callback_data="cb_hedge_settings_menu")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))
    return kb.as_markup()

def _digests_reports_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_digest_settings"), callback_data="cb_digest_settings_menu"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_market_alerts"), callback_data="cb_market_alerts"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))
    return kb.as_markup()

def _pagination_kb(lang: str, current_page: int, total_pages: int, callback_prefix: str, back_target: str = "cb_menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    row = []
    if current_page > 0:
        row.append(InlineKeyboardButton(text="<<", callback_data=f"{callback_prefix}:{current_page-1}"))
    row.append(InlineKeyboardButton(text=f"{current_page+1}/{total_pages}", callback_data="noop"))
    if current_page < total_pages - 1:
        row.append(InlineKeyboardButton(text=">>", callback_data=f"{callback_prefix}:{current_page+1}"))
    kb.row(*row)
    if "cb_positions" in callback_prefix:
        context = callback_prefix.split(":", 1)[1] if ":" in callback_prefix else "trading"
        kb.row(
            InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data=f"{callback_prefix}:{current_page}"),
            InlineKeyboardButton(text=_t(lang, "btn_share"), callback_data=f"cb_share_pnl_menu:{context}:{current_page}")
        )
    elif "cb_orders" in callback_prefix:
        kb.row(InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data=f"{callback_prefix}:{current_page}"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data=back_target))
    return kb.as_markup()

async def _build_billing_ui(user_id: int, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    state = await _get_billing_state(user_id)
    plan = state["plan"]
    plan_cfg = state["plan_cfg"]
    usage = state["usage"]
    counts = state["counts"]
    sub = state["subscription"]

    active_until = sub.get("active_until")
    if active_until:
        active_until_text = datetime.datetime.utcfromtimestamp(active_until).strftime("%Y-%m-%d")
    elif sub.get("source") == "manual_test":
        active_until_text = _t(lang, "billing_test_mode")
    else:
        active_until_text = _t(lang, "billing_no_expiry")

    free_cfg = get_plan_config("free")
    pro_cfg = get_plan_config("pro")
    pro_plus_cfg = get_plan_config("pro_plus")

    text = (
        f"{_t(lang, 'billing_title')}\n\n"
        f"{_t(lang, 'billing_current_plan')}: <b>{get_plan_title(plan, lang)}</b>\n"
        f"{_t(lang, 'billing_active_until')}: <b>{active_until_text}</b>\n\n"
        f"{_t(lang, 'billing_usage_title')}\n"
        f"• {_t(lang, 'billing_feature_wallets')}: <b>{counts['wallets']}/{_limit_value(plan_cfg['limits']['wallets'])}</b>\n"
        f"• {_t(lang, 'billing_feature_watchlist')}: <b>{counts['watchlist']}/{_limit_value(plan_cfg['limits']['watchlist'])}</b>\n"
        f"• {_t(lang, 'billing_feature_alerts')}: <b>{counts['alerts']}/{_limit_value(plan_cfg['limits']['alerts'])}</b>\n"
        f"• {_t(lang, 'billing_feature_market_reports')}: <b>{counts['market_reports']}/{_limit_value(plan_cfg['limits']['market_reports'])}</b>\n"
        f"• {_t(lang, 'billing_feature_overview_runs')}: <b>{usage.get(BILLING_USAGE_OVERVIEW, 0)}/{_limit_value(plan_cfg['limits']['overview_runs_daily'])}</b>\n"
        f"• {_t(lang, 'billing_feature_assistant_messages')}: <b>{usage.get(BILLING_USAGE_ASSISTANT, 0)}/{_limit_value(plan_cfg['limits']['assistant_messages_daily'])}</b>\n"
        f"• {_t(lang, 'billing_feature_exports_daily')}: <b>{usage.get(BILLING_USAGE_EXPORTS, 0)}/{_limit_value(plan_cfg['limits']['exports_daily'])}</b>\n"
        f"• {_t(lang, 'billing_feature_share_pnl_daily')}: <b>{usage.get(BILLING_USAGE_SHARE_PNL, 0)}/{_limit_value(plan_cfg['limits']['share_pnl_daily'])}</b>\n"
        f"• {_t(lang, 'billing_feature_digest_slots')}: <b>{counts['digest_slots']}/{_limit_value(plan_cfg['limits']['digest_slots'])}</b>\n\n"
        f"{_t(lang, 'billing_features_title')}\n"
        f"• {_t(lang, 'billing_feature_terminal')}: <b>{_t(lang, 'billing_yes') if plan_cfg['features']['terminal'] else _t(lang, 'billing_no')}</b>\n"
        f"• {_t(lang, 'billing_feature_export')}: <b>{_t(lang, 'billing_yes') if plan_cfg['features']['export'] else _t(lang, 'billing_no')}</b>\n"
        f"• {_t(lang, 'billing_feature_digests')}: <b>{_t(lang, 'billing_yes') if plan_cfg['features']['digests'] else _t(lang, 'billing_no')}</b>\n"
        f"• {_t(lang, 'billing_feature_vault_reports')}: <b>{_t(lang, 'billing_yes') if plan_cfg['features']['vault_reports'] else _t(lang, 'billing_no')}</b>\n"
        f"• {_t(lang, 'billing_feature_flex')}: <b>{_t(lang, 'billing_yes') if plan_cfg['features']['flex'] else _t(lang, 'billing_no')}</b>\n"
        f"• {_t(lang, 'billing_feature_share_pnl')}: <b>{_t(lang, 'billing_yes') if plan_cfg['features']['share_pnl'] else _t(lang, 'billing_no')}</b>\n"
        f"• {_t(lang, 'billing_feature_ai_settings')}: <b>{_t(lang, 'billing_yes') if plan_cfg['features']['advanced_ai_settings'] else _t(lang, 'billing_no')}</b>\n\n"
        f"{_t(lang, 'billing_prices_title')}\n"
        f"• <b>{get_plan_title('free', lang)}</b> — $0 · "
        f"{free_cfg['limits']['wallets']} {_t(lang, 'billing_feature_wallets').lower()}, "
        f"{free_cfg['limits']['alerts']} {_t(lang, 'billing_feature_alerts').lower()}, "
        f"{free_cfg['limits']['overview_runs_daily']} {_t(lang, 'billing_feature_overview_runs').lower()}, "
        f"{free_cfg['limits']['assistant_messages_daily']} {_t(lang, 'billing_feature_assistant_messages').lower()}\n"
        f"• <b>{get_plan_title('pro', lang)}</b> — {get_plan_price_options('pro')} · {get_plan_star_price_options('pro')} · "
        f"{pro_cfg['limits']['wallets']} {_t(lang, 'billing_feature_wallets').lower()}, "
        f"{pro_cfg['limits']['watchlist']} {_t(lang, 'billing_feature_watchlist').lower()}, "
        f"{pro_cfg['limits']['alerts']} {_t(lang, 'billing_feature_alerts').lower()}, "
        f"{pro_cfg['limits']['overview_runs_daily']} {_t(lang, 'billing_feature_overview_runs').lower()}\n"
        f"• <b>{get_plan_title('pro_plus', lang)}</b> — {get_plan_price_options('pro_plus')} · {get_plan_star_price_options('pro_plus')} · "
        f"{pro_plus_cfg['limits']['wallets']} {_t(lang, 'billing_feature_wallets').lower()}, "
        f"{pro_plus_cfg['limits']['watchlist']} {_t(lang, 'billing_feature_watchlist').lower()}, "
        f"{pro_plus_cfg['limits']['alerts']} {_t(lang, 'billing_feature_alerts').lower()}, "
        f"{pro_plus_cfg['limits']['overview_runs_daily']} {_t(lang, 'billing_feature_overview_runs').lower()}, "
        f"{pro_plus_cfg['limits']['assistant_messages_daily']} {_t(lang, 'billing_feature_assistant_messages').lower()}\n\n"
        f"{_t(lang, 'billing_stars_fee_note')}\n"
        f"<i>{_t(lang, 'billing_payment_note')}</i>"
    )

    kb = InlineKeyboardBuilder()
    for months in PLAN_MONTH_OPTIONS:
        kb.button(text=f"⭐ Pro {months}M · {get_plan_star_price('pro', months)}", callback_data=f"bill_buy:pro:{months}")
    for months in PLAN_MONTH_OPTIONS:
        kb.button(text=f"💎 Pro+ {months}M · {get_plan_star_price('pro_plus', months)}", callback_data=f"bill_buy:pro_plus:{months}")

    if user_id in TEST_BILLING_ADMIN_IDS:
        kb.button(text="🧪 Free", callback_data="bill_test:set:free")
        kb.button(text="🧪 Pro", callback_data="bill_test:set:pro")
        kb.button(text="🧪 Pro+", callback_data="bill_test:set:pro_plus")
        kb.button(text="🧪 Reset usage", callback_data="bill_test:reset_usage")

    kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
    if user_id in TEST_BILLING_ADMIN_IDS:
        kb.adjust(2, 2, 2, 2, 2, 2, 1)
    else:
        kb.adjust(2, 2, 2, 2, 1)
    return text, kb.as_markup()

async def _build_digest_settings_ui(user_id: int, lang: str, back_target: str = "cb_settings") -> tuple[str, InlineKeyboardMarkup]:
    cfg = await db.get_digest_settings(user_id)
    state = await _get_billing_state(user_id)
    digest_limit = _limit_value(state["plan_cfg"]["limits"].get("digest_slots"))
    digest_used = _count_enabled_digests(cfg)
    text = (
        f"{_t(lang, 'digest_settings_title')}\n\n"
        f"{_t(lang, 'digest_settings_msg')}\n\n"
        f"{_t(lang, 'billing_feature_digest_slots')}: <b>{digest_used}/{digest_limit}</b>\n\n"
    )
    kb = InlineKeyboardBuilder()

    for target in DIGEST_TARGETS:
        dc = cfg.get(target, {})
        enabled = bool(dc.get("enabled", True))
        time_str = dc.get("time", "09:00")
        name = _t(lang, _digest_label_key(target))
        text += f"• <b>{name}</b>: {'ON' if enabled else 'OFF'} | <code>{time_str} UTC</code>\n"

        kb.row(
            InlineKeyboardButton(
                text=f"{'✅' if enabled else '➕'} {name}",
                callback_data=f"dg_toggle:{target}:{back_target}"
            ),
            InlineKeyboardButton(
                text=f"🕒 {time_str}",
                callback_data=f"dg_set_time:{target}:{back_target}"
            )
        )

    text += f"\n<i>{_t(lang, 'digest_schedule_note')}</i>"
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data=back_target))
    return text, kb.as_markup()
