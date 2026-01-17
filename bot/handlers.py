import asyncio
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, BufferedInputFile, InputMediaPhoto, ErrorEvent
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_symbol_name, get_mid_price, get_open_orders, get_spot_balances, 
    get_perps_state, pretty_float, get_user_portfolio, get_perps_context,
    extract_avg_entry_from_balance, get_user_fills, get_hlp_info,
    get_user_vault_equities, get_user_funding, get_user_ledger,
    get_all_assets_meta, get_fear_greed_index
)
from bot.analytics import (
    generate_pnl_chart, format_funding_heatmap, generate_pnl_card, 
    calculate_trade_stats, generate_flex_pnl_card,
    prepare_terminal_dashboard_data_clean, prepare_positions_table_data,
    prepare_orders_table_data
)
from bot.market_overview import market_overview
import markdown
from bot.renderer import render_html_to_image
import logging
import time
import html
import re
import math
import csv
import io
import datetime

router = Router()
logger = logging.getLogger(__name__)

async def smart_edit(call: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None):
    """Edits text message or deletes photo and sends new text message."""
    try:
        # If the message has media, we usually want to delete it and send text
        # or edit media if we have new media (but this function is mostly for text)
        if call.message.photo or call.message.document:
            try:
                await call.message.delete()
            except:
                pass
            return await call.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        
        # If it's a regular text message, try to edit it
        try:
            return await call.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            # If editing fails (e.g. content is the same), just answer
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
            except:
                pass
            return await call.message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        return await call.message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML")

# --- UI Helpers ---

def _main_menu_kb(lang):
    kb = InlineKeyboardBuilder()
    # Row 0: Terminal
    kb.row(InlineKeyboardButton(text="🖥️ Terminal", callback_data="cb_terminal"))
    # Row 0.5: VELOX AI & Hedge
    kb.row(
        InlineKeyboardButton(text="🧠 Hedge AI", callback_data="cb_ai_overview_menu"),
        InlineKeyboardButton(text="🛡️ Hedge Chat", callback_data="cb_hedge_chat_start")
    )
    # Row 1: Portfolio & Trading
    kb.row(
        InlineKeyboardButton(text=_t(lang, "cat_portfolio"), callback_data="sub:portfolio"),
        InlineKeyboardButton(text=_t(lang, "cat_trading"), callback_data="sub:trading")
    )
    # Row 2: Market & Settings
    kb.row(
        InlineKeyboardButton(text=_t(lang, "cat_market"), callback_data="sub:market"),
        InlineKeyboardButton(text=_t(lang, "cat_settings"), callback_data="cb_settings")
    )
    return kb.as_markup()

def _portfolio_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_balance"), callback_data="cb_balance:portfolio"),
        InlineKeyboardButton(text=_t(lang, "btn_pnl"), callback_data="cb_pnl")
    )
    # Cross-link to Trading
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_positions"), callback_data="cb_positions:portfolio:0"),
        InlineKeyboardButton(text=_t(lang, "btn_orders"), callback_data="cb_orders:portfolio:0")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _trading_kb(lang):
    kb = InlineKeyboardBuilder()
    # Row 0: Balance (Full Width)
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_balance"), callback_data="cb_balance:trading"))
    
    # Row 1: Positions & Orders
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_positions"), callback_data="cb_positions:trading:0"),
        InlineKeyboardButton(text=_t(lang, "btn_orders"), callback_data="cb_orders:trading:0")
    )
    
    # Row 2: History & Stats
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_history"), callback_data="cb_fills"),
        InlineKeyboardButton(text=_t(lang, "btn_stats"), callback_data="cb_stats:trading")
    )
    
    # Row 3: Calculator & Risk Check
    kb.row(
        InlineKeyboardButton(text=_t(lang, "calc_btn"), callback_data="calc_start"),
        InlineKeyboardButton(text=_t(lang, "btn_risk_check"), callback_data="cb_risk_check")
    )
    
    # Row 4: Back
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _market_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_market"), callback_data="cb_market"),
        InlineKeyboardButton(text=_t(lang, "btn_whales"), callback_data="cb_whales")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_fear_greed"), callback_data="cb_fear_greed"),
        InlineKeyboardButton(text=_t(lang, "btn_price_alerts"), callback_data="cb_alerts")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_market_alerts"), callback_data="cb_market_alerts")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _back_kb(lang, target="cb_menu"):
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data=target)
    return kb.as_markup()

def _settings_kb(lang):
    kb = InlineKeyboardBuilder()
    # Row 0: AI Settings
    kb.row(
        InlineKeyboardButton(text="🧠 Hedge AI Overview", callback_data="cb_overview_settings_menu"),
        InlineKeyboardButton(text="🛡️ Velox Hedge", callback_data="cb_hedge_settings_menu")
    )
    # Row 1: Wallets & Flex
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_wallets"), callback_data="cb_wallets_menu"),
        InlineKeyboardButton(text=_t(lang, "btn_flex"), callback_data="cb_flex_menu")
    )
    # Row 2: Export & Language
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_export"), callback_data="cb_export"),
        InlineKeyboardButton(text=_t(lang, "btn_lang"), callback_data="cb_lang_menu")
    )
    # Row 3: Alert Types (Funding/OI)
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_funding_alert"), callback_data="cb_funding_alert_prompt"),
        InlineKeyboardButton(text=_t(lang, "btn_oi_alert"), callback_data="cb_oi_alert_prompt")
    )
    # Row 4: Thresholds
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_prox"), callback_data="set_prox_prompt"),
        InlineKeyboardButton(text=_t(lang, "btn_vol"), callback_data="set_vol_prompt"),
        InlineKeyboardButton(text=_t(lang, "btn_whale"), callback_data="set_whale_prompt")
    )
    # Row 5: Back
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _pagination_kb(lang: str, current_page: int, total_pages: int, callback_prefix: str, back_target: str = "cb_menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    
    # Navigation Buttons
    row = []
    if current_page > 0:
        row.append(InlineKeyboardButton(text="<<", callback_data=f"{callback_prefix}:{current_page-1}"))
    
    row.append(InlineKeyboardButton(text=f"{current_page+1}/{total_pages}", callback_data="noop"))
    
    if current_page < total_pages - 1:
        row.append(InlineKeyboardButton(text=">>", callback_data=f"{callback_prefix}:{current_page+1}"))
    
    kb.row(*row)
    
    # Extra buttons for Positions
    if "cb_positions" in callback_prefix:
        kb.row(
            InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data=f"{callback_prefix}:{current_page}"),
            InlineKeyboardButton(text=_t(lang, "btn_share"), callback_data="cb_share_pnl_menu")
        )
    elif "cb_orders" in callback_prefix:
        kb.row(InlineKeyboardButton(text=_t(lang, "btn_refresh"), callback_data=f"{callback_prefix}:{current_page}"))
        
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data=back_target))
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

@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = await db.get_lang(message.chat.id)
    await message.answer(_t(lang, "help_msg"), parse_mode="HTML")

@router.message(Command("add_wallet"))
async def cmd_add_wallet(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "add_wallet_usage"), parse_mode="HTML")
        return
    wallet = args[1].lower()
    await db.add_wallet(message.chat.id, wallet)
    
    ws = getattr(message.bot, "ws_manager", None)
    if ws:
        ws.track_wallet(wallet)
        await ws.subscribe_user(wallet)
        
    await message.answer(_t(lang, "tracking").format(wallet=wallet), reply_markup=_back_kb(lang), parse_mode="HTML")

