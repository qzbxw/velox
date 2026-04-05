import logging
import asyncio
import time
import datetime
import html
import re
import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database import db
from bot.locales import _t
from bot.services import (
    get_perps_context, get_fear_greed_index, pretty_float
)
from bot import market_overview
from bot.renderer import render_html_to_image
from bot.handlers._common import (
    smart_edit, _back_kb, _ensure_billing_feature, _consume_billing_usage,
    BILLING_USAGE_OVERVIEW, BILLING_USAGE_ASSISTANT
)
from bot.handlers.states import SettingsStates, AIStates

router = Router(name="ai")
logger = logging.getLogger(__name__)

class HedgeChatStates:
    chatting = "chatting" # Simple string for FSM logic check if needed, though we use AIStates

# --- HELPERS ---

def _build_overview_settings_ui(lang: str, cfg: dict, include_back: bool = True) -> tuple[str, InlineKeyboardMarkup]:
    prompt_status = "✅ Custom" if cfg.get("prompt_override") else "❌ Default"
    text = (
        f"⚙️ <b>{_t(lang, 'market_title')} - {_t(lang, 'settings_title')}</b>\n\n"
        f"<b>Status:</b> {'✅ Enabled' if cfg['enabled'] else '🔴 Disabled'}\n"
        f"<b>Prompt:</b> {prompt_status}\n\n"
        f"<b>Schedule (UTC):</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_t(lang, "ov_btn_toggle"), callback_data="ov_toggle"))

    schedules = cfg.get("schedules", [])
    if not schedules:
        text += "\n<i>No scheduled times.</i>"
    else:
        for t in sorted(schedules):
            kb.row(InlineKeyboardButton(text=f"❌ {t}", callback_data=f"ov_del_time:{t}"))
            text += f"\n• {t}"

    kb.row(
        InlineKeyboardButton(text="➕ Add Time", callback_data="ov_add_time"),
        InlineKeyboardButton(text="📝 Set Prompt", callback_data="ov_prompt")
    )

    if include_back:
        kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))

    return text, kb.as_markup()

async def _fetch_market_snapshot():
    return await get_perps_context()

async def _send_ai_overview(bot, chat_id, user_id, status_msg=None):
    lang = await db.get_lang(chat_id)
    if not status_msg:
        status_msg = await bot.send_message(chat_id, _t(lang, "ai_generating"), parse_mode="HTML")
    
    try:
        # Fetch data in parallel
        ctx, news, fng = await asyncio.gather(
            get_perps_context(),
            market_overview.fetch_news_rss(since_timestamp=time.time() - 86400),
            get_fear_greed_index(),
            return_exceptions=True
        )

        if isinstance(ctx, Exception) or not ctx:
            raise ValueError("Failed to fetch market context")
        
        universe = ctx[0]["universe"] if isinstance(ctx[0], dict) and "universe" in ctx[0] else ctx[0]
        asset_ctxs = ctx[1]

        # Process Market Data for Prompt
        market_data = {}
        total_volume = sum(float(ac.get("dayNtlVlm", 0)) for ac in asset_ctxs)
        total_oi = sum(float(ac.get("openInterest", 0)) * float(ac.get("markPx", 0)) for ac in asset_ctxs)

        market_data["global_volume"] = pretty_float(total_volume, 0)
        market_data["total_oi"] = pretty_float(total_oi, 0)

        for sym in ["BTC", "ETH"]:
            idx = next((i for i, u in enumerate(universe) if (u["name"] if isinstance(u, dict) else u) == sym), -1)
            if idx != -1 and idx < len(asset_ctxs):
                ac = asset_ctxs[idx]
                p = float(ac.get("markPx", 0))
                prev = float(ac.get("prevDayPx", 0) or p)
                change = ((p - prev)/prev)*100 if prev else 0
                market_data[sym] = {"price": pretty_float(p), "change": round(change, 2)}
            else:
                market_data[sym] = {"price": "0", "change": 0.0}

        market_data["etf_flows"] = {"btc_flow": 0, "eth_flow": 0}

        movers = []
        for i in range(min(len(universe), len(asset_ctxs))):
            ac = asset_ctxs[i]
            p = float(ac.get("markPx", 0))
            prev = float(ac.get("prevDayPx", 0) or p)
            change = ((p - prev)/prev)*100 if prev else 0
            u_name = universe[i]["name"] if isinstance(universe[i], dict) else universe[i]
            movers.append({"name": u_name, "change": round(change, 2)})

        movers.sort(key=lambda x: x["change"], reverse=True)
        market_data["top_gainers"] = movers[:5]
        market_data["top_losers"] = movers[-5:][::-1]

        def get_change(idx):
            if idx >= len(asset_ctxs): return 0
            ac = asset_ctxs[idx]
            p = float(ac.get("markPx", 0))
            prev = float(ac.get("prevDayPx", 0) or p)
            return ((p - prev)/prev)*100 if prev else 0

        mover_indices = [(i, get_change(i)) for i in range(len(universe))]
        mover_indices.sort(key=lambda x: x[1], reverse=True)
        
        top_gainer = (universe[mover_indices[0][0]]["name"] if isinstance(universe[mover_indices[0][0]], dict) else universe[mover_indices[0][0]])
        top_gainer_pct = mover_indices[0][1]
        top_loser = (universe[mover_indices[-1][0]]["name"] if isinstance(universe[mover_indices[-1][0]], dict) else universe[mover_indices[-1][0]])
        top_loser_pct = mover_indices[-1][1]
        
        vol_indices = [(i, float(asset_ctxs[i].get("dayNtlVlm", 0))) for i in range(len(universe)) if i < len(asset_ctxs)]
        vol_indices.sort(key=lambda x: x[1], reverse=True)
        top_vol = (universe[vol_indices[0][0]]["name"] if isinstance(universe[vol_indices[0][0]], dict) else universe[vol_indices[0][0]])
        top_vol_val = vol_indices[0][1]
        
        fund_indices = [(i, float(asset_ctxs[i].get("funding", 0))) for i in range(len(universe)) if i < len(asset_ctxs)]
        fund_indices.sort(key=lambda x: x[1], reverse=True)
        top_fund = (universe[fund_indices[0][0]]["name"] if isinstance(universe[fund_indices[0][0]], dict) else universe[fund_indices[0][0]])
        top_fund_val = fund_indices[0][1] * 100 * 24 * 365 # APR

        user_config = await db.get_overview_settings(user_id)
        
        ai_data = await market_overview.generate_summary(
            market_data, news, "INTELLIGENCE",
            custom_prompt=user_config.get("prompt_override"),
            style=user_config.get("style", "detailed"),
            lang=lang
        )
        
        if not isinstance(ai_data, dict):
             ai_data = {"summary": str(ai_data), "sentiment": "Neutral"}

        summary_text = ai_data.get("summary", "No summary available.")
        sentiment = ai_data.get("sentiment", "Neutral")

        render_data = {
            "period_label": "INTELLIGENCE",
            "date": datetime.datetime.now().strftime("%d %b %H:%M"),
            "btc": market_data["BTC"],
            "eth": market_data["ETH"],
            "sentiment": sentiment,
            "fng": fng if fng and not isinstance(fng, Exception) else {"value": 0, "classification": "N/A"},
            "gemini_model": "3 Flash Preview",
            "top_gainer": {"sym": top_gainer, "val": top_gainer_pct},
            "top_loser": {"sym": top_loser, "val": top_loser_pct},
            "top_vol": {"sym": top_vol, "val": f"${top_vol_val/1e6:.0f}M"},
            "top_fund": {"sym": top_fund, "val": f"{top_fund_val:.0f}%"}
        }
        
        img_buf = await render_html_to_image("market_overview.html", render_data, width=1000, height=1000, lang=lang)
        
        btc_d, eth_d = market_data.get("BTC", {}), market_data.get("ETH", {})
        btc_c, eth_c = btc_d.get("change", 0.0), eth_d.get("change", 0.0)
        btc_icon, eth_icon = ("🟢" if btc_c >= 0 else "🔴"), ("🟢" if eth_c >= 0 else "🔴")
        
        header = f"<b>BTC: ${btc_d.get('price', '0')} ({btc_icon} {btc_c:+.2f}%)</b>\n<b>ETH: ${eth_d.get('price', '0')} ({eth_icon} {eth_c:+.2f}%)</b>"
        
        img_msg = await bot.send_photo(chat_id=chat_id, photo=BufferedInputFile(img_buf.read(), filename="overview.png"), caption=f"{header}\n\n🧠 <b>Velox Insight</b>", parse_mode="HTML")
        
        report_text = html.escape(summary_text)
        report_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', report_text)
        report_text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', report_text)
        
        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "btn_refresh"), callback_data="cb_market_overview_refresh")
        kb.button(text=_t(lang, "btn_settings"), callback_data="cb_overview_settings_menu")
        kb.button(text=_t(lang, "btn_back"), callback_data="cb_ai_cleanup")
        kb.adjust(1, 2)

        txt_msg = await bot.send_message(chat_id=chat_id, text=report_text, parse_mode="HTML", reply_markup=kb.as_markup())
        
        # Access storage to save IDs
        ctx_key = bot.fsm.resolve_context_key(chat_id, user_id)
        state_obj = FSMContext(storage=bot.fsm.storage, key=ctx_key)
        await state_obj.update_data(ai_overview_msg_ids=[img_msg.message_id, txt_msg.message_id])
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Overview error: {e}", exc_info=True)
        if status_msg: await status_msg.edit_text("❌ Failed to generate overview.")