@router.message(Command("tag"))
async def cmd_tag(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(_t(lang, "tag_usage"), parse_mode="HTML")
        return
    
    wallet = args[1].lower()
    tag = args[2]
    
    await db.update_wallet_settings(message.chat.id, wallet, tag=tag)
    await message.answer(_t(lang, "settings_updated"))

@router.message(Command("threshold"))
async def cmd_threshold(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 3:
        await message.answer(_t(lang, "threshold_usage"), parse_mode="HTML")
        return
    
    wallet = args[1].lower()
    try:
        threshold = float(args[2])
    except:
        await message.answer(_t(lang, "invalid_number"))
        return
    
    await db.update_wallet_settings(message.chat.id, wallet, threshold=threshold)
    await message.answer(_t(lang, "settings_updated"))

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
        await message.answer(_t(lang, "unknown_price", symbol=symbol), parse_mode="HTML")
        return
        
    direction = "above" if target > current else "below"
    
    await db.add_price_alert(message.chat.id, symbol, target, direction)
    
    dir_icon = "📈" if direction == "above" else "📉"
    msg = _t(lang, "alert_added").format(symbol=symbol, dir=dir_icon, price=pretty_float(target))
    await message.answer(msg, parse_mode="HTML")

@router.message(Command("f_alert"))
async def cmd_f_alert(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 3:
        await message.answer("⚠️ Usage: <code>/f_alert ETH 50</code> (Alert if APR > 50% or < -20%)", parse_mode="HTML")
        return
    
    symbol = args[1].upper()
    try:
        target = float(args[2])
    except:
        await message.answer(_t(lang, "invalid_number"))
        return

    # Determine direction automatically based on current funding
    ctx = await get_perps_context()
    universe = ctx[0].get("universe", [])
    asset_ctxs = ctx[1]
    idx = next((i for i, u in enumerate(universe) if u["name"] == symbol), -1)
    
    current_apr = 0.0
    if idx != -1:
        current_apr = float(asset_ctxs[idx].get("funding", 0)) * 24 * 365 * 100
    
    direction = "above" if target > current_apr else "below"
    await db.add_alert(message.chat.id, symbol, target, direction, "funding")
    
    dir_icon = "📈" if direction == "above" else "📉"
    await message.answer(_t(lang, "funding_alert_set", symbol=symbol, dir=dir_icon, val=target), parse_mode="HTML")

@router.message(Command("oi_alert"))
async def cmd_oi_alert(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 3:
        await message.answer("⚠️ Usage: <code>/oi_alert ETH 100</code> (Alert if OI > $100M)", parse_mode="HTML")
        return
    
    symbol = args[1].upper()
    try:
        target = float(args[2]) # In Millions USD
    except:
        await message.answer(_t(lang, "invalid_number"))
        return

    # Determine direction
    ctx = await get_perps_context()
    universe = ctx[0].get("universe", [])
    asset_ctxs = ctx[1]
    idx = next((i for i, u in enumerate(universe) if u["name"] == symbol), -1)
    
    current_oi = 0.0
    if idx != -1:
        current_oi = float(asset_ctxs[idx].get("openInterest", 0)) * float(asset_ctxs[idx].get("markPx", 0)) / 1e6
    
    direction = "above" if target > current_oi else "below"
    await db.add_alert(message.chat.id, symbol, target, direction, "oi")
    
    dir_icon = "📈" if direction == "above" else "📉"
    await message.answer(_t(lang, "oi_alert_set", symbol=symbol, dir=dir_icon, val=target), parse_mode="HTML")

async def _generate_export_files(wallet: str):
    """Internal helper to generate CSV files for a wallet."""
    # --- 1. Fetch Data ---
    portf, fills, funding, ledger = await asyncio.gather(
        get_user_portfolio(wallet),
        get_user_fills(wallet),
        get_user_funding(wallet),
        get_user_ledger(wallet),
        return_exceptions=True
    )
    
    # Handle exceptions in gather
    if isinstance(portf, Exception): portf = None
    if isinstance(fills, Exception): fills = []
    if isinstance(funding, Exception): funding = []
    if isinstance(ledger, Exception): ledger = []

    history = []
    pnl_history = []
    
    if portf:
        target_data = {}
        if isinstance(portf, list):
            for item in portf:
                if isinstance(item, list) and len(item) == 2:
                    period, p_data = item
                    if period == "allTime":
                        target_data = p_data
                        break
            if not target_data and portf and isinstance(portf[0], list) and len(portf[0]) == 2:
                    target_data = portf[0][1]
        elif isinstance(portf, dict):
            target_data = portf.get("data", {})
        
        history = target_data.get("accountValueHistory", [])
        pnl_history = target_data.get("pnlHistory", [])

    if not history and not fills and not funding and not ledger:
        return None, None

    # --- 2. Process History CSV ---
    # Combined list for History: [ts, date, equity, pnl, cash_flow, funding, type]
    combined_history = []
    pnl_map = {p[0]: p[1] for p in pnl_history} if pnl_history else {}

    for p in history:
        ts = p[0]
        combined_history.append({
            "ts": ts,
            "equity": p[1],
            "pnl": pnl_map.get(ts, "0"),
            "cash": 0,
            "funding": 0,
            "type": "Equity Sample"
        })

    for l in ledger:
        combined_history.append({
            "ts": l.get("time", 0),
            "equity": "",
            "pnl": "",
            "cash": l.get("delta", {}).get("amount", 0),
            "funding": 0,
            "type": f"Ledger: {l.get('delta', {}).get('type', 'update')}"
        })

    for f in funding:
        combined_history.append({
            "ts": f.get("time", 0),
            "equity": "",
            "pnl": "",
            "cash": 0,
            "funding": f.get("delta", {}).get("amount", 0),
            "type": "Funding Payment"
        })

    combined_history.sort(key=lambda x: x["ts"])

    output_hist = io.StringIO()
    writer_hist = csv.writer(output_hist)
    writer_hist.writerow(["Timestamp", "Date", "Equity", "PnL (Cumulative)", "Cash Flow", "Funding", "Type"])
    
    for row in combined_history:
        dt = datetime.datetime.fromtimestamp(row["ts"]/1000).strftime("%Y-%m-%d %H:%M:%S")
        writer_hist.writerow([row["ts"], dt, row["equity"], row["pnl"], row["cash"], row["funding"], row["type"]])
    
    output_hist.seek(0)
    doc_hist = BufferedInputFile(output_hist.getvalue().encode(), filename=f"history_{wallet[:6]}.csv")

    # --- 3. Process Fills CSV ---
    output_fills = io.StringIO()
    writer_fills = csv.writer(output_fills)
    writer_fills.writerow(["Time", "Symbol", "Side", "Price", "Size", "Value", "Fee", "Realized PnL", "Trade ID", "Liquidity", "Type"])
    
    # Combine Fills and Funding for detailed transaction view
    combined_fills = []
    for f in fills:
        combined_fills.append({
            "time": f.get("time", 0),
            "coin": f.get("coin", ""),
            "side": f.get("side", ""),
            "dir": f.get("dir", ""),
            "px": f.get("px", 0),
            "sz": f.get("sz", 0),
            "fee": f.get("fee", 0),
            "pnl": f.get("closedPnl", 0),
            "tid": f.get("tid", ""),
            "liq": f.get("liquidity", ""),
            "type": "Fill"
        })
    
    for f in funding:
        combined_fills.append({
            "time": f.get("time", 0),
            "coin": f.get("delta", {}).get("coin", ""),
            "side": "",
            "dir": "Funding",
            "px": f.get("delta", {}).get("fundingRate", 0),
            "sz": f.get("delta", {}).get("szi", 0),
            "fee": 0,
            "pnl": f.get("delta", {}).get("amount", 0),
            "tid": f.get("hash", ""),
            "liq": "",
            "type": "Funding"
        })

    combined_fills.sort(key=lambda x: x["time"], reverse=True)

    for f in combined_fills:
        try:
            ts = f["time"]
            dt = datetime.datetime.fromtimestamp(ts/1000).strftime("%Y-%m-%d %H:%M:%S")
            coin = f["coin"]
            if coin.startswith("@"):
                try: coin = await get_symbol_name(coin)
                except: pass
            
            direction = f["dir"]
            if not direction and f["type"] == "Fill":
                direction = "Buy" if f["side"] == "B" else "Sell"
            
            px = float(f["px"])
            sz = float(f["sz"])
            val = px * sz if f["type"] == "Fill" else 0
            
            writer_fills.writerow([dt, coin, direction, px, sz, f"{val:.2f}", f["fee"], f["pnl"], f["tid"], f["liq"], f["type"]])
        except:
            continue

    output_fills.seek(0)
    doc_fills = BufferedInputFile(output_fills.getvalue().encode(), filename=f"fills_{wallet[:6]}.csv")
    
    return doc_hist, doc_fills

@router.message(Command("funding"))
async def cmd_funding(message: Message):
    await _show_funding_page(message.chat.id, message.chat.id, page=0, edit=False)

@router.callback_query(F.data.startswith("cb_funding:"))
async def cb_funding_page(call: CallbackQuery):
    parts = call.data.split(":")
    page = int(parts[1])
    await _show_funding_page(call.message.chat.id, call.message.chat.id, page=page, edit=True, msg_id=call.message.message_id)
    await call.answer()

async def _render_funding_page(bot, chat_id, page=0, edit=False, msg_id=None):
    lang = await db.get_lang(chat_id)
    wallets = await db.list_wallets(chat_id)
    
    if not wallets:
        if edit:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_t(lang, "need_wallet"), parse_mode="HTML")
            except: pass
        else:
            await bot.send_message(chat_id, _t(lang, "need_wallet"), parse_mode="HTML")
        return

    from bot.services import get_user_funding
    from datetime import datetime
    import time
    
    start_ts = int((time.time() - 86400) * 1000) # 24h ago
    all_updates = []
    
    # Aggregate
    for wallet in wallets:
        updates = await get_user_funding(wallet, start_time=start_ts)
        if updates:
            for u in updates:
                u['wallet'] = wallet
            all_updates.extend(updates)
            
    # Sort
    all_updates.sort(key=lambda x: int(x.get("time", 0)), reverse=True)
    
    # Pagination
    ITEMS_PER_PAGE = 10
    total_items = len(all_updates)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
    
    if page >= total_pages: page = max(0, total_pages - 1)
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    items = all_updates[start_idx:end_idx]
    
    # Calc Total Sum (Global)
    total_sum_usd = sum([float(u.get("delta", {}).get("usdc", 0) or 0) for u in all_updates])
    
    msg_text = f"💰 <b>{_t(lang, 'funding_log_title')}</b>\n"
    msg_text += f"Total (24h): <b>${pretty_float(total_sum_usd, 2)}</b>\n\n"
    
    if not items:
        msg_text += f"<i>{_t(lang, 'funding_empty')}</i>"
    else:
        for item in items:
            ts = int(item.get("time", 0)) / 1000
            t_str = datetime.fromtimestamp(ts).strftime('%H:%M')
            delta = item.get("delta", {})
            sym = delta.get("coin", "???")
            amount = float(delta.get("usdc", 0) or 0)
            
            w_short = f"{item['wallet'][:4]}..{item['wallet'][-3:]}"
            val_str = f"{amount:+.2f}"
            
            msg_text += f"• {t_str} <b>{sym}</b>: <b>${val_str}</b> [{w_short}]\n"
            
    msg_text += f"\n<i>Page {page+1}/{max(1, total_pages)}</i>"
    
    # Buttons
    kb = InlineKeyboardBuilder()
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="<<", callback_data=f"cb_funding:{page-1}"))
    row.append(InlineKeyboardButton(text="🔄", callback_data=f"cb_funding:{page}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text=">>", callback_data=f"cb_funding:{page+1}"))
    kb.row(*row)
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    
    if edit and msg_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=msg_text, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception:
            pass
    else:
        await bot.send_message(chat_id, msg_text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.message(Command("funding"))
async def cmd_funding(message: Message):
    await _render_funding_page(message.bot, message.chat.id, page=0, edit=False)

@router.callback_query(F.data.startswith("cb_funding:"))
async def cb_funding_page(call: CallbackQuery):
    parts = call.data.split(":")
    page = int(parts[1])
    await _render_funding_page(call.message.bot, call.message.chat.id, page=page, edit=True, msg_id=call.message.message_id)
    await call.answer()

@router.message(Command("export"))
async def cmd_export(message: Message):
    status_msg = await message.answer("⏳ Exporting data...")
    lang = await db.get_lang(message.chat.id)
    wallets = await db.list_wallets(message.chat.id)
    if not wallets:
        await status_msg.edit_text(_t(lang, "need_wallet"))
        return
    
    found_any = False
    
    for wallet in wallets:
        try:
            await status_msg.edit_text(f"⏳ Exporting {wallet[:6]}... (History & Fills)")
        except:
            pass

        doc_hist, doc_fills = await _generate_export_files(wallet)
        
        if doc_hist:
            found_any = True
            await message.answer_document(doc_hist, caption=f"📊 Equity & Ledger History: {wallet[:6]}")
        
        if doc_fills:
            found_any = True
            await message.answer_document(doc_fills, caption=f"📝 Trade & Transaction History: {wallet[:6]}")

    try:
        if not found_any:
            await status_msg.edit_text("❌ No data found for any tracked wallets.")
        else:
            await status_msg.delete()
    except:
        pass


# --- CALLBACKS ---

@router.callback_query(F.data == "cb_export")
async def cb_export(call: CallbackQuery):
    await call.answer("Exporting...")
    status_msg = await call.message.answer("⏳ Exporting data...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await status_msg.edit_text(_t(lang, "need_wallet"))
        return
    
    found_any = False
    
    for wallet in wallets:
        try:
            await status_msg.edit_text(f"⏳ Exporting {wallet[:6]}... (History & Fills)")
        except:
            pass

        doc_hist, doc_fills = await _generate_export_files(wallet)
        
        if doc_hist:
            found_any = True
            await call.message.answer_document(doc_hist, caption=f"📊 Equity & Ledger History: {wallet[:6]}")
        
        if doc_fills:
            found_any = True
            await call.message.answer_document(doc_fills, caption=f"📝 Trade & Transaction History: {wallet[:6]}")

    try:
        if not found_any:
            await status_msg.edit_text("❌ No data found for any tracked wallets.")
        else:
            await status_msg.delete()
    except:
        pass


@router.callback_query(F.data == "cb_menu")
async def cb_menu(call: CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    text = _t(lang, "welcome")
    if wallets:
        text += "\n\n" + _t(lang, "tracking").format(wallet=f"{wallets[0][:6]}...{wallets[0][-4:]}")
    
    await smart_edit(call, text, reply_markup=_main_menu_kb(lang))
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

@router.callback_query(F.data == "sub:market")
async def cb_sub_market(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "menu_market"), reply_markup=_market_kb(lang))
    await call.answer()

@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()

@router.callback_query(F.data.startswith("cb_balance"))
async def cb_balance(call: CallbackQuery):
    await call.answer("Loading...")
    
    parts = call.data.split(":")
    context = parts[1] if len(parts) > 1 else "portfolio"
    
    # Determine back target
    back_target = "sub:portfolio"
    if context == "trading":
        back_target = "sub:trading"
    elif context == "portfolio":
        back_target = "sub:portfolio"
        
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
        return

    msg_parts = []
    ws = getattr(call.message.bot, "ws_manager", None)

    for wallet in wallets:
        spot_bals = await get_spot_balances(wallet)
        perps_state = await get_perps_state(wallet)
        vault_equities = await get_user_vault_equities(wallet)
        
        wallet_lines = []
        wallet_total = 0.0
        
        # 1. Process Spot
        if spot_bals:
            for b in spot_bals:
                coin_id = b.get("coin")
                coin_name = await get_symbol_name(coin_id, is_spot=True)
                amount = float(b.get("total", 0) or 0)
                hold = float(b.get("hold", 0) or 0)
                
                if amount <= 0: continue
                
                px = 0.0
                if ws: px = ws.get_price(coin_name, coin_id)
                if not px: px = await get_mid_price(coin_name, coin_id)
                
                val = amount * px
                wallet_total += val
                
                # Calculate Avg Entry and PnL%
                entry = extract_avg_entry_from_balance(b)
                if not entry or entry <= 0:
                    try:
                        coin_fills = await db.get_fills_by_coin(wallet, coin_id)
                        from bot.services import calc_avg_entry_from_fills
                        entry = calc_avg_entry_from_fills(coin_fills)
                    except:
                        entry = 0.0

                pnl_str = ""
                if entry > 0 and px > 0:
                    pnl_pct = ((px / entry) - 1) * 100
                    pnl_usd = (px - entry) * amount
                    pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
                    pnl_str = f" | {pnl_icon} {pnl_pct:+.1f}% (${pretty_float(pnl_usd, 2)})"

                line = f"▫️ <b>{coin_name}</b>: {amount:.4f} (${pretty_float(val, 0)})"
                if entry > 0:
                    line += f"\n     └ {_t(lang, 'avg_lbl')}: ${pretty_float(entry)}{pnl_str}"
                
                if hold > 0:
                    line += f" (🔒 {hold:.4f})"
                wallet_lines.append(line)

        # 2. Vaults logic
        vault_total = 0.0
        vault_lines = []
        if vault_equities:
            for v in vault_equities:
                v_name = v.get("vaultAddress")
                v_equity = float(v.get("equity", 0))
                if v_equity > 1:
                    vault_total += v_equity
                    disp_name = "HLP" if "df13098394e1832014b0df3f91285497" in v_name.lower() else f"Vault {v_name[:6]}"
                    vault_lines.append(f"🏛 <b>{disp_name}</b>: ${pretty_float(v_equity, 2)}")

        # 3. Perps Logic
        perps_equity = 0.0
        margin_used = 0.0
        total_ntl = 0.0
        total_upnl = 0.0
        withdrawable = 0.0
        maint_margin = 0.0
        
        if perps_state:
            withdrawable = float(perps_state.get("withdrawable", 0) or 0)
            maint_margin = float(perps_state.get("crossMaintenanceMarginUsed", 0) or 0)
            
            if "marginSummary" in perps_state:
                ms = perps_state["marginSummary"]
                perps_equity = float(ms.get("accountValue", 0) or 0)
                margin_used = float(ms.get("totalMarginUsed", 0) or 0)
                total_ntl = float(ms.get("totalNtlPos", 0) or 0)
            
            for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {})
                coin_id = pos.get("coin")
                szi = float(pos.get("szi", 0))
                entry_px = float(pos.get("entryPx", 0))
                if szi == 0: continue
                
                sym = await get_symbol_name(coin_id, is_spot=False)
                mark_px = 0.0
                if ws: mark_px = ws.get_price(sym, coin_id)
                if not mark_px: mark_px = await get_mid_price(sym, coin_id)
                
                if mark_px:
                     total_upnl += (mark_px - entry_px) * szi

        # 4. Assemble Wallet Message
        header = f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b>"
        body = ""
        if wallet_lines:
            body += f"\n   <b>Spot:</b> ${pretty_float(wallet_total, 2)}\n   " + "\n   ".join(wallet_lines)
        
        if vault_lines:
            body += f"\n   <b>{_t(lang, 'vaults_lbl')}:</b> ${pretty_float(vault_total, 2)}\n   " + "\n   ".join(vault_lines)

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
        
        if not body: body = f"\n   {_t(lang, 'empty_state')}"
        msg_parts.append(header + body)

    text = _t(lang, "balance_title") + "\n\n" + "\n\n".join(msg_parts)
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_refresh"), callback_data=f"cb_balance:{context}")
    kb.button(text="📊 Portfolio Chart", callback_data="cb_portfolio_chart")
    kb.button(text=_t(lang, "btn_back"), callback_data=back_target)
    kb.adjust(1)
    
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_portfolio_chart")
async def cb_portfolio_chart(call: CallbackQuery):
    await call.answer("Analyzing portfolio composition...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets: return
    
    ws = getattr(call.message.bot, "ws_manager", None)
    
    # Aggregate all assets
    assets_map = {} # sym -> usd_value
    
    for wallet in wallets:
        # Spot
        spot_bals = await get_spot_balances(wallet)
        if spot_bals:
            for b in spot_bals:
                coin_id = b.get("coin")
                name = await get_symbol_name(coin_id, is_spot=True)
                amount = float(b.get("total", 0) or 0)
                if amount <= 0: continue
                
                px = 0.0
                if ws: px = ws.get_price(name, coin_id)
                if not px: px = await get_mid_price(name, coin_id)
                
                val = amount * px
                assets_map[name] = assets_map.get(name, 0) + val
                
        # Perps Equity
        perps_state = await get_perps_state(wallet)
        if perps_state and "marginSummary" in perps_state:
             val = float(perps_state["marginSummary"].get("accountValue", 0) or 0)
             assets_map["USDC (Margin)"] = assets_map.get("USDC (Margin)", 0) + val

    if not assets_map:
        await call.answer("No assets found.", show_alert=True)
        return
        
    assets_list = [{"name": k, "value": v} for k, v in assets_map.items() if v > 1]
    
    from bot.analytics import prepare_portfolio_composition_data
    from bot.renderer import render_html_to_image
    
    comp_data = prepare_portfolio_composition_data(assets_list)
    
    try:
        buf = await render_html_to_image("portfolio_composition.html", comp_data)
        photo = BufferedInputFile(buf.read(), filename="portfolio.png")
        await smart_edit_media(call, photo, "📊 <b>Portfolio Composition</b>", reply_markup=_back_kb(lang, "cb_balance:portfolio"))
    except Exception as e:
        logger.error(f"Error rendering portfolio composition: {e}")
        await call.message.answer("❌ Error generating image.")

@router.callback_query(F.data.startswith("cb_positions"))
async def cb_positions(call: CallbackQuery):
    # Parse data: cb_positions:context:page OR cb_positions:page (legacy)
    parts = call.data.split(":")
    if len(parts) == 3:
        context = parts[1]
        try: page = int(parts[2])
        except: page = 0
    elif len(parts) == 2:
        context = "trading"
        try: page = int(parts[1])
        except: page = 0
    else:
        context = "trading"
        page = 0

    # Determine back target
    back_target = "sub:trading"
    if context == "portfolio":
        back_target = "sub:portfolio"

    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
        return

    # Gather ALL positions first
    all_positions_data = [] # List of tuples/dicts to render
    ws = getattr(call.message.bot, "ws_manager", None)

    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        positions = state.get("assetPositions", [])
        for p in positions:
            pos = p.get("position", {})
            szi = float(pos.get("szi", 0))
            if szi == 0: continue
            
            # Enrich data
            coin_id = pos.get("coin")
            sym = await get_symbol_name(coin_id, is_spot=False)
            entry_px = float(pos.get("entryPx", 0))
            leverage = float(pos.get("leverage", {}).get("value", 0))
            liq_px = float(pos.get("liquidationPx", 0) or 0)
            
            mark_px = 0.0
            if ws: mark_px = ws.get_price(sym, coin_id)
            if not mark_px: mark_px = await get_mid_price(sym, coin_id)
            
            upnl = (mark_px - entry_px) * szi if mark_px else 0.0
            roi = 0.0
            if leverage and szi and entry_px:
                 roi = (upnl / (abs(szi) * entry_px / leverage)) * 100
            
            all_positions_data.append({
                "wallet": wallet,
                "sym": sym,
                "szi": szi,
                "entry": entry_px,
                "lev": leverage,
                "liq": liq_px,
                "upnl": upnl,
                "roi": roi
            })

    if not all_positions_data:
        text = _t(lang, "positions_title") + "\n\n" + _t(lang, "no_open_positions")
        await smart_edit(call, text, reply_markup=_back_kb(lang, back_target))
        return

    # Pagination Logic
    ITEMS_PER_PAGE = 5
    total_pages = math.ceil(len(all_positions_data) / ITEMS_PER_PAGE)
    
    # Cap page
    if page >= total_pages: page = total_pages - 1
    if page < 0: page = 0
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = all_positions_data[start_idx:end_idx]
    
    msg_parts = []
    
    for item in page_items:
        icon = "🟢" if item["szi"] > 0 else "🔴"
        w_short = f"{item['wallet'][:4]}..{item['wallet'][-3:]}"
        line = (
            f"{icon} <b>{item['sym']}</b> {item['lev']}x [{w_short}]\n"
            f"   Sz: {item['szi']:.4f} @ ${pretty_float(item['entry'])}\n"
            f"   Liq: ${pretty_float(item['liq'])} | uPnL: <b>${pretty_float(item['upnl'], 2)}</b> ({item['roi']:+.0f}%)"
        )
        msg_parts.append(line)
        
        # Add Exit Calc button for the last item in the list for this demo/logic 
        # (Usually better to have one per item if they were separate messages, 
        # but here we'll add a specific callback for the first one for simplicity or adjust kb)
        
    text = f"{_t(lang, 'positions_title')} ({page+1}/{total_pages})\n\n" + "\n\n".join(msg_parts)
    
    kb = _pagination_kb(lang, page, total_pages, f"cb_positions:{context}", back_target=back_target)
    
    # Add Exit Calc buttons for the current page items
    for i, item in enumerate(page_items):
        btn_label = _t(lang, "calc_exit_btn", sym=item['sym'])
        # Store data in callback_data is size limited, so we use a shorthand
        # Format: calc_exit:SYM:ENTRY:SIZE:LEV:IS_LONG:LIQ
        cb_data = f"calc_exit:{item['sym']}:{item['entry']:.4f}:{abs(item['szi']):.4f}:{item['lev']}:{item['szi']>0}:{item['liq']:.2f}"
        if len(cb_data) > 64:
             # Fallback if too long
             cb_data = f"calc_exit:{item['sym']}:{int(item['entry'])}:{int(abs(item['szi']))}:{int(item['lev'])}:{item['szi']>0}:{int(item['liq'])}"
        
        kb.inline_keyboard.insert(-1, [InlineKeyboardButton(text=btn_label, callback_data=cb_data)])

    await smart_edit(call, text, reply_markup=kb)

@router.callback_query(F.data.startswith("calc_exit:"))
async def cb_calc_exit(call: CallbackQuery, state: FSMContext):
    # Format: calc_exit:SYM:ENTRY:SIZE:LEV:IS_LONG:LIQ
    parts = call.data.split(":")
    sym = parts[1]
    entry = float(parts[2])
    size = float(parts[3])
    lev = float(parts[4])
    is_long = parts[5] == "True"
    liq_px = float(parts[6]) if len(parts) > 6 else 0.0
    
    lang = await db.get_lang(call.message.chat.id)
    
    await state.update_data(
        mode="perp",
        side="long" if is_long else "short",
        entry=entry,
        size=size,
        lev=lev,
        is_exit=True,
        symbol=sym,
        liq_px=liq_px,
        # We don't know the user's total balance easily here, 
        # but we can derive it from size/lev for the calc to work
        balance= (size * entry) / lev if lev > 0 else size * entry
    )
    
    msg = _t(lang, "exit_calc_title", sym=sym) + _t(lang, "calc_sl")
    await call.message.answer(msg, parse_mode="HTML")
    await state.set_state(CalcStates.sl)
    await call.answer()

@router.callback_query(F.data == "cb_share_pnl_menu")
async def cb_share_pnl_menu(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        return
        
    kb = InlineKeyboardBuilder()
    
    # Collect all positions
    ws = getattr(call.message.bot, "ws_manager", None)
    
    has_pos = False
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        positions = state.get("assetPositions", [])
        for p in positions:
            pos = p.get("position", {})
            szi = float(pos.get("szi", 0))
            if szi == 0: continue
            has_pos = True
            
            coin_id = pos.get("coin")
            sym = await get_symbol_name(coin_id, is_spot=False)
            entry = float(pos.get("entryPx", 0))
            mark = 0.0
            if ws: mark = ws.get_price(sym)
            if not mark: mark = await get_mid_price(sym, coin_id)
            
            upnl = (mark - entry) * szi if mark else 0.0
            
            # Button Label: ETH +$100 / ETH -$50
            sign = "+" if upnl >= 0 else "-"
            label = f"{sym} {sign}${pretty_float(abs(upnl), 0)}"
            
            kb.button(text=label, callback_data=f"cb_share_pnl:{sym}")
            
    if not has_pos:
        await call.answer("No open positions to share.", show_alert=True)
        return
        
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_positions:0")
    kb.adjust(2) # 2 per row
    
    await smart_edit(call, _t(lang, "select_pos"), reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("cb_share_pnl:"))
async def cb_share_pnl(call: CallbackQuery):
    symbol = call.data.split(":")[1]
    await call.answer(f"Generating card for {symbol}...")
    
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    ws = getattr(call.message.bot, "ws_manager", None)
    
    target_pos = None
    
    # Find the position again
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        positions = state.get("assetPositions", [])
        for p in positions:
            pos = p.get("position", {})
            coin_id = pos.get("coin")
            sym_name = await get_symbol_name(coin_id, is_spot=False)
            if sym_name == symbol:
                szi = float(pos.get("szi", 0))
                if szi == 0: continue
                target_pos = pos
                break
        if target_pos: break
        
    if not target_pos:
        await call.message.answer(_t(lang, "pos_not_found"))
        return
        
    # Prepare Data
    szi = float(target_pos.get("szi", 0))
    entry = float(target_pos.get("entryPx", 0))
    leverage = float(target_pos.get("leverage", {}).get("value", 1))
    
    mark = 0.0
    if ws: mark = ws.get_price(symbol)
    if not mark: mark = await get_mid_price(symbol)
    
    upnl = (mark - entry) * szi
    roi = 0.0
    if leverage and szi and entry:
         roi = (upnl / (abs(szi) * entry / leverage)) * 100
         
    side = "LONG" if szi > 0 else "SHORT"
    
    data = {
        "symbol": symbol,
        "side": side,
        "leverage": leverage,
        "entry": entry,
        "mark": mark,
        "roi": roi,
        "pnl": upnl
    }
    
    from bot.analytics import prepare_pnl_card_data
    from bot.renderer import render_html_to_image
    
    pnl_data = prepare_pnl_card_data(data)
    try:
        buf = await render_html_to_image("pnl_card.html", pnl_data)
        photo = BufferedInputFile(buf.read(), filename=f"pnl_{data['symbol']}.png")
        await smart_edit_media(call, photo, f"🚀 <b>{data['symbol']} Position</b>", reply_markup=_back_kb(lang, "cb_positions:0"))
    except Exception as e:
        logger.error(f"Error rendering PnL card: {e}")
        await call.message.answer("❌ Error generating image.")

@router.callback_query(F.data.startswith("cb_orders"))
async def cb_orders(call: CallbackQuery):
    # Parse data: cb_orders:context:page OR cb_orders:page
    parts = call.data.split(":")
    if len(parts) == 3:
        context = parts[1]
        try: page = int(parts[2])
        except: page = 0
    elif len(parts) == 2:
        context = "trading"
        try: page = int(parts[1])
        except: page = 0
    else:
        context = "trading"
        page = 0

    # Determine back target
    back_target = "sub:trading"
    if context == "portfolio":
        back_target = "sub:portfolio"
        
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
        return

    all_orders = []
    # Fetch balances and positions once per wallet for speed
    wallet_data = {} # {wallet: {'spot': balances, 'perps': perps_state}}

    for wallet in wallets:
        orders = await get_open_orders(wallet)
        if isinstance(orders, dict): orders = orders.get("orders", [])
        if not orders: continue
        
        spot_bals = await get_spot_balances(wallet)
        perps_state = await get_perps_state(wallet)
        wallet_data[wallet] = {"spot": spot_bals, "perps": perps_state}
        
        for o in orders:
            o["wallet"] = wallet
            all_orders.append(o)
            
    if not all_orders:
        text = _t(lang, "orders_title") + "\n\n" + _t(lang, "no_open_orders")
        await smart_edit(call, text, reply_markup=_back_kb(lang, back_target))
        return

    # Pagination
    ITEMS_PER_PAGE = 5
    total_pages = math.ceil(len(all_orders) / ITEMS_PER_PAGE)
    if page >= total_pages: page = total_pages - 1
    if page < 0: page = 0
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = all_orders[start_idx:end_idx]
    
    msg_parts = []
    for o in page_items:
        wallet = o["wallet"]
        # Resolve coin name
        coin_raw = o.get("coin")
        is_spot = str(coin_raw).startswith("@")
        sym = await get_symbol_name(coin_raw, is_spot=is_spot)
        
        # Determine market type label
        market_type = "Spot" if is_spot else "Perp"
        
        sz = float(o.get("sz", 0))
        px = float(o.get("limitPx", 0))
        side = str(o.get("side", "")).lower()
        is_buy = side.startswith("b")
        
        # Calculate distance
        current_px = await get_mid_price(sym, coin_raw)
        dist_str = "n/a"
        if current_px > 0 and px > 0:
            diff = ((px - current_px) / current_px) * 100
            dist_str = f"<b>{diff:+.2f}%</b>"
            
        icon = "🟢" if is_buy else "🔴"
        side_label = "BUY" if is_buy else "SELL"
        w_short = f"{wallet[:4]}..{wallet[-3:]}"
        
        val_usd = sz * px
        
        # --- Profit/New Avg Logic ---
        profit_line = ""
        avg_entry = 0.0
        current_sz = 0.0
        
        if is_spot:
            bals = wallet_data[wallet]["spot"]
            for b in bals:
                if str(b.get("coin")) == str(coin_raw):
                    avg_entry = extract_avg_entry_from_balance(b)
                    current_sz = float(b.get("total", 0))
                    break
        else:
            pstate = wallet_data[wallet]["perps"]
            if pstate:
                for p in pstate.get("assetPositions", []):
                    pos = p.get("position", {})
                    if str(pos.get("coin")) == str(coin_raw):
                        avg_entry = float(pos.get("entryPx", 0))
                        current_sz = float(pos.get("szi", 0))
                        break

        if not is_buy: # SELL order
            if avg_entry > 0:
                profit_usd = (px - avg_entry) * sz
                if not is_spot and current_sz < 0: # Closing a short
                    profit_usd = (avg_entry - px) * sz
                
                profit_pct = ((px / avg_entry) - 1) * 100
                if not is_spot and current_sz < 0:
                    profit_pct = ((avg_entry / px) - 1) * 100
                
                p_color = "🟢" if profit_usd >= 0 else "🔴"
                profit_line = f"\n   " + _t(lang, "profit_if_filled", val=f"{p_color}\"${pretty_float(profit_usd, 2)}", pct=f"{profit_pct:+.1f}")
        else: # BUY order
            if avg_entry > 0:
                if not is_spot and current_sz < 0: # Closing a short
                    profit_usd = (avg_entry - px) * sz
                    profit_pct = ((avg_entry / px) - 1) * 100
                    p_color = "🟢" if profit_usd >= 0 else "🔴"
                    profit_line = f"\n   " + _t(lang, "profit_if_filled", val=f"{p_color}\"${pretty_float(profit_usd, 2)}", pct=f"{profit_pct:+.1f}")
                elif current_sz > 0: # Increasing long
                    new_sz = current_sz + sz
                    new_avg = ((current_sz * avg_entry) + (sz * px)) / new_sz
                    diff_avg = ((new_avg / avg_entry) - 1) * 100
                    profit_line = f"\n   " + _t(lang, "new_avg_if_filled", val=pretty_float(new_avg, 2), pct=f"{diff_avg:+.1f}")

        item_text = (
            f"{icon} <b>{sym}</b> [{market_type}]\n"
            f"   {side_label}: {sz} @ \"${pretty_float(px)}\" (~${pretty_float(val_usd, 2)})\n"
            f"   Цена: ${pretty_float(current_px)} | До входа: {dist_str} [{w_short}]"
            f"{profit_line}"
        )
        msg_parts.append(item_text)

    text = f"{_t(lang, 'orders_title')} ({page+1}/{total_pages})\n\n" + "\n\n".join(msg_parts)
    
    kb = _pagination_kb(lang, page, total_pages, f"cb_orders:{context}", back_target=back_target)
    
    await smart_edit(call, text, reply_markup=kb)

@router.callback_query(F.data == "cb_settings")
async def cb_settings(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await smart_edit(call, _t(lang, "settings_title"), reply_markup=_settings_kb(lang))
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
    lang_code = call.data.split(":")[1]
    await db.set_lang(call.message.chat.id, lang_code)
    await cb_settings(call)

@router.callback_query(F.data == "cb_alerts")
async def cb_alerts(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    alerts = await db.get_user_alerts(call.message.chat.id)
    ts = time.strftime("%H:%M:%S")
    
    if not alerts:
        text = f"{_t(lang, 'market_title')} > <b>{_t(lang, 'btn_price_alerts')}</b>\n\n{_t(lang, 'no_alerts')}\n{_t(lang, 'alert_usage')}\n\n<i>Last update: {ts}</i>"
        await smart_edit(call, text, reply_markup=_back_kb(lang, "sub:market"))
        return

    kb = InlineKeyboardBuilder()
    text = _t(lang, "alerts_list") + "\n"
    
    for a in alerts:
        aid = str(a["_id"])
        s = str(a.get("symbol", "???"))
        p = pretty_float(a.get("target", 0))
        d = "📈" if a.get("direction") == "above" else "📉"
        
        # Plain text format
        text += f"\n• {s} {d} {p}"
        kb.button(text=f"❌ Del {s}", callback_data=f"del_alert:{aid}")
        
    kb.button(text="🗑️ Clear All", callback_data="clear_all_alerts")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    text += f"\n\n<i>Last update: {ts}</i>"
    
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_wallets_menu")
async def cb_wallets_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets_full(call.message.chat.id)
    
    if not wallets:
        await call.message.edit_text(
            f"📭 {_t(lang, 'need_wallet')}",
            reply_markup=_settings_kb(lang),
            parse_mode="HTML"
        )
        return

    text = f"👛 <b>{_t(lang, 'btn_wallets')}</b>\n\n"
    kb = InlineKeyboardBuilder()
    
    for w in wallets:
        addr = w["address"]
        tag = w.get("tag", "No Tag")
        thresh = w.get("threshold", 0.0)
        
        text += f"• <code>{addr[:6]}...{addr[-4:]}</code>\n"
        text += f"  Tag: <b>{tag}</b> | Min: <b>${thresh}</b>\n\n"
        
        kb.button(text=f"❌ Del {tag if tag != 'No Tag' else addr[:6]}", callback_data=f"cb_del_wallet:{addr}")

    text += "ℹ️ <i>Use /tag &lt;0x...&gt; &lt;Name&gt;\nUse /threshold &lt;0x...&gt; &lt;USD&gt;</i>"
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_settings")
    kb.adjust(1)
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("cb_del_wallet:"))
async def cb_del_wallet(call: CallbackQuery):
    addr = call.data.split(":")[1]
    await db.remove_wallet(call.message.chat.id, addr)
    await cb_wallets_menu(call)

@router.callback_query(F.data == "clear_all_alerts")
async def cb_clear_all_alerts(call: CallbackQuery):
    await db.delete_all_user_alerts(call.message.chat.id)
    lang = await db.get_lang(call.message.chat.id)
    await call.answer(_t(lang, "deleted"))
    await cb_alerts(call)

@router.callback_query(F.data.startswith("del_alert:"))
async def cb_del_alert(call: CallbackQuery):
    aid = call.data.split(":")[1]
    lang = await db.get_lang(call.message.chat.id)
    success = await db.delete_alert(aid)
    
    if success:
        await call.answer(_t(lang, "deleted"))
    else:
        # If it failed, maybe it was already deleted (race condition)
        await call.answer("🗑️ Alert already removed or error")
        
    await cb_alerts(call)

@router.callback_query(F.data.startswith("quick_alert:"))
async def cb_quick_alert(call: CallbackQuery):
    """Quick alert setup from fill notification"""
    symbol = call.data.split(":")[1]
    lang = await db.get_lang(call.message.chat.id)
    
    # Get current price
    current_price = await get_mid_price(symbol)
    if not current_price:
        await call.answer("❌ Cannot get price", show_alert=True)
        return
    
    # Suggest +/- 3% as default targets
    above_target = current_price * 1.03
    below_target = current_price * 0.97
    
    text = f"🔔 <b>Quick Alert: {symbol}</b>\n\n"
    text += f"Current price: <b>${pretty_float(current_price)}</b>\n\n"
    text += "Choose alert type:"
    
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"📈 Above ${pretty_float(above_target)}", callback_data=f"set_quick_alert:{symbol}:above:{above_target}"),
        InlineKeyboardButton(text=f"📉 Below ${pretty_float(below_target)}", callback_data=f"set_quick_alert:{symbol}:below:{below_target}")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data.startswith("set_quick_alert:"))
async def cb_set_quick_alert(call: CallbackQuery):
    """Set the quick alert"""
    parts = call.data.split(":")
    symbol = parts[1]
    direction = parts[2]
    target = float(parts[3])
    
    lang = await db.get_lang(call.message.chat.id)
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
    # Basic validation
    if len(symbol) > 10 or not symbol.isalnum():
        await message.answer(_t(lang, "watch_invalid"))
        return

    await db.add_watch_symbol(message.chat.id, symbol)
    
    # Update WS subscription if needed (optional, for volatility alerts)
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
    
    # Update WS subscription
    ws = getattr(message.bot, "ws_manager", None)
    if ws and symbol in ws.watch_subscribers:
        ws.watch_subscribers[symbol].discard(message.chat.id)
        
    await message.answer(_t(lang, "watch_removed").format(symbol=symbol), parse_mode="HTML")

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
        
        # 24h Change
        prev_day = float(ac.get("prevDayPx", 0) or price)
        change_24h = ((price - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
        change_icon = "🟢" if change_24h >= 0 else "🔴"
        
        lines.append(
            f"🔹 <b>{sym}</b>: ${pretty_float(price, 4)} ({change_icon} {change_24h:+.2f}%)\n"
            f"   F: {funding_rate*100:.4f}% ({apr:.1f}% APR) | Vol: ${vol_str}"
        )
    
    # Add timestamp
    ts = time.strftime("%H:%M:%S", time.gmtime())
    text = f"{_t(lang, 'market_title')} (updated {ts})\n\n" + "\n\n".join(lines)
    text += "\n\nℹ️ <i>/watch SYM | /unwatch SYM</i>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_market_overview"), callback_data="cb_market_overview")
    kb.button(text=_t(lang, "btn_refresh"), callback_data="cb_market")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_market_overview")
async def cb_market_overview(call: CallbackQuery, state: FSMContext):
    await call.answer("Generating Market Insights...")
    lang = await db.get_lang(call.message.chat.id)
    
    # Fetch market data
    ctx, hlp_info = await asyncio.gather(
        get_perps_context(),
        get_hlp_info(),
        return_exceptions=True
    )
    
    if isinstance(ctx, Exception) or not ctx or not isinstance(ctx, list) or len(ctx) != 2:
        await call.message.answer("❌ Error fetching market data.")
        return
        
    if isinstance(hlp_info, Exception):
        hlp_info = None

    universe = ctx[0].get("universe", [])
    asset_ctxs = ctx[1]
    
    from bot.analytics import prepare_modern_market_data, prepare_liquidity_data, prepare_coin_prices_data
    from bot.renderer import render_html_to_image
    
    # Prepare data
    data_alpha = prepare_modern_market_data(asset_ctxs, universe, hlp_info)
    data_liq = prepare_liquidity_data(asset_ctxs, universe)
    data_prices = prepare_coin_prices_data(asset_ctxs, universe)
    
    # Fetch Fear & Greed
    from bot.services import get_fear_greed_index
    fng = await get_fear_greed_index()
    fng_text = ""
    if fng:
        fng_emoji = fng["emoji"]
        val = fng["value"]
        cl = fng["classification"]
        fng_text = f"• Fear/Greed: {fng_emoji} <b>{val}</b> ({cl})\n"
    
    try:
        # Render all images
        buf_alpha = await render_html_to_image("market_stats.html", data_alpha)
        buf_liq = await render_html_to_image("liquidity_stats.html", data_liq)
        buf_heat = await render_html_to_image("funding_heatmap.html", data_alpha)
        buf_prices = await render_html_to_image("coin_prices.html", data_prices)
        
        # 1. Get detailed info for Majors
        majors_text = ""
        major_symbols = ["BTC", "ETH", "SOL", "HYPE"]
        for sym in major_symbols:
            idx = next((i for i, u in enumerate(universe) if u["name"] == sym), -1)
            if idx != -1:
                ac = asset_ctxs[idx]
                price = float(ac.get("markPx", 0))
                prev_day = float(ac.get("prevDayPx", 0) or price)
                change = ((price - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
                funding = float(ac.get("funding", 0)) * 24 * 365 * 100
                oi = float(ac.get("openInterest", 0)) * price / 1e6
                vol = float(ac.get("dayNtlVlm", 0)) / 1e6
                
                icon = "🟢" if change >= 0 else "🔴"
                majors_text += (
                    f"🔹 <b>{sym}</b>: ${pretty_float(price)} ({icon} {change:+.2f}%)\n"
                    f"   ├ F: <code>{funding:+.1f}% APR</code>\n"
                    f"   └ OI: <b>${oi:.1f}M</b> | Vol: <b>${vol:.1f}M</b>\n\n"
                )

        # 2. Build watchlist text
        watchlist = await db.get_watchlist(call.message.chat.id)
        watchlist_lines = []
        if watchlist:
            for sym in watchlist:
                if sym in major_symbols: continue
                idx = next((i for i, u in enumerate(universe) if u["name"] == sym), -1)
                if idx != -1:
                    ac = asset_ctxs[idx]
                    price = float(ac.get("markPx", 0))
                    prev_day = float(ac.get("prevDayPx", 0) or price)
                    change = ((price - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
                    icon = "🟢" if change >= 0 else "🔴"
                    watchlist_lines.append(f"• {sym}: ${pretty_float(price)} ({icon} {change:+.2f}%)")
        
        watchlist_text = ""
        if watchlist_lines:
            watchlist_text = f"⭐ <b>{_t(lang, 'market_report_watchlist')}</b>:\n" + "\n".join(watchlist_lines) + "\n\n"

        now_utc = time.strftime("%H:%M")
        text_report = (
            f"📊 <b>{_t(lang, 'market_alerts_title')}</b>\n\n"
            f"<b>{_t(lang, 'market_report_global')}</b>\n"
            f"• Vol 24h: <b>${data_alpha['global_volume']}</b>\n"
            f"• Total OI: <b>${data_alpha['total_oi']}</b>\n"
            f"• Sentiment: <code>{data_alpha['sentiment_label']}</code>\n"
            f"{fng_text}\n"
            f"<b>{_t(lang, 'market_report_majors')}</b>\n"
            f"{majors_text}"
            f"{watchlist_text}"
            f"🕒 <i>{_t(lang, 'market_report_footer', time=now_utc + ' UTC')}</i>"
        )

        media = [
            InputMediaPhoto(media=BufferedInputFile(buf_prices.read(), filename="insights_1.png")),
            InputMediaPhoto(media=BufferedInputFile(buf_heat.read(), filename="insights_2.png")),
            InputMediaPhoto(media=BufferedInputFile(buf_alpha.read(), filename="insights_3.png")),
            InputMediaPhoto(media=BufferedInputFile(buf_liq.read(), filename="insights_4.png"))
        ]
        
        await call.message.delete()
        media_msgs = await call.message.answer_media_group(media)
        # Store message IDs for cleanup
        await state.update_data(market_media_ids=[m.message_id for m in media_msgs])
        
        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "btn_back"), callback_data="cb_market_cleanup")
        
        await call.message.answer(text_report, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error generating images: {e}")
        await call.message.answer("❌ Error generating images.")

@router.callback_query(F.data == "cb_market_cleanup")
async def cb_market_cleanup(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mids = data.get("market_media_ids", [])
    for mid in mids:
        if mid == call.message.message_id: continue
        try:
            await call.message.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)
        except:
            pass
    await state.update_data(market_media_ids=None)
    await cb_sub_market(call)

@router.callback_query(F.data.startswith("cb_heatmap_sort:"))
async def cb_heatmap_sort(call: CallbackQuery):
    sort_by = call.data.split(":")[1]
    await call.answer(f"Sorting by {sort_by}...")
    
    lang = await db.get_lang(call.message.chat.id)
    ctx = await get_perps_context()
    universe = ctx[0].get("universe", [])
    asset_ctxs = ctx[1]
    
    from bot.analytics import generate_market_overview_image
    buf = generate_market_overview_image(asset_ctxs, universe, sort_by=sort_by)
    
    kb = InlineKeyboardBuilder()
    if sort_by != "vol": kb.button(text=_t(lang, "sort_vol"), callback_data="cb_heatmap_sort:vol")
    if sort_by != "funding": kb.button(text=_t(lang, "sort_funding"), callback_data="cb_heatmap_sort:funding")
    if sort_by != "oi": kb.button(text=_t(lang, "sort_oi"), callback_data="cb_heatmap_sort:oi")
    if sort_by != "change": kb.button(text=_t(lang, "sort_change"), callback_data="cb_heatmap_sort:change")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_market")
    kb.adjust(2, 2)
    
    if buf:
        photo = BufferedInputFile(buf.read(), filename="market_overview.png")
        await call.message.edit_media(
            media=InputMediaPhoto(media=photo, caption=f"📊 <b>Market Fundamentals ({sort_by.upper()})</b>", parse_mode="HTML"),
            reply_markup=kb.as_markup()
        )

@router.message(Command("set_vol"))
async def cmd_set_vol(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "set_vol_usage"), parse_mode="HTML")
        return
    try:
        val = float(args[1]) / 100.0 # User enters 2.5, we store 0.025
        await db.update_user_settings(message.chat.id, {"watch_alert_pct": val})
        await message.answer(_t(lang, "vol_set", val=val*100), parse_mode="HTML")
    except:
        await message.answer(_t(lang, "invalid_number"))

@router.callback_query(F.data.startswith("cb_pnl"))
async def cb_pnl(call: CallbackQuery):
    await call.answer("Loading...")
    
    parts = call.data.split(":")
    context = parts[1] if len(parts) > 1 else "portfolio"
    
    back_target = "sub:portfolio"
    if context == "trading":
        back_target = "sub:trading"
    elif context == "stats": # If we ever use stats specific context
        back_target = "cb_stats" # Return to stats?
        
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
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
                sym = await get_symbol_name(coin, is_spot=True)
                px = 0.0
                if ws: px = ws.get_price(sym, coin)
                if not px: px = await get_mid_price(sym, coin)
                
                val = amount * px
                w_spot_eq += val
                
                # uPnL for Spot (Approximate)
                entry = extract_avg_entry_from_balance(b)
                if not entry or entry <= 0:
                    # Fallback to stored fills in DB
                    try:
                        coin_fills = await db.get_fills_by_coin(wallet, coin)
                        from .services import calc_avg_entry_from_fills
                        entry = calc_avg_entry_from_fills(coin_fills)
                    except Exception:
                        entry = 0.0

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
                    sym = await get_symbol_name(coin_id, is_spot=False)
                    mark = 0.0
                    if ws: mark = ws.get_price(sym, coin_id)
                    if not mark: mark = await get_mid_price(sym, coin_id)
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
        card += f"\n   <b>{_t(lang, 'total_lbl')}: ${pretty_float(w_total, 2)}</b>"
        if w_spot_eq > 1:
            s_u_icon = "🟢" if w_spot_upnl >= 0 else "🔴"
            card += f"\n   {_t(lang, 'spot_bal')}: ${pretty_float(w_spot_eq, 2)} (uPnL: {s_u_icon}${pretty_float(w_spot_upnl, 2)})"
        if w_perps_eq > 1 or w_perps_upnl != 0:
            p_u_icon = "🟢" if w_perps_upnl >= 0 else "🔴"
            card += f"\n   {_t(lang, 'perps_bal')}: ${pretty_float(w_perps_eq, 2)} (uPnL: {p_u_icon}${pretty_float(w_perps_upnl, 2)})"
        
        if pnl_stats:
            card += pnl_stats
            
        wallet_cards.append(card)

    # Global Stats Card
    g_total = g_spot_eq + g_perps_eq
    g_upnl = g_spot_upnl + g_perps_upnl
    g_u_icon = "🟢" if g_upnl >= 0 else "🔴"
    
    header = f"{_t(lang, 'pnl_title')}\n\n"
    header += f"{_t(lang, 'net_worth')}: <b>${pretty_float(g_total, 2)}</b>\n"
    header += f"   {_t(lang, 'spot_bal')}: ${pretty_float(g_spot_eq, 2)}\n"
    header += f"   {_t(lang, 'perps_bal')}: ${pretty_float(g_perps_eq, 2)}\n"
    header += f"   {_t(lang, 'total_upnl')}: {g_u_icon} <b>${pretty_float(g_upnl, 2)}</b>"
    
    text = header + "\n\n" + "\n\n".join(wallet_cards)
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_graph"), callback_data="cb_pnl_graph")
    kb.button(text=_t(lang, "btn_back"), callback_data=back_target)
    kb.adjust(1)
    
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_pnl_graph")
async def cb_pnl_graph(call: CallbackQuery):
    await call.answer("Generating graph...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang))
        return
        
    # Aggregate history from all wallets
    aggregated_history = {} # {ts: total_equity}
    
    for wallet in wallets:
        portf = await get_user_portfolio(wallet)
        if not portf:
            continue

        history_data = []
        if isinstance(portf, list):
            target_data = {}
            for item in portf:
                if isinstance(item, list) and len(item) == 2:
                    period, p_data = item
                    if period == "allTime":
                        target_data = p_data
                        break
            
            if not target_data and portf and isinstance(portf[0], list) and len(portf[0]) == 2:
                 target_data = portf[0][1]
                 
            history_data = target_data.get("accountValueHistory", [])
        elif isinstance(portf, dict):
            data = portf.get("data", {})
            history_data = data.get("accountValueHistory", [])
            
        for ts, equity in history_data:
            # We use floor to nearest 5 min or hour if needed to align points, 
            # but usually HL returns same snapshots for all users if it's daily.
            # If timestamps differ slightly, we might need a better merge.
            # For now, let's assume they align or we just sum them as is.
            aggregated_history[ts] = aggregated_history.get(ts, 0.0) + float(equity)

    if not aggregated_history:
        await call.message.answer("📭 No history data for graph.")
        return
        
    # Sort and convert back to list of lists
    sorted_history = [[ts, val] for ts, val in sorted(aggregated_history.items())]
    
    label = "Total Portfolio" if len(wallets) > 1 else wallets[0]
        buf = generate_pnl_chart(history_list, "Total Portfolio")
        photo = BufferedInputFile(buf.read(), filename="pnl_chart.png")
        await smart_edit_media(call, photo, "📈 <b>Equity History & Drawdown</b>", reply_markup=_back_kb(lang, "cb_pnl"))
    except Exception as e:

# --- CALCULATOR ---

class CalcStates(StatesGroup):
    mode = State() # spot / perp
    side = State() # long / short
    balance = State()
    entry = State()
    sl = State()
    tp = State()
    risk = State()

class AlertStates(StatesGroup):
    waiting_for_symbol = State()
    waiting_for_target = State()

class SettingsStates(StatesGroup):
    waiting_for_prox = State()
    waiting_for_vol = State()
    waiting_for_whale = State()
    waiting_for_ov_time = State()
    waiting_for_ov_prompt = State()

class MarketAlertStates(StatesGroup):
    waiting_for_time = State()
    waiting_for_type = State()

class HedgeChatStates(StatesGroup):
    chatting = State()

@router.callback_query(F.data == "cb_market_alerts")
async def cb_market_alerts(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    user_settings = await db.get_user_settings(call.message.chat.id)
    alert_times = user_settings.get("market_alert_times", [])
    ts = time.strftime("%H:%M:%S")
    
    text = f"{_t(lang, 'market_alerts_title')}\n\n{_t(lang, 'market_alerts_msg')}\n\n"
    
    kb = InlineKeyboardBuilder()
    if not alert_times:
        text += f"<i>{_t(lang, 'no_market_alerts')}</i>"
    else:
        for t_entry in sorted(alert_times, key=lambda x: x["t"] if isinstance(x, dict) else x):
            if isinstance(t_entry, dict):
                t = t_entry["t"]
                is_repeat = t_entry.get("r", True)
            else:
                t = t_entry
                is_repeat = True
                
            repeat_label = "🔄" if is_repeat else "📍"
            text += f"{repeat_label} <b>{t} UTC</b>\n"
            kb.button(text=f"❌ {t}", callback_data=f"del_market_alert:{t}")
    
    kb.button(text=_t(lang, "btn_add_time"), callback_data="cb_add_market_alert_time")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    text += f"\n\n<i>{repeat_label if alert_times else ''} {_t(lang, 'daily')} | {_t(lang, 'once')}</i>\n<i>{_t(lang, 'last_update')}: {ts}</i>"
    
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except:
        pass

@router.callback_query(F.data == "cb_add_market_alert_time")
async def cb_add_market_alert_time(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(menu_msg_id=call.message.message_id)
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_market_alerts")
    
    await call.message.edit_text(_t(lang, "add_time_prompt"), reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(MarketAlertStates.waiting_for_time)
    await call.answer()

@router.message(MarketAlertStates.waiting_for_time)
async def process_market_alert_time(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    time_str = message.text.strip()
    
    try:
        parts = time_str.split(":")
        if len(parts) != 2: raise ValueError
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
        time_str = f"{h:02d}:{m:02d}"
    except ValueError:
        await message.answer(_t(lang, "invalid_time"))
        return

    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    await state.update_data(pending_time=time_str)
    
    # Cleanup user message
    try:
        await message.delete()
    except:
        pass
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 " + _t(lang, "daily"), callback_data="ma_type:daily")
    kb.button(text="📍 " + _t(lang, "once"), callback_data="ma_type:once")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_market_alerts")
    kb.adjust(1)
    
    text = f"⏰ Time: <b>{time_str} UTC</b>\n\nChoose frequency:"
    
    if msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(MarketAlertStates.waiting_for_type)
        except:
            await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
            await state.set_state(MarketAlertStates.waiting_for_type)
    else:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        await state.set_state(MarketAlertStates.waiting_for_type)

@router.callback_query(MarketAlertStates.waiting_for_type, F.data.startswith("ma_type:"))
async def process_market_alert_type(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    data = await state.get_data()
    time_str = data.get("pending_time")
    alert_type = call.data.split(":")[1]
    is_repeat = (alert_type == "daily")
    
    user_settings = await db.get_user_settings(call.message.chat.id)
    alert_times = user_settings.get("market_alert_times", [])
    
    # Remove existing for this time if any
    alert_times = [t for t in alert_times if (t["t"] if isinstance(t, dict) else t) != time_str]
    
    # Add new
    alert_times.append({"t": time_str, "r": is_repeat})
    await db.update_user_settings(call.message.chat.id, {"market_alert_times": alert_times})
    
    await state.clear()
    await call.answer(_t(lang, "market_alert_added").format(time=time_str))
    await cb_market_alerts(call)

@router.callback_query(F.data.startswith("del_market_alert:"))
async def cb_del_market_alert(call: CallbackQuery):
    time_str = call.data.split(":")[1]
    lang = await db.get_lang(call.message.chat.id)
    
    user_settings = await db.get_user_settings(call.message.chat.id)
    alert_times = user_settings.get("market_alert_times", [])
    
    # Handle both formats during deletion
    new_times = []
    found = False
    for t in alert_times:
        curr_t = t["t"] if isinstance(t, dict) else t
        if curr_t == time_str:
            found = True
            continue
        new_times.append(t)
    
    if found:
        await db.update_user_settings(call.message.chat.id, {"market_alert_times": new_times})
        await call.answer(_t(lang, "market_alert_removed").format(time=time_str))
    else:
        await call.answer("🗑️ Alert not found or already removed")
        
    await cb_market_alerts(call)

@router.callback_query(F.data == "cb_funding_alert_prompt")
async def cb_funding_alert_prompt(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(alert_type="funding", menu_msg_id=call.message.message_id)
    await call.message.edit_text(_t(lang, "prompt_symbol"), reply_markup=_back_kb(lang, "cb_settings"), parse_mode="HTML")
    await state.set_state(AlertStates.waiting_for_symbol)
    await call.answer()

@router.callback_query(F.data == "cb_oi_alert_prompt")
async def cb_oi_alert_prompt(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(alert_type="oi", menu_msg_id=call.message.message_id)
    await call.message.edit_text(_t(lang, "prompt_symbol"), reply_markup=_back_kb(lang, "cb_settings"), parse_mode="HTML")
    await state.set_state(AlertStates.waiting_for_symbol)
    await call.answer()

@router.message(AlertStates.waiting_for_symbol)
async def process_alert_symbol(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    symbol = message.text.strip().upper()
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    
    # Basic validation
    if len(symbol) > 10 or not symbol.isalnum():
        await message.answer(_t(lang, "watch_invalid"))
        return

    await state.update_data(symbol=symbol)
    a_type = data.get("alert_type")
    
    prompt = _t(lang, "prompt_target_funding") if a_type == "funding" else _t(lang, "prompt_target_oi")
    
    try: await message.delete()
    except: pass

    if msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=prompt,
                reply_markup=_back_kb(lang, "cb_settings"),
                parse_mode="HTML"
            )
        except:
            await message.answer(prompt, reply_markup=_back_kb(lang, "cb_settings"), parse_mode="HTML")
    else:
        await message.answer(prompt, reply_markup=_back_kb(lang, "cb_settings"), parse_mode="HTML")
        
    await state.set_state(AlertStates.waiting_for_target)

@router.message(AlertStates.waiting_for_target)
async def process_alert_target(message: Message, state: FSMContext):
    try: await message.delete()
    except: pass
    
    lang = await db.get_lang(message.chat.id)
    try:
        target = float(message.text.replace(",", "."))
    except:
        await message.answer(_t(lang, "invalid_number"))
        return
        
    data = await state.get_data()
    symbol = data.get("symbol")
    a_type = data.get("alert_type")
    msg_id = data.get("menu_msg_id")
    
    # Determine direction
    ctx = await get_perps_context()
    universe = ctx[0].get("universe", [])
    asset_ctxs = ctx[1]
    
    idx = next((i for i, u in enumerate(universe) if u["name"] == symbol), -1)
    current_val = 0.0
    
    if idx != -1 and idx < len(asset_ctxs):
        if a_type == "funding":
            current_val = float(asset_ctxs[idx].get("funding", 0)) * 24 * 365 * 100
        else:
            current_val = float(asset_ctxs[idx].get("openInterest", 0)) * float(asset_ctxs[idx].get("markPx", 0)) / 1e6
            
    direction = "above" if target > current_val else "below"
    await db.add_alert(message.chat.id, symbol, target, direction, a_type)
    
    dir_icon = "📈" if direction == "above" else "📉"
    success_msg = _t(lang, "funding_alert_set" if a_type == "funding" else "oi_alert_set", symbol=symbol, dir=dir_icon, val=target)
    
    try: await message.delete()
    except: pass

    if msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=success_msg,
                reply_markup=_settings_kb(lang),
                parse_mode="HTML"
            )
        except:
            await message.answer(success_msg, reply_markup=_settings_kb(lang), parse_mode="HTML")
    else:
        await message.answer(success_msg, reply_markup=_settings_kb(lang), parse_mode="HTML")
    
    await state.clear()

        await message.answer(success_msg, reply_markup=_settings_kb(lang), parse_mode="HTML")
        
    await state.clear()

@router.callback_query(F.data == "calc_start")
async def calc_start(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "calc_spot_btn"), callback_data="calc_mode:spot")
    kb.button(text=_t(lang, "calc_perp_btn"), callback_data="calc_mode:perp")
    kb.button(text=_t(lang, "calc_reverse"), callback_data="calc_mode:reverse")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:trading")
    kb.adjust(2, 1, 1)
    
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(_t(lang, "calc_mode"), reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(CalcStates.mode)

@router.callback_query(CalcStates.mode, F.data.startswith("calc_mode:"))
async def calc_set_mode(call: CallbackQuery, state: FSMContext):
    mode = call.data.split(":")[1]
    await state.update_data(mode=mode)
    lang = await db.get_lang(call.message.chat.id)
    kb = _back_kb(lang, "calc_start")
    
    if mode == "spot":
        await state.update_data(side="long")
        await call.message.edit_text(_t(lang, "calc_balance"), reply_markup=kb, parse_mode="HTML")
        await state.set_state(CalcStates.balance)
    elif mode == "reverse":
        await call.message.edit_text("🛡️ <b>Reverse Risk Calculator</b>\n\nEnter <b>Entry Price</b>:", reply_markup=kb, parse_mode="HTML")
        await state.set_state(CalcStates.entry)
    else:
        kb_side = InlineKeyboardBuilder()
        kb_side.button(text=_t(lang, "calc_long"), callback_data="calc_side:long")
        kb_side.button(text=_t(lang, "calc_short"), callback_data="calc_side:short")
        kb_side.button(text=_t(lang, "btn_back"), callback_data="calc_start")
        kb_side.adjust(2, 1)
        
        await call.message.edit_text(_t(lang, "calc_side_msg"), reply_markup=kb_side.as_markup(), parse_mode="HTML")
        await state.set_state(CalcStates.side)
    
    await call.answer()

@router.callback_query(CalcStates.side, F.data.startswith("calc_side:"))
async def calc_set_side(call: CallbackQuery, state: FSMContext):
    side = call.data.split(":")[1]
    await state.update_data(side=side)
    lang = await db.get_lang(call.message.chat.id)
    await call.message.edit_text(_t(lang, "calc_balance"), reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
    await state.set_state(CalcStates.balance)
    await call.answer()

@router.message(CalcStates.balance)
async def calc_set_balance(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(balance=val)
        prompt = _t(lang, "calc_entry")
        try: await message.delete()
        except: pass
        if msg_id:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        else:
            await message.answer(prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.entry)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.entry)
async def calc_set_entry(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(entry=val)
        prompt = _t(lang, "calc_sl")
        try: await message.delete()
        except: pass
        if msg_id:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        else:
            await message.answer(prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.sl)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.sl)
async def calc_set_sl(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(sl=val)
        
        prompt = _t(lang, "calc_tp")
        if data.get("mode") == "reverse":
            prompt = "💰 Enter <b>Risk Amount ($)</b> (e.g. 50):"
            
        try: await message.delete()
        except: pass
        
        if msg_id:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        else:
            await message.answer(prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.tp)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.tp)
async def calc_set_tp(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(tp=val)
        
        try: await message.delete()
        except: pass
        
        if data.get("mode") == "reverse":
            # Direct calculation for reverse mode here
            entry = float(data.get("entry", 0))
            sl = float(data.get("sl", 0))
            risk_amt = val
            
            if entry <= 0 or sl <= 0 or risk_amt <= 0 or entry == sl:
                await message.answer("❌ Invalid inputs. Entry != SL and > 0.")
                await state.clear()
                return
            
            dist_pct = abs(entry - sl) / entry
            size_usd = risk_amt / dist_pct
            side = "LONG" if entry > sl else "SHORT"
            
            res = (
                f"🛡️ <b>Risk Calculation Result</b>\n\n"
                f"Risk: <b>${risk_amt}</b>\n"
                f"Entry: ${entry}\n"
                f"Stop Loss: ${sl} ({side})\n"
                f"Distance: {dist_pct*100:.2f}%\n\n"
                f"👉 <b>Position Size: \${pretty_float(size_usd, 2)}</b>\n"
                f"(Qty: {size_usd/entry:.4f})"
            )
            kb = InlineKeyboardBuilder()
            kb.button(text=_t(lang, "btn_back"), callback_data="calc_start")
            
            if msg_id:
                try: await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=res, reply_markup=kb.as_markup(), parse_mode="HTML")
                except: await message.answer(res, reply_markup=kb.as_markup(), parse_mode="HTML")
            else:
                await message.answer(res, reply_markup=kb.as_markup(), parse_mode="HTML")
            await state.clear()
            return

        prompt = _t(lang, "calc_risk")
        if msg_id:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        else:
            await message.answer(prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.risk)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.risk)
async def calc_calculate(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    try:
        risk_val = float(message.text.replace(",", "."))
        await state.clear()
        
        mode = data.get("mode")
        balance = data.get("balance", 0)
        entry = data.get("entry", 0)
        sl = data.get("sl", 0)
        tp = data.get("tp", 0)
        side = data.get("side")
        
        if (side == "long" and sl >= entry) or (side == "short" and sl <= entry):
             await message.answer(_t(lang, "calc_side_wrong"), parse_mode="HTML")
             return
             
        risk_per_coin = abs(entry - sl)
        if risk_per_coin == 0:
            await message.answer(_t(lang, "calc_error"))
            return
            
        position_coins = risk_val / risk_per_coin
        position_usd = position_coins * entry
        fees = position_usd * 0.00035 * 2
        lev = position_usd / balance if balance > 0 else 1.0
            
        reward_per_coin = abs(tp - entry)
        rr = reward_per_coin / risk_per_coin if risk_per_coin else 0
        
        liq_px = 0
        if lev > 1:
            if side == "long": liq_px = entry * (1 - (1/lev) + 0.01)
            else: liq_px = entry * (1 + (1/lev) - 0.01)
        
        liq_warning = ""
        if lev > 1:
             if (side == "long" and liq_px > sl) or (side == "short" and liq_px < sl):
                 liq_warning = _t(lang, "calc_liq_warn")
        
        sl_pct = ((sl - entry) / entry) * 100
        tp_pct = ((tp - entry) / entry) * 100
        total_loss = risk_val + fees
        total_profit = (position_coins * reward_per_coin) - fees
        p50 = (total_profit / 2)
        
        lev_row = _t(lang, "calc_lev_lbl", lev=f"{lev:.1f}") if lev > 1 else ""
        liq_row = _t(lang, "calc_liq_lbl", liq=pretty_float(liq_px)) if liq_px > 0 else ""

        msg = _t(lang, "calc_result",
            side=side.upper(), mode="PERP" if lev > 1 else "SPOT", balance=pretty_float(balance),
            risk=pretty_float(risk_val), entry=pretty_float(entry), sl=pretty_float(sl),
            sl_pct=f"{sl_pct:+.2f}", tp=pretty_float(tp), tp_pct=f"{tp_pct:+.2f}",
            rr=f"{rr:.2f}", lev_row=lev_row, liq_row=liq_row,
            size_usd=pretty_float(position_usd), size_coins=pretty_float(position_coins, 4),
            fees=pretty_float(fees), total_loss=pretty_float(total_loss),
            total_profit=pretty_float(total_profit), p50=pretty_float(p50), p100=pretty_float(total_profit)
        ) + liq_warning
        
        try: await message.delete()
        except: pass
        
        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "btn_back"), callback_data="sub:trading")
        
        if msg_id:
            try: await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=msg, reply_markup=kb.as_markup(), parse_mode="HTML")
            except: await message.answer(msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await message.answer(msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

# --- INLINE MODE ---

@router.inline_query()
async def inline_query_handler(query: InlineQuery):
    query_text = query.query.strip().upper()
    
    if not query_text:
        return
    
    # Try to find price
    price = 0.0
    symbol = query_text
    
    # Check if we have access to WS for fast price
    ws = getattr(query.bot, "ws_manager", None)
    if ws:
        price = ws.get_price(symbol)
    
    if not price:
        price = await get_mid_price(symbol)
        
    if not price:
        return

    # Create result
    result_id = f"price_{symbol}_{time.time()}"
    
    title = f"{symbol}: ${pretty_float(price)}"
    description = "Click to send current price."
    
    input_content = InputTextMessageContent(
        message_text=f"💎 <b>{symbol}</b>\nPrice: <code>${pretty_float(price)}</code>",
        parse_mode="HTML"
    )
    
    item = InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=input_content
    )
    
    await query.answer([item], cache_time=5)

# --- NEW HANDLERS ---

@router.callback_query(F.data.startswith("cb_stats"))
async def cb_stats(call: CallbackQuery):
    # Parse context: cb_stats:context
    parts = call.data.split(":")
    context = parts[1] if len(parts) > 1 else "trading"
    
    back_target = "sub:trading"
    if context == "portfolio":
        back_target = "sub:portfolio"

    await call.answer("Calculating Stats...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
        return
        
    # Aggregate stats
    total_wins = 0
    total_loss = 0
    total_gp = 0.0
    total_gl = 0.0
    
    for wallet in wallets:
        fills = await get_user_fills(wallet)
        stats = calculate_trade_stats(fills)
        if stats:
            total_wins += stats["wins"]
            total_loss += stats["losses"]
            total_gp += stats["gross_profit"]
            total_gl += stats["gross_loss"]
            
    total_trades = total_wins + total_loss
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
    pf = (total_gp / total_gl) if total_gl > 0 else (999.0 if total_gp > 0 else 0)
    net_pnl = total_gp - total_gl
    
    text = f"{_t(lang, 'stats_title')}\n\n"
    text += f"{_t(lang, 'stats_trades')}: <b>{total_trades}</b>\n"
    text += f"{_t(lang, 'stats_winrate')}: <b>{win_rate:.1f}%</b>\n"
    text += f"{_t(lang, 'stats_pf')}: <b>{pf:.2f}</b>\n\n"
    text += f"{_t(lang, 'gross_profit')}: 🟢 <b>${pretty_float(total_gp, 2)}</b>\n"
    text += f"{_t(lang, 'gross_loss')}: 🔴 <b>${pretty_float(total_gl, 2)}</b>\n"
    
    icon = "🟢" if net_pnl >= 0 else "🔴"
    text += f"\n{_t(lang, 'net_pnl')}: {icon} <b>${pretty_float(net_pnl, 2)}</b>"
    
    # Check PnL History for graph
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_pnl"), callback_data=f"cb_pnl:{context}")
    kb.button(text=_t(lang, "btn_back"), callback_data=back_target)
    kb.adjust(1)
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "cb_whales")
async def cb_whales(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    user_settings = await db.get_user_settings(call.message.chat.id)
    
    is_on = user_settings.get("whale_alerts", False)
    threshold = user_settings.get("whale_threshold", 50_000)
    wl_only = user_settings.get("whale_watchlist_only", False)
    
    status = _t(lang, "whale_alerts_on") if is_on else _t(lang, "whale_alerts_off")
    wl_status = f"👁️ Watchlist Only: ON" if wl_only else _t(lang, "whales_all_assets")
    
    text = f"{_t(lang, 'whales_title')}\n\n"
    text += _t(lang, "whale_intro") + "\n\n"
    text += f"{status}\n"
    text += f"{wl_status}\n"
    text += f"{_t(lang, 'min_val')}: <b>${pretty_float(threshold, 0)}</b>"
    
    kb = InlineKeyboardBuilder()
    
    toggle_txt = _t(lang, "disable") if is_on else _t(lang, "enable")
    kb.button(text=toggle_txt, callback_data=f"toggle_whales:{'off' if is_on else 'on'}")
    
    wl_toggle_txt = "🔔 Show All Assets" if wl_only else "👁️ Watchlist Only"
    kb.button(text=wl_toggle_txt, callback_data=f"toggle_whale_wl:{'off' if wl_only else 'on'}")
    
    kb.button(text="✏️ Threshold", callback_data="set_whale_thr_prompt")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("toggle_whale_wl:"))
async def cb_toggle_whale_wl(call: CallbackQuery):
    action = call.data.split(":")[1]
    is_on = (action == "on")
    await db.update_user_settings(call.message.chat.id, {"whale_watchlist_only": is_on})
    await cb_whales(call)

@router.callback_query(F.data.startswith("toggle_whales:"))
async def cb_toggle_whales(call: CallbackQuery):
    action = call.data.split(":")[1]
    is_on = (action == "on")
    await db.update_user_settings(call.message.chat.id, {"whale_alerts": is_on})
    await cb_whales(call)

@router.callback_query(F.data == "cb_fear_greed")
async def cb_fear_greed(call: CallbackQuery):
    """Display Fear & Greed Index from Alternative.me"""
    lang = await db.get_lang(call.message.chat.id)
    
    from bot.services import get_fear_greed_index
    fng = await get_fear_greed_index()
    
    if not fng:
        await smart_edit(call, "❌ Unable to fetch Fear & Greed data.", reply_markup=_back_kb(lang, "sub:market"))
        await call.answer()
        return
    
    value = fng["value"]
    classification = fng["classification"]
    change = fng["change"]
    emoji = fng["emoji"]
    
    # Visual gauge bar
    filled = int(value / 5)  # 0-20 bars
    gauge = "█" * filled + "░" * (20 - filled)
    
    # Change arrow
    if change > 0:
        change_icon = "📈"
    elif change < 0:
        change_icon = "📉"
    else:
        change_icon = "➖"
    
    text = f"{_t(lang, 'fng_title')}\n\n"
    text += f"{emoji} <b>{value}</b> — {classification}\n\n"
    text += f"<code>[{gauge}]</code>\n"
    text += f"<code>0   Fear         Greed   100</code>\n\n"
    text += f"{change_icon} {_t(lang, 'fng_change', change=change)}\n\n"
    text += f"<i>Source: Alternative.me Crypto Fear & Greed Index</i>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 " + _t(lang, "btn_refresh"), callback_data="cb_fear_greed")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    # Try to edit if message exists (Refresh logic)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        # If content identical or can't edit (e.g. was a photo), fallback to smart_edit which handles deletion
        if "message is not modified" not in str(Exception):
             await smart_edit(call, text, reply_markup=kb.as_markup())
             
    await call.answer()

@router.callback_query(F.data == "set_whale_thr_prompt")
async def cb_set_whale_thr_prompt(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.answer(_t(lang, "whale_input"), parse_mode="HTML")
    await call.answer()

@router.message(Command("set_whale"))
async def cmd_set_whale(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "set_whale_usage"), parse_mode="HTML")
        return
    try:
        val = float(args[1])
        await db.update_user_settings(message.chat.id, {"whale_threshold": val})
        await message.answer(_t(lang, "whale_set", val=pretty_float(val)), parse_mode="HTML")
    except:
        await message.answer(_t(lang, "invalid_number"))

@router.callback_query(F.data == "set_prox_prompt")
async def cb_set_prox_prompt(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(_t(lang, "prox_input"), reply_markup=_back_kb(lang, "cb_settings"), parse_mode="HTML")
    await state.set_state(SettingsStates.waiting_for_prox)
    await call.answer()

@router.callback_query(F.data == "set_vol_prompt")
async def cb_set_vol_prompt(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(_t(lang, "vol_input"), reply_markup=_back_kb(lang, "cb_settings"), parse_mode="HTML")
    await state.set_state(SettingsStates.waiting_for_vol)
    await call.answer()

@router.callback_query(F.data == "set_whale_prompt")
async def cb_set_whale_prompt(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(menu_msg_id=call.message.message_id)
    await call.message.edit_text(_t(lang, "whale_input"), reply_markup=_back_kb(lang, "cb_settings"), parse_mode="HTML")
    await state.set_state(SettingsStates.waiting_for_whale)
    await call.answer()

@router.message(SettingsStates.waiting_for_prox)
async def process_set_prox_state(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    
    res_text = ""
    try:
        val = float(message.text.replace(",", ".")) / 100.0
        await db.update_user_settings(message.chat.id, {"prox_alert_pct": val})
        res_text = "✅ " + _t(lang, "prox_set", val=val*100)
    except:
        res_text = "❌ " + _t(lang, "invalid_number")
    
    await state.clear()
    try: await message.delete()
    except: pass
    
    final_text = f"{res_text}\n\n{_t(lang, 'settings_title')}"
    if msg_id:
        try: await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")
        except: await message.answer(final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")
    else:
        await message.answer(final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")

@router.message(SettingsStates.waiting_for_vol)
async def process_set_vol_state(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    
    res_text = ""
    try:
        val = float(message.text.replace(",", ".")) / 100.0
        await db.update_user_settings(message.chat.id, {"watch_alert_pct": val})
        res_text = "✅ " + _t(lang, "vol_set", val=val*100)
    except:
        res_text = "❌ " + _t(lang, "invalid_number")
    
    await state.clear()
    try: await message.delete()
    except: pass
    
    final_text = f"{res_text}\n\n{_t(lang, 'settings_title')}"
    if msg_id:
        try: await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")
        except: await message.answer(final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")
    else:
        await message.answer(final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")

@router.message(SettingsStates.waiting_for_whale)
async def process_set_whale_state(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    msg_id = data.get("menu_msg_id")
    
    res_text = ""
    try:
        val = float(message.text.replace(",", "."))
        await db.update_user_settings(message.chat.id, {"whale_threshold": val})
        res_text = "✅ " + _t(lang, "whale_set", val=pretty_float(val))
    except:
        res_text = "❌ " + _t(lang, "invalid_number")
    
    await state.clear()
    try: await message.delete()
    except: pass
    
    final_text = f"{res_text}\n\n{_t(lang, 'settings_title')}"
    if msg_id:
        try: await message.bot.edit_message_text(chat_id=message.chat.id, message_id=msg_id, text=final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")
        except: await message.answer(final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")
    else:
        await message.answer(final_text, reply_markup=_settings_kb(lang), parse_mode="HTML")

@router.message(SettingsStates.waiting_for_ov_time)
async def process_ov_time(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    t_str = message.text.strip()
    
    # Validate HH:MM
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
    
    if text.lower() == "clear":
        cfg["prompt_override"] = None
    else:
        cfg["prompt_override"] = text
        
    await db.update_overview_settings(message.from_user.id, cfg)
    
    await state.clear()
    await message.answer(_t(lang, "ov_prompt_set"))
    await cmd_overview_settings(message)

@router.message(Command("set_prox"))
async def cmd_set_prox(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "set_prox_usage"), parse_mode="HTML")
        return
    try:
        val = float(args[1]) / 100.0 # User enters 0.5, we store 0.005
        await db.update_user_settings(message.chat.id, {"prox_alert_pct": val})
        await message.answer(_t(lang, "prox_set", val=val*100), parse_mode="HTML")
    except:
        await message.answer(_t(lang, "invalid_number"))

@router.callback_query(F.data == "cb_flex_menu")
async def cb_flex_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    
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
    period = call.data.split(":")[1]
    await call.answer("Generating...")
    
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    
    if not wallets:
        await call.message.answer(_t(lang, "need_wallet"))
        return

    # Labels for the card
    period_labels = {
        "day": _t(lang, "flex_period_day"),
        "week": _t(lang, "flex_period_week"),
        "month": _t(lang, "flex_period_month"),
        "all": _t(lang, "flex_period_all")
    }
    period_label = period_labels.get(period, "Period")
    
    wallet_label = "Portfolio"
    if len(wallets) == 1:
        w = wallets[0]
        wallet_label = f"{w[:6]}...{w[-4:]}"
    elif len(wallets) > 1:
        wallet_label = f"{len(wallets)} Wallets"

    # Calculate global PnL for the period
    total_period_pnl = 0.0
    total_start_equity = 0.0
    
    has_data = False
    
    now_ms = time.time() * 1000
    delta_ms = 0
    if period == "day": delta_ms = 86400000
    elif period == "week": delta_ms = 86400000 * 7
    elif period == "month": delta_ms = 86400000 * 30
    elif period == "all": delta_ms = 9999999999999
    
    target_time = now_ms - delta_ms
    
    for wallet in wallets:
        portf = await get_user_portfolio(wallet)
        if not portf: continue
        
        # Extract history
        equity_hist = []
        pnl_hist = []
        
        target_data = {}
        if isinstance(portf, list):
            # Try to find "allTime" or "month"
            for item in portf:
                if isinstance(item, list) and len(item) == 2:
                    p_name, p_data = item
                    if p_name == "allTime":
                        target_data = p_data
                        break
            if not target_data and portf and isinstance(portf[0], list):
                 target_data = portf[0][1]
                 
        elif isinstance(portf, dict):
             target_data = portf.get("data", {})
             
        equity_hist = target_data.get("accountValueHistory", [])
        pnl_hist = target_data.get("pnlHistory", [])
             
        if not equity_hist or not pnl_hist: continue
        
        # Sort
        equity_hist.sort(key=lambda x: x[0])
        pnl_hist.sort(key=lambda x: x[0])
        
        # 1. Get Start Point (closest to target_time)
        # Note: pnl_hist and equity_hist might have different lengths/timestamps, 
        # but usually they align or are close enough.
        
        # Find index in pnl_hist
        if period == "all":
            p_start = 0.0 # For all-time, we start from zero profit
            # Initial equity base: first recorded equity minus its cumulative pnl
            e_0 = float(equity_hist[0][1])
            p_0 = float(pnl_hist[0][1])
            e_start = e_0 - p_0
            if e_start <= 0: e_start = e_0 # Fallback if initial was zero
        else:
            # PnL Start
            closest_p = min(pnl_hist, key=lambda x: abs(x[0] - target_time))
            p_start = float(closest_p[1])
            
            # Equity Start (at the same time as PnL Start)
            t_ref = closest_p[0]
            closest_eq = min(equity_hist, key=lambda x: abs(x[0] - t_ref))
            e_start = float(closest_eq[1])
            
        # 2. Get End Point (Current)
        p_end = float(pnl_hist[-1][1])
        e_end = float(equity_hist[-1][1])
        
        # 3. Calculate Wallet PnL (Trade-only)
        w_pnl = p_end - p_start
        
        # 4. Determine base for percentage
        if period == "all":
            # For all-time ROI, base should be total net deposits
            # Total Net Deposits = Current Equity - Current Cumulative PnL
            w_base = e_end - p_end
        else:
            w_base = e_start
            
        total_period_pnl += w_pnl
        total_start_equity += max(0, w_base)
        has_data = True
        
    if not has_data:
        await call.message.answer("❌ Not enough history data.")
        return
        
    pnl_val = total_period_pnl
    # Avoid div by zero
    pnl_pct = 0.0
    if total_start_equity > 0:
        pnl_pct = (pnl_val / total_start_equity) * 100
    elif pnl_val > 0:
        pnl_pct = 100.0
    
    is_positive = pnl_val >= 0
    
    # Generate for the first wallet for now (or loop/select)
    from bot.analytics import prepare_account_flex_data
    from bot.renderer import render_html_to_image
    
    flex_data = prepare_account_flex_data(pnl_val, pnl_pct, period_label, is_positive, wallet_label)
    
    try:
        buf = await render_html_to_image("account_flex.html", flex_data)
        photo = BufferedInputFile(buf.read(), filename="equity_flex.png")
        await smart_edit_media(call, photo, f"📊 <b>{period_label} Account Summary</b>", reply_markup=_back_kb(lang, "cb_flex_menu"))
    except Exception as e:
        logger.error(f"Error rendering account flex: {e}")
        await call.message.answer("❌ Error generating image.")

@router.callback_query(F.data == "cb_terminal")
async def cb_terminal(call: CallbackQuery):
    await call.answer("Loading Terminal...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.answer("No wallet tracked.")
        return

    ws = getattr(call.message.bot, "ws_manager", None)
    
    total_equity = 0.0
    total_upnl = 0.0
    total_margin_used = 0.0
    total_withdrawable = 0.0
    total_ntl = 0.0
    
    combined_assets = [] 
    combined_positions = [] 
    
    for wallet in wallets:
        spot_bals = await get_spot_balances(wallet)
        perps_state = await get_perps_state(wallet)
        
        if spot_bals:
            for b in spot_bals:
                coin_id = b.get("coin")
                name = await get_symbol_name(coin_id, is_spot=True)
                amount = float(b.get("total", 0) or 0)
                if amount <= 0: continue
                
                px = 0.0
                if ws: px = ws.get_price(name, coin_id)
                if not px: px = await get_mid_price(name, coin_id)
                
                val = amount * px
                total_equity += val
                
                entry = extract_avg_entry_from_balance(b)
                if not entry or entry <= 0:
                    try:
                        coin_fills = await db.get_fills_by_coin(wallet, coin_id)
                        from bot.services import calc_avg_entry_from_fills
                        entry = calc_avg_entry_from_fills(coin_fills)
                    except:
                        entry = 0.0
                
                if entry > 0 and px > 0:
                    spot_pnl = (px - entry) * amount
                    total_upnl += spot_pnl
                    
                    roi = ((px / entry) - 1) * 100
                    combined_positions.append({
                        "symbol": name,
                        "side": "SPOT",
                        "leverage": "SPOT",
                        "size_usd": abs(val),
                        "entry": entry,
                        "mark": px,
                        "liq": 0.0,
                        "pnl": spot_pnl,
                        "roi": roi
                    })

                if val > 5:
                    combined_assets.append({"name": name, "value": val})

        if perps_state:
             if "marginSummary" in perps_state:
                 ms = perps_state["marginSummary"]
                 p_eq = float(ms.get("accountValue", 0) or 0)
                 m_used = float(ms.get("totalMarginUsed", 0) or 0)
                 ntl = float(ms.get("totalNtlPos", 0) or 0)
                 
                 total_equity += p_eq
                 total_margin_used += m_used
                 total_ntl += ntl
                 
             total_withdrawable += float(perps_state.get("withdrawable", 0) or 0)
             
             for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {})
                szi = float(pos.get("szi", 0))
                if szi == 0: continue
                
                coin_id = pos.get("coin")
                sym = await get_symbol_name(coin_id, is_spot=False)
                entry = float(pos.get("entryPx", 0))
                leverage = float(pos.get("leverage", {}).get("value", 0))
                liq = float(pos.get("liquidationPx", 0) or 0)
                
                mark = 0.0
                if ws: mark = ws.get_price(sym, coin_id)
                if not mark: mark = await get_mid_price(sym, coin_id)
                
                pnl = (mark - entry) * szi if mark else 0.0
                total_upnl += pnl
                
                roi = 0.0
                if leverage and szi and entry:
                     roi = (pnl / (abs(szi) * entry / leverage)) * 100
                     
                combined_positions.append({
                    "symbol": sym,
                    "side": "LONG" if szi > 0 else "SHORT",
                    "leverage": leverage,
                    "size_usd": abs(szi * mark),
                    "entry": entry,
                    "mark": mark,
                    "liq": liq,
                    "pnl": pnl,
                    "roi": roi
                })

    margin_pct = (total_margin_used / total_equity * 100) if total_equity > 0 else 0.0
    effective_leverage = (total_ntl / total_equity) if total_equity > 0 else 0.0
    
    wallet_label = wallets[0] if len(wallets) == 1 else "Total Portfolio"
    
    data = prepare_terminal_dashboard_data_clean(
        wallet_label=wallet_label if len(wallets) > 1 else "Personal Wallet",
        wallet_address=wallets[0],
        total_equity=total_equity,
        upnl=total_upnl,
        margin_usage=margin_pct,
        leverage=effective_leverage,
        withdrawable=total_withdrawable,
        assets=combined_assets,
        positions=combined_positions
    )
    
    try:
        buf = await render_html_to_image("terminal_dashboard.html", data, width=1000, height=600)
        photo = BufferedInputFile(buf.read(), filename="terminal.png")
        
        caption = "🖥️ <b>Velox Terminal</b>"
        if len(wallets) > 1: caption += f" ({len(wallets)} wallets)"
        
        await smart_edit_media(call, photo, caption, reply_markup=_main_menu_kb(lang))
    except Exception as e:
        logger.error(f"Error rendering terminal: {e}")
        await call.message.answer("❌ Error generating terminal.")

@router.callback_query(F.data == "cb_positions_img")
async def cb_positions_img(call: CallbackQuery):
    await call.answer("Generating Table...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets: return

    ws = getattr(call.message.bot, "ws_manager", None)
    combined_positions = []
    
    for wallet in wallets:
        state = await get_perps_state(wallet)
        spot_bals = await get_spot_balances(wallet)
        
        if state:
            positions = state.get("assetPositions", [])
            for p in positions:
                pos = p.get("position", {})
                szi = float(pos.get("szi", 0))
                if szi == 0: continue
                
                coin_id = pos.get("coin")
                sym = await get_symbol_name(coin_id, is_spot=False)
                entry = float(pos.get("entryPx", 0))
                leverage = float(pos.get("leverage", {}).get("value", 0))
                liq = float(pos.get("liquidationPx", 0) or 0)
                
                mark = 0.0
                if ws: mark = ws.get_price(sym, coin_id)
                if not mark: mark = await get_mid_price(sym, coin_id)
                
                pnl = (mark - entry) * szi if mark else 0.0
                roi = 0.0
                if leverage and szi and entry:
                     roi = (pnl / (abs(szi) * entry / leverage)) * 100
                     
                combined_positions.append({
                    "symbol": sym,
                    "side": "LONG" if szi > 0 else "SHORT",
                    "leverage": leverage,
                    "size_usd": abs(szi * mark),
                    "entry": entry,
                    "mark": mark,
                    "liq": liq,
                    "pnl": pnl,
                    "roi": roi
                })

        if spot_bals:
            for b in spot_bals:
                coin_id = b.get("coin")
                if coin_id == "USDC": continue
                
                amount = float(b.get("total", 0) or 0)
                sym = await get_symbol_name(coin_id, is_spot=True)
                
                px = 0.0
                if ws: px = ws.get_price(sym, coin_id)
                if not px: px = await get_mid_price(sym, coin_id)
                
                if amount * px < 5: continue
                
                entry = extract_avg_entry_from_balance(b)
                if not entry or entry <= 0:
                    try:
                        coin_fills = await db.get_fills_by_coin(wallet, coin_id)
                        from bot.services import calc_avg_entry_from_fills
                        entry = calc_avg_entry_from_fills(coin_fills)
                    except:
                        entry = 0.0
                
                upnl = 0.0
                roi = 0.0
                if entry > 0 and px > 0:
                    upnl = (px - entry) * amount
                    roi = ((px / entry) - 1) * 100
                
                combined_positions.append({
                    "symbol": sym,
                    "side": "SPOT",
                    "leverage": "SPOT",
                    "size_usd": abs(amount * px),
                    "entry": entry,
                    "mark": px,
                    "liq": 0.0,
                    "pnl": upnl,
                    "roi": roi
                })

    data = prepare_positions_table_data(
        wallet_label=wallets[0] if len(wallets) == 1 else "Total Portfolio",
        positions=combined_positions
    )
    
    try:
        h = 150 + (len(combined_positions) * 55)
        h = max(400, min(h, 2000))
        
        buf = await render_html_to_image("positions_table.html", data, width=800, height=h)
        photo = BufferedInputFile(buf.read(), filename="positions.png")
        
        await smart_edit_media(call, photo, "📸 <b>Active Positions</b>", reply_markup=_back_kb(lang, "sub:trading"))
    except Exception as e:
        logger.error(f"Error rendering table: {e}")
        await call.message.answer("❌ Error generating table.")

@router.callback_query(F.data == "cb_fills")
async def cb_fills(call: CallbackQuery):
    await call.answer("Fetching history...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.answer(_t(lang, "need_wallet"))
        return

    lines = []
    lines.append(f"📜 <b>Recent Trades (Last 10)</b>")
    
    all_fills = []
    for wallet in wallets:
        fills = await get_user_fills(wallet)
        for f in fills: 
            f['wallet'] = wallet
        all_fills.extend(fills)
        
    all_fills.sort(key=lambda x: x.get("time", 0), reverse=True)
    
    for f in all_fills[:10]:
        coin = f.get("coin", "???")
        if coin.startswith("@"):
             try: coin = await get_symbol_name(coin, is_spot=True)
             except: pass
        
        side = f.get("side", "")
        if f.get("dir"): 
             side = f.get("dir")
             
        px = float(f.get("px", 0))
        sz = float(f.get("sz", 0))
        val = px * sz
        pnl = float(f.get("closedPnl", 0) or 0)
        
        ts = f.get("time", 0)
        dt = datetime.datetime.fromtimestamp(ts/1000).strftime("%H:%M")
        
        icon = "🟢" if side == "B" else "🔴"
        side_text = _t(lang, "hist_buy") if side == "B" else _t(lang, "hist_sell")
        
        pnl_str = ""
        if pnl != 0:
            pnl_str = f" | PnL: {'+' if pnl>0 else ''}{pretty_float(pnl, 2)}"
            
        lines.append(
            f"{icon} <b>{coin}</b> {side_text} ${pretty_float(px)}\n"
            f"   <i>{dt} | Sz: {sz} (${pretty_float(val, 0)}){pnl_str}</i>"
        )
        
    if not all_fills:
        lines.append("\n<i>No recent trades found.</i>")
        
    await smart_edit(call, "\n".join(lines), reply_markup=_back_kb(lang, "sub:trading"))

@router.callback_query(F.data == "cb_risk_check")
async def cb_risk_check(call: CallbackQuery):
    await call.answer("Scanning for risks...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets: return

    ws = getattr(call.message.bot, "ws_manager", None)
    risky_positions = []
    
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        
        if "marginSummary" in state:
            ms = state["marginSummary"]
            m_used = float(ms.get("totalMarginUsed", 0))
            eq = float(ms.get("accountValue", 0))
            if eq > 0:
                util = (m_used / eq) * 100
                if util > 70:
                    risky_positions.append(f"⚠️ <b>Wallet {wallet[:6]}...</b> Margin Usage: {util:.1f}%")

        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            szi = float(pos.get("szi", 0))
            if szi == 0: continue
            
            coin_id = pos.get("coin")
            sym = await get_symbol_name(coin_id, is_spot=False)
            liq = float(pos.get("liquidationPx", 0) or 0)
            
            if liq <= 0: continue
            
            mark = 0.0
            if ws: mark = ws.get_price(sym, coin_id)
            if not mark: mark = await get_mid_price(sym, coin_id)
            
            if mark > 0:
                dist_pct = abs(mark - liq) / mark * 100
                if dist_pct < 10:
                    side = "LONG" if szi > 0 else "SHORT"
                    risky_positions.append(
                        f"🚨 <b>{sym}</b> {side} [{wallet[:4]}..]\n"
                        f"   Price: {pretty_float(mark)} | Liq: {pretty_float(liq)}\n"
                        f"   Buffer: <b>{dist_pct:.2f}%</b>"
                    )

    if not risky_positions:
        await smart_edit(call, _t(lang, "risk_healthy"), reply_markup=_back_kb(lang, "sub:trading"))
    else:
        text = _t(lang, "risk_warning") + "\n\n" + "\n\n".join(risky_positions)
        await smart_edit(call, text, reply_markup=_back_kb(lang, "sub:trading"))

@router.callback_query(F.data == "cb_manual_digest")
async def cb_manual_digest(call: CallbackQuery):
    await call.answer("Generating Digest...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.answer("No wallet tracked.")
        return
        
    wallet = wallets[0]
    portf = await get_user_portfolio(wallet)
    if not portf or not isinstance(portf, dict):
        await call.message.answer("No data available.")
        return
        
    data = portf.get("data", {})
    history = data.get("accountValueHistory", [])
    if not history:
        await call.message.answer("No history available.")
        return
    
    history.sort(key=lambda x: x[0])
    current_val = float(history[-1][1])
    target_ms = history[-1][0] - 86400000
    
    closest = min(history, key=lambda x: abs(x[0] - target_ms))
    start_val = float(closest[1])
        
    diff = current_val - start_val
    pct = (diff / start_val) * 100 if start_val > 0 else 0.0
    icon = "🟢" if diff >= 0 else "🔴"
    
    msg = (
        f"☀️ <b>Daily Digest (Preview)</b>\n"
        f"Wallet: <code>{wallet[:6]}...{wallet[-4:]}</code>\n\n"
        f"💰 Equity: <b>${pretty_float(current_val, 2)}</b>\n"
        f"📅 24h Change: {icon} <b>${pretty_float(diff, 2)}</b> ({pct:+.2f}%)"
    )
    sent_msg = await call.message.answer(msg, parse_mode="HTML")
    
    # Fire Hedge Insight
    ws = getattr(call.message.bot, "ws_manager", None)
    if ws and sent_msg:
        await ws.fire_hedge_insight(call.message.chat.id, call.from_user.id, "chat", {
            "digest_type": "manual_preview",
            "diff": diff,
            "pct": pct
        }, reply_to_id=sent_msg.message_id)

# --- MARKET OVERVIEW ---

async def _fetch_market_snapshot():
    ctx = await get_perps_context()
    # ctx[0] is universe, ctx[1] is asset_ctxs
    # Return full context for detailed processing
    return ctx

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
        for sym in ["BTC", "ETH"]:
            idx = next((i for i, u in enumerate(universe) if u.get("name") == sym), -1)
            if idx != -1 and idx < len(asset_ctxs):
                ac = asset_ctxs[idx]
                p = float(ac.get("markPx", 0))
                prev = float(ac.get("prevDayPx", 0) or p)
                change = ((p - prev)/prev)*100 if prev else 0
                market_data[sym] = {"price": pretty_float(p), "change": round(change, 2)}
            else:
                market_data[sym] = {"price": "0", "change": 0.0}

        # Flow data (legacy support for prompt, but zeroed out visually)
        market_data["btc_etf_flow"] = 0
        market_data["eth_etf_flow"] = 0

        # --- Calculate Top Movers for Image ---
        # Sort by Change %
        def get_change(idx):
            if idx >= len(asset_ctxs): return 0
            ac = asset_ctxs[idx]
            p = float(ac.get("markPx", 0))
            prev = float(ac.get("prevDayPx", 0) or p)
            return ((p - prev)/prev)*100 if prev else 0

        mover_indices = [(i, get_change(i)) for i in range(len(universe))]
        mover_indices.sort(key=lambda x: x[1], reverse=True)
        
        top_gainer = universe[mover_indices[0][0]]["name"]
        top_gainer_pct = mover_indices[0][1]
        
        top_loser = universe[mover_indices[-1][0]]["name"]
        top_loser_pct = mover_indices[-1][1]
        
        # Sort by Volume
        vol_indices = [(i, float(asset_ctxs[i].get("dayNtlVlm", 0))) for i in range(len(universe)) if i < len(asset_ctxs)]
        vol_indices.sort(key=lambda x: x[1], reverse=True)
        top_vol = universe[vol_indices[0][0]]["name"]
        top_vol_val = vol_indices[0][1]
        
        # Sort by Funding
        fund_indices = [(i, float(asset_ctxs[i].get("funding", 0))) for i in range(len(universe)) if i < len(asset_ctxs)]
        fund_indices.sort(key=lambda x: x[1], reverse=True)
        top_fund = universe[fund_indices[0][0]]["name"]
        top_fund_val = fund_indices[0][1] * 100 * 24 * 365 # APR

        user_config = await db.get_overview_settings(user_id)
        
        # AI Generation
        ai_data = await market_overview.generate_summary(
            market_data, 
            news, 
            "INTELLIGENCE",
            custom_prompt=user_config.get("prompt_override"),
            style=user_config.get("style", "detailed"),
            lang=lang
        )
        
        if not isinstance(ai_data, dict):
             ai_data = {"summary": str(ai_data), "sentiment": "Neutral", "next_event": "N/A"}

        summary_text = ai_data.get("summary", "No summary available.")
        sentiment = ai_data.get("sentiment", "Neutral")

        # Global Volatility Proxy (Average Absolute Change of Top 50 Vol Coins)
        # Or just use the Fear & Greed as is, and replace Next Event with "Market Vitality"
        
        render_data = {
            "period_label": "INTELLIGENCE",
            "date": datetime.datetime.now().strftime("%d %b %H:%M"),
            "btc": market_data["BTC"],
            "eth": market_data["ETH"],
            "sentiment": sentiment,
            "fng": fng if fng and not isinstance(fng, Exception) else {"value": 0, "classification": "N/A"},
            "gemini_model": "3 Flash Preview",
            
            # New Data Fields
            "top_gainer": {"sym": top_gainer, "val": top_gainer_pct},
            "top_loser": {"sym": top_loser, "val": top_loser_pct},
            "top_vol": {"sym": top_vol, "val": f"${top_vol_val/1e6:.0f}M"},
            "top_fund": {"sym": top_fund, "val": f"{top_fund_val:.0f}%"}
        }
        
        img_buf = await render_html_to_image("market_overview.html", render_data, width=1000, height=1000)
        
        # Header for Image Caption
        btc_d = market_data.get("BTC", {})
        eth_d = market_data.get("ETH", {})
        btc_c = btc_d.get("change", 0.0)
        eth_c = eth_d.get("change", 0.0)
        btc_icon = "🟢" if btc_c >= 0 else "🔴"
        eth_icon = "🟢" if eth_c >= 0 else "🔴"
        
        header = (
            f"<b>BTC: ${btc_d.get('price', '0')} ({btc_icon} {btc_c:+.2f}%)</b>\n"
            f"<b>ETH: ${eth_d.get('price', '0')} ({eth_icon} {eth_c:+.2f}%)</b>"
        )
        
        # Send Image
        img_msg = await bot.send_photo(
             chat_id=chat_id,
             photo=BufferedInputFile(img_buf.read(), filename="overview.png"),
             caption=f"{header}\n\n<b>VELOX AI</b>",
             parse_mode="HTML"
        )
        
        # Prepare Text Report
        report_text = html.escape(summary_text)
        report_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', report_text)
        report_text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', report_text)
        
        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "btn_refresh"), callback_data="cb_market_overview_refresh")
        kb.button(text=_t(lang, "btn_settings"), callback_data="cb_overview_settings_menu")
        kb.button(text=_t(lang, "btn_back"), callback_data="cb_ai_cleanup")
        kb.adjust(1, 2)

        txt_msg = await bot.send_message(
            chat_id=chat_id,
            text=report_text,
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )
        
        # Store message IDs for cleanup
        state = FSMContext(
            storage=bot.fsm.storage,
            key=bot.fsm.resolve_context_key(chat_id, user_id)
        )
        await state.update_data(ai_overview_msg_ids=[img_msg.message_id, txt_msg.message_id])
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Overview error: {e}", exc_info=True)
        if status_msg:
            await status_msg.edit_text("❌ Failed to generate overview.")

@router.callback_query(F.data == "cb_ai_cleanup")
async def cb_ai_cleanup(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mids = data.get("ai_overview_msg_ids", [])
    for mid in mids:
        if mid == call.message.message_id: continue
        try:
            await call.message.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)
        except:
            pass
    await state.update_data(ai_overview_msg_ids=None)
    await cb_sub_market(call)

@router.message(Command("overview"))
async def cmd_overview(message: Message):
    await _send_ai_overview(message.bot, message.chat.id, message.from_user.id)

@router.callback_query(F.data == "cb_market_overview_refresh")
async def cb_market_overview_refresh(call: CallbackQuery, state: FSMContext):
    await call.answer()
    # Clean up previous messages first if they exist
    data = await state.get_data()
    mids = data.get("ai_overview_msg_ids", [])
    for mid in mids:
        try:
            await call.message.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)
        except:
            pass
            
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_menu")
    status_msg = await call.message.answer(_t(lang, "ai_generating"), reply_markup=kb.as_markup(), parse_mode="HTML")
    await _send_ai_overview(call.message.bot, call.message.chat.id, call.from_user.id, status_msg=status_msg)

@router.message(Command("overview_settings"))
async def cmd_overview_settings(message: Message):
    lang = await db.get_lang(message.chat.id)
    cfg = await db.get_overview_settings(message.from_user.id)
    
    prompt_status = "✅ Custom" if cfg.get('prompt_override') else "❌ Default"
    
    text = (
        f"⚙️ <b>{_t(lang, 'market_title')} - {_t(lang, 'settings_title')}</b>\n\n"
        f"<b>Status:</b> {'✅ Enabled' if cfg['enabled'] else '🔴 Disabled'}\n"
        f"<b>Prompt:</b> {prompt_status}\n\n"
        f"<b>Schedule (UTC):</b>"
    )
    
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_t(lang, "ov_btn_toggle"), callback_data="ov_toggle"))
    
    # List times
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
    
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("ov_"))
async def cb_overview_settings(call: CallbackQuery, state: FSMContext):
    action = call.data
    user_id = call.from_user.id
    lang = await db.get_lang(call.message.chat.id)
    
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
    
    if action == "ov_toggle":
        cfg["enabled"] = not cfg["enabled"]
    elif action.startswith("ov_del_time:"):
        t = action.split(":", 1)[1]
        if t in cfg["schedules"]:
            cfg["schedules"].remove(t)
            
    await db.update_overview_settings(user_id, cfg)
    
    # Refresh message
    prompt_status = "✅ Custom" if cfg.get('prompt_override') else "❌ Default"
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
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))

    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except: pass
    await call.answer()

@router.callback_query(F.data == "cb_overview_settings_menu")
async def cb_overview_settings_menu(call: CallbackQuery):
    await call.answer()
    lang = await db.get_lang(call.message.chat.id)
    cfg = await db.get_overview_settings(call.from_user.id)
    
    prompt_status = "✅ Custom" if cfg.get('prompt_override') else "❌ Default"
    
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
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))
    
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_ai_overview_menu")
async def cb_ai_overview_menu(call: CallbackQuery):
    await call.answer()
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_menu")
    status_msg = await call.message.answer(_t(lang, "ai_generating"), reply_markup=kb.as_markup(), parse_mode="HTML")
    await _send_ai_overview(call.message.bot, call.message.chat.id, call.from_user.id, status_msg=status_msg)

async def _hedge_settings_render(call: CallbackQuery, user_id: int):
    lang = await db.get_lang(call.message.chat.id)
    cfg = await db.get_hedge_settings(user_id)
    
    enabled = cfg.get("enabled", False)
    triggers = cfg.get("triggers", {})
    
    def _btn_text(key, label):
        is_on = triggers.get(key, False)
        return f"{'✅' if is_on else '❌'} {label}"

    kb = InlineKeyboardBuilder()
    
    # Row 0: Master Toggle
    kb.row(InlineKeyboardButton(
        text=_t(lang, "hedge_btn_toggle", state="ON" if enabled else "OFF"), 
        callback_data="hedge_toggle_master"
    ))
    
    # Rows 1-5: Triggers Grid (2 per row)
    trigger_list = [
        ("liquidation", _t(lang, "hedge_trigger_liqs")),
        ("fills", _t(lang, "hedge_trigger_fills")),
        ("proximity", _t(lang, "hedge_trigger_prox")),
        ("volatility", _t(lang, "hedge_trigger_vol")),
        ("whale", _t(lang, "hedge_trigger_whale")),
        ("margin", _t(lang, "hedge_trigger_margin")),
        ("listings", _t(lang, "hedge_trigger_listings")),
        ("ledger", _t(lang, "hedge_trigger_ledger")),
        ("funding", _t(lang, "hedge_trigger_funding")),
        ("oi", _t(lang, "hedge_trigger_oi")),
    ]
    
    for i in range(0, len(trigger_list), 2):
        row = []
        key1, label1 = trigger_list[i]
        row.append(InlineKeyboardButton(text=_btn_text(key1, label1), callback_data=f"hedge_toggle:{key1}"))
        
        if i + 1 < len(trigger_list):
            key2, label2 = trigger_list[i+1]
            row.append(InlineKeyboardButton(text=_btn_text(key2, label2), callback_data=f"hedge_toggle:{key2}"))
        kb.row(*row)
        
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_settings"))
    
    text = f"{_t(lang, 'hedge_title')}\n\n{_t(lang, 'hedge_desc')}"
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_hedge_settings_menu")
async def cb_hedge_settings_menu(call: CallbackQuery):
    await _hedge_settings_render(call, call.from_user.id)
    await call.answer()

@router.callback_query(F.data.startswith("hedge_toggle"))
async def cb_hedge_toggle(call: CallbackQuery):
    user_id = call.from_user.id
    cfg = await db.get_hedge_settings(user_id)
    
    if call.data == "hedge_toggle_master":
        cfg["enabled"] = not cfg.get("enabled", False)
    elif call.data.startswith("hedge_toggle:"):
        key = call.data.split(":")[1]
        if "triggers" not in cfg: cfg["triggers"] = {}
        cfg["triggers"][key] = not cfg["triggers"].get(key, False)
        
    await db.update_hedge_settings(user_id, cfg)
    await _hedge_settings_render(call, user_id)
    await call.answer()

@router.callback_query(F.data == "cb_hedge_chat_start")
async def cb_hedge_chat_start(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_menu")
    
    text = "🛡️ <b>Velox Hedge Chat</b>\n\nI am your AI risk manager. I have full context of your portfolio, watchlist, and latest market news.\n\nHow can I help you today?"
    if lang == "ru":
        text = "🛡️ <b>Velox Hedge Chat</b>\n\nЯ твой ИИ риск-менеджер. У меня есть полный контекст твоего портфеля, вотчлиста и последних новостей рынка.\n\nЧем я могу помочь сегодня?"
        
    await smart_edit(call, text, reply_markup=kb.as_markup())
    await state.set_state(HedgeChatStates.chatting)
    await state.update_data(history=[])
    await call.answer()

@router.message(HedgeChatStates.chatting, ~F.text.startswith("/"))
async def process_hedge_chat(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    history = data.get("history", [])
    
    # Show typing status
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Add user message to history
    history.append({"role": "user", "content": message.text})
    
    # Generate Response
    response = await market_overview.generate_hedge_comment(
        context_type="chat",
        event_data={"user_msg": message.text},
        user_id=message.from_user.id,
        lang=lang,
        history=history
    )
    
    if not response:
        response = "⚠️ I am having trouble connecting to my brain. Please try again."
        if lang == "ru": response = "⚠️ Возникли трудности с подключением. Попробуй еще раз."

    # Add AI response to history
    history.append({"role": "assistant", "content": response})
    
    # Keep history short (last 10 messages)
    if len(history) > 10:
        history = history[-10:]
        
    await state.update_data(history=history)
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_menu")
    
    await message.answer(response, reply_markup=kb.as_markup(), parse_mode="HTML")

async def _send_hedge_insight(bot, chat_id, user_id, context_type, event_data, reply_to_id=None):
    """Fires in background to provide AI insight after a fast alert."""
    try:
        cfg = await db.get_hedge_settings(user_id)
        if not cfg.get("enabled"): return
        if not cfg.get("triggers", {}).get(context_type, True): return
        
        lang = await db.get_lang(chat_id)
        
        # Show typing status
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except: pass

        # AI Generation
        comment = await market_overview.generate_hedge_comment(
            context_type=context_type,
            event_data=event_data,
            user_id=user_id,
            lang=lang
        )
        
        if comment:
            text = f"🛡️ <b>Hedge Insight:</b>\n{comment}"
            if lang == "ru": text = f"🛡️ <b>Velox Hedge:</b>\n{comment}"
            
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_to_message_id=reply_to_id
            )
    except Exception as e:
        logger.error(f"Error in Hedge Insight task: {e}")

@router.error()
async def global_error_handler(event: ErrorEvent):
    logger.error(f"Critical Error in Handler: {event.exception}", exc_info=True)
    try:
        if event.update.message:
            await event.update.message.answer("❌ Internal Bot Error. Please try again later.")
        elif event.update.callback_query:
            await event.update.callback_query.answer("❌ Internal Error.", show_alert=True)
    except:
        pass