# --- HANDLERS ---

@router.callback_query(F.data == "cb_ai_overview_menu")
async def cb_ai_overview_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _consume_billing_usage(call, call.message.chat.id, lang, BILLING_USAGE_OVERVIEW, "overview_runs_daily", "billing_feature_overview_runs", is_callback=True):
        return
    await call.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:overview")
    status_msg = await call.message.answer(_t(lang, "ai_generating"), reply_markup=kb.as_markup(), parse_mode="HTML")
    await _send_ai_overview(call.message.bot, call.message.chat.id, call.from_user.id, status_msg=status_msg)

@router.callback_query(F.data == "cb_market_overview_refresh")
async def cb_market_overview_refresh(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    if not await _consume_billing_usage(call, call.message.chat.id, lang, BILLING_USAGE_OVERVIEW, "overview_runs_daily", "billing_feature_overview_runs", is_callback=True):
        return
    await call.answer()
    data = await state.get_data()
    mids = data.get("ai_overview_msg_ids", [])
    for mid in mids:
        try: await call.message.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)
        except Exception: pass
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:overview")
    status_msg = await call.message.answer(_t(lang, "ai_generating"), reply_markup=kb.as_markup(), parse_mode="HTML")
    await _send_ai_overview(call.message.bot, call.message.chat.id, call.from_user.id, status_msg=status_msg)

@router.callback_query(F.data == "cb_ai_cleanup")
async def cb_ai_cleanup(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mids = data.get("ai_overview_msg_ids", [])
    for mid in mids:
        if mid == call.message.message_id: continue
        try: await call.message.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)
        except Exception: pass
    await state.update_data(ai_overview_msg_ids=None)
    from bot.handlers.menu import cb_sub_overview
    await cb_sub_overview(call)

@router.message(Command("overview"))
async def cmd_overview(message: Message):
    lang = await db.get_lang(message.chat.id)
    if not await _consume_billing_usage(message, message.chat.id, lang, BILLING_USAGE_OVERVIEW, "overview_runs_daily", "billing_feature_overview_runs"):
        return
    await _send_ai_overview(message.bot, message.chat.id, message.from_user.id)

@router.message(Command("overview_settings"))
async def cmd_overview_settings(message: Message):
    lang = await db.get_lang(message.chat.id)
    if not await _ensure_billing_feature(message, message.chat.id, lang, "advanced_ai_settings", "billing_feature_ai_settings"):
        return
    cfg = await db.get_overview_settings(message.from_user.id)
    text, kb = _build_overview_settings_ui(lang, cfg, include_back=False)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "cb_overview_settings_menu")
async def cb_overview_settings_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "advanced_ai_settings", "billing_feature_ai_settings", is_callback=True):
        return
    await call.answer()
    cfg = await db.get_overview_settings(call.from_user.id)
    text, kb = _build_overview_settings_ui(lang, cfg)
    await smart_edit(call, text, reply_markup=kb)

@router.callback_query(F.data.startswith("ov_"))
async def cb_overview_settings(call: CallbackQuery, state: FSMContext):
    action, user_id, lang = call.data, call.from_user.id, await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "advanced_ai_settings", "billing_feature_ai_settings", is_callback=True):
        return
    if action == "ov_add_time":
        await state.update_data(menu_msg_id=call.message.message_id)
        await call.message.edit_text(_t(lang, "add_time_prompt"), reply_markup=_back_kb(lang, "cb_overview_settings_menu"), parse_mode="HTML")
        await state.set_state(SettingsStates.waiting_for_ov_time)
        await call.answer()
        return
    if action == "ov_prompt":
        await state.update_data(menu_msg_id=call.message.message_id)
        await call.message.edit_text("⌨️ Enter your <b>Custom Prompt</b> instructions:\n<i>(e.g. 'Focus on DeFi tokens', 'Be sarcastic')</i>\nType 'clear' to reset.", reply_markup=_back_kb(lang, "cb_overview_settings_menu"), parse_mode="HTML")
        await state.set_state(SettingsStates.waiting_for_ov_prompt)
        await call.answer()
        return
    cfg = await db.get_overview_settings(user_id)
    if action == "ov_toggle": cfg["enabled"] = not cfg["enabled"]
    elif action.startswith("ov_del_time:"):
        t = action.split(":", 1)[1]
        if t in cfg["schedules"]: cfg["schedules"].remove(t)
    await db.update_overview_settings(user_id, cfg)
    text, kb = _build_overview_settings_ui(lang, cfg)
    try: await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception: pass
    await call.answer()

@router.message(SettingsStates.waiting_for_ov_time)
async def process_ov_time(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    t_str = message.text.strip()
    if not re.match(r"^\d{2}:\d{2}$", t_str):
        await message.answer(_t(lang, "ov_invalid_time"))
        return
    cfg = await db.get_overview_settings(message.from_user.id)
    if t_str not in cfg["schedules"]:
        cfg["schedules"].append(t_str)
        await db.update_overview_settings(message.from_user.id, cfg)
    await state.clear()
    await message.answer(_t(lang, "ov_time_added", time=t_str))
    await cmd_overview_settings(message)

@router.message(SettingsStates.waiting_for_ov_prompt)
async def process_ov_prompt(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    text = message.text.strip()
    cfg = await db.get_overview_settings(message.from_user.id)
    cfg["prompt_override"] = None if text.lower() == "clear" else text
    await db.update_overview_settings(message.from_user.id, cfg)
    await state.clear()
    await message.answer(_t(lang, "ov_prompt_set"))
    await cmd_overview_settings(message)

# --- HEDGE SETTINGS ---

async def _hedge_settings_render(call: CallbackQuery, user_id: int):
    lang = await db.get_lang(call.message.chat.id)
    cfg = await db.get_hedge_settings(user_id)
    enabled = cfg.get("enabled", False)
    triggers = cfg.get("triggers", {})
    def _btn_text(key, label):
        if not enabled: return f"⚪️ {label}"
        return f"{'✅' if triggers.get(key, False) else '❌'} {label}"
    kb = InlineKeyboardBuilder()
    state_text = ("ON" if enabled else "OFF") if lang != "ru" else ("ВКЛ" if enabled else "ВЫКЛ")
    kb.row(InlineKeyboardButton(text=_t(lang, "hedge_btn_toggle", state=state_text), callback_data="hedge_toggle_master"))
    trigger_list = [("liquidation", _t(lang, "hedge_trigger_liqs")), ("fills", _t(lang, "hedge_trigger_fills")), ("proximity", _t(lang, "hedge_trigger_prox")), ("volatility", _t(lang, "hedge_trigger_vol")), ("whale", _t(lang, "hedge_trigger_whale")), ("margin", _t(lang, "hedge_trigger_margin")), ("listings", _t(lang, "hedge_trigger_listings")), ("ledger", _t(lang, "hedge_trigger_ledger")), ("funding", _t(lang, "hedge_trigger_funding")), ("oi", _t(lang, "hedge_trigger_oi"))]
    for i in range(0, len(trigger_list), 2):
        row = [InlineKeyboardButton(text=_btn_text(trigger_list[i][0], trigger_list[i][1]), callback_data=f"hedge_toggle:{trigger_list[i][0]}")]
        if i + 1 < len(trigger_list): row.append(InlineKeyboardButton(text=_btn_text(trigger_list[i+1][0], trigger_list[i+1][1]), callback_data=f"hedge_toggle:{trigger_list[i+1][0]}"))
        kb.row(*row)
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))
    await smart_edit(call, f"{_t(lang, 'hedge_title')}\n\n{_t(lang, 'hedge_desc')}", reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_hedge_settings_menu")
async def cb_hedge_settings_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "advanced_ai_settings", "billing_feature_ai_settings", is_callback=True):
        return
    await _hedge_settings_render(call, call.message.chat.id)
    await call.answer()

@router.callback_query(F.data.startswith("hedge_toggle"))
async def cb_hedge_toggle(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "advanced_ai_settings", "billing_feature_ai_settings", is_callback=True):
        return
    user_id, cfg = call.message.chat.id, await db.get_hedge_settings(call.message.chat.id)
    if call.data == "hedge_toggle_master": cfg["enabled"] = not cfg.get("enabled", False)
    elif call.data.startswith("hedge_toggle:"):
        key = call.data.split(":")[1]
        if "triggers" not in cfg: cfg["triggers"] = {}
        cfg["triggers"][key] = not cfg["triggers"].get(key, False)
    await db.update_hedge_settings(user_id, cfg)
    await _hedge_settings_render(call, user_id)
    await call.answer()

# --- HEDGE CHAT ---

@router.callback_query(F.data == "cb_hedge_chat_start")
async def cb_hedge_chat_start(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:overview")
    text = "🛡️ <b>Velox Assistant</b>\n\nI’m your market and risk assistant. I have context on your portfolio, watchlist, and current market conditions.\n\nHow can I help you today?"
    if lang == "ru":
        text = "🛡️ <b>Velox Assistant</b>\n\nЯ твой помощник по рынку и риск-менеджменту. У меня есть контекст по твоему портфелю, вотчлисту и текущей ситуации на рынке.\n\nЧем я могу помочь сегодня?"
    await smart_edit(call, text, reply_markup=kb.as_markup())
    await state.set_state(AIStates.waiting_for_chat)
    mem = await db.get_hedge_memory(call.message.chat.id, limit=10)
    await state.update_data(history=[{"role": m.get("role", "user"), "content": m.get("content", "")} for m in mem if m.get("content")])
    await call.answer()

@router.message(AIStates.waiting_for_chat, ~F.text.startswith("/"))
async def process_hedge_chat(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    if not await _consume_billing_usage(message, message.chat.id, lang, BILLING_USAGE_ASSISTANT, "assistant_messages_daily", "billing_feature_assistant_messages"):
        return
    data = await state.get_data()
    history = data.get("history", [])
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    history.append({"role": "user", "content": message.text})
    await db.append_hedge_memory(message.chat.id, role="user", content=message.text, meta={"context_type": "chat"})
    response = await market_overview.generate_hedge_comment(context_type="chat", event_data={"user_msg": message.text}, user_id=message.from_user.id, lang=lang, history=history)
    if not response:
        response = "⚠️ I am having trouble connecting to my brain. Please try again."
        if lang == "ru": response = "⚠️ Возникли трудности с подключением. Попробуй еще раз."
    disp_response = html.escape(response)
    disp_response = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', disp_response)
    disp_response = re.sub(r'\*(.*?)\*', r'<i>\1</i>', disp_response)
    history.append({"role": "assistant", "content": response})
    await db.append_hedge_memory(message.chat.id, role="assistant", content=response, meta={"context_type": "chat"})
    if len(history) > 10: history = history[-10:]
    await state.update_data(history=history)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:overview")
    await message.answer(disp_response, reply_markup=kb.as_markup(), parse_mode="HTML")

async def _send_hedge_insight(bot, chat_id, user_id, context_type, event_data, reply_to_id=None):
    try:
        cfg = await db.get_hedge_settings(user_id)
        if not cfg.get("enabled"): return
        if not cfg.get("triggers", {}).get(context_type, True): return
        lang = await db.get_lang(chat_id)
        try: await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception: pass
        comment = await market_overview.generate_hedge_comment(context_type=context_type, event_data=event_data, user_id=user_id, lang=lang)
        if comment:
            try: event_txt = json.dumps(event_data, ensure_ascii=False)[:700]
            except Exception: event_txt = str(event_data)[:700]
            await db.append_hedge_memory(user_id, role="system", content=f"{context_type}: {event_txt}", meta={"context_type": context_type})
            await db.append_hedge_memory(user_id, role="assistant", content=comment, meta={"context_type": context_type})
            disp_comment = html.escape(comment)
            disp_comment = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', disp_comment)
            disp_comment = re.sub(r'\*(.*?)\*', r'<i>\1</i>', disp_comment)
            await bot.send_message(chat_id=chat_id, text=f"🛡️ <b>Velox Assistant:</b>\n{disp_comment}", parse_mode="HTML", reply_to_message_id=reply_to_id)
    except Exception as e:
        logger.error(f"Error in Hedge Insight task: {e}")
