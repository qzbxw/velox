from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, BufferedInputFile, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_symbol_name, get_mid_price, get_open_orders, get_spot_balances, 
    get_perps_state, pretty_float, get_user_portfolio, get_perps_context,
    extract_avg_entry_from_balance, get_user_fills
)
from bot.analytics import generate_pnl_chart, format_funding_heatmap, generate_pnl_card, calculate_trade_stats, generate_flex_pnl_card
import logging
import time
import html
import math
import csv
import io
import datetime

router = Router()
logger = logging.getLogger(__name__)

# --- UI Helpers ---

def _main_menu_kb(lang):
    kb = InlineKeyboardBuilder()
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
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_balance"), callback_data="cb_balance"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_pnl"), callback_data="cb_pnl"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _trading_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_positions"), callback_data="cb_positions:0"),
        InlineKeyboardButton(text=_t(lang, "btn_orders"), callback_data="cb_orders:0")
    )
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_stats"), callback_data="cb_stats"),
        InlineKeyboardButton(text=_t(lang, "calc_btn"), callback_data="calc_start")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _market_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_market"), callback_data="cb_market"),
        InlineKeyboardButton(text=_t(lang, "btn_whales"), callback_data="cb_whales")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_market_alerts"), callback_data="cb_market_alerts"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_back"), callback_data="cb_menu"))
    return kb.as_markup()

def _back_kb(lang, target="cb_menu"):
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_back"), callback_data=target)
    return kb.as_markup()

def _settings_kb(lang):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_wallets"), callback_data="cb_wallets_menu"))
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_alerts"), callback_data="cb_alerts"))
    kb.row(
        InlineKeyboardButton(text=_t(lang, "btn_export"), callback_data="cb_export"),
        InlineKeyboardButton(text=_t(lang, "btn_flex"), callback_data="cb_flex_menu")
    )
    kb.row(
        InlineKeyboardButton(text="⚡ Prox Alert %", callback_data="set_prox_prompt"),
        InlineKeyboardButton(text="🌊 Vol Alert %", callback_data="set_vol_prompt")
    )
    kb.row(InlineKeyboardButton(text=_t(lang, "btn_lang"), callback_data="cb_lang_menu"))
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
        kb.row(InlineKeyboardButton(text=_t(lang, "btn_share"), callback_data="cb_share_pnl_menu"))
        
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

        # --- 1. Portfolio History ---
        portf = await get_user_portfolio(wallet)
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

        # --- 2. Fills (Trades) ---
        fills = await get_user_fills(wallet)

        if not history and not fills:
            continue
            
        found_any = True
        
        # Prepare PnL lookup
        pnl_map = {p[0]: p[1] for p in pnl_history} if pnl_history else {}

        # CSV 1: History
        if history:
            output_hist = io.StringIO()
            writer = csv.writer(output_hist)
            writer.writerow(["Timestamp", "Date", "Equity", "PnL (Cumulative)"])
            
            for p in history:
                try:
                    ts_ms = p[0]
                    val = p[1]
                    pnl_val = pnl_map.get(ts_ms, "0")
                    dt = datetime.datetime.fromtimestamp(ts_ms/1000).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow([ts_ms, dt, val, pnl_val])
                except:
                    continue
                
            output_hist.seek(0)
            doc_hist = BufferedInputFile(output_hist.getvalue().encode(), filename=f"history_{wallet[:6]}.csv")
            await message.answer_document(doc_hist, caption=f"📊 Equity & PnL History: {wallet[:6]}")

        # CSV 2: Fills
        if fills:
            output_fills = io.StringIO()
            writer = csv.writer(output_fills)
            writer.writerow(["Time", "Symbol", "Side", "Price", "Size", "Value", "Fee", "Realized PnL", "Type"])
            
            # Sort fills by time desc
            fills.sort(key=lambda x: x.get("time", 0), reverse=True)
            
            for f in fills:
                try:
                    ts = f.get("time", 0)
                    dt = datetime.datetime.fromtimestamp(ts/1000).strftime("%Y-%m-%d %H:%M:%S")
                    coin = f.get("coin", "")
                    # Resolve coin name if it's @ID
                    if coin.startswith("@"):
                        try:
                            coin = await get_symbol_name(coin)
                        except:
                            pass
                        
                    side = f.get("side", "")
                    direction = f.get("dir", "") # Open Long, Close Short etc often just 'Open Long' or 'Buy'
                    if not direction:
                        direction = "Buy" if side == "B" else "Sell"
                        
                    px = float(f.get("px", 0))
                    sz = float(f.get("sz", 0))
                    val = px * sz
                    fee = f.get("fee", 0)
                    cl_pnl = f.get("closedPnl", 0)
                    
                    writer.writerow([dt, coin, direction, px, sz, f"{val:.2f}", fee, cl_pnl, "Fill"])
                except:
                    continue

            output_fills.seek(0)
            doc_fills = BufferedInputFile(output_fills.getvalue().encode(), filename=f"fills_{wallet[:6]}.csv")
            await message.answer_document(doc_fills, caption=f"📝 Trade History: {wallet[:6]}")

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

        # --- 1. Portfolio History ---
        portf = await get_user_portfolio(wallet)
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

        # --- 2. Fills (Trades) ---
        fills = await get_user_fills(wallet)

        if not history and not fills:
            continue
            
        found_any = True
        
        # Prepare PnL lookup
        pnl_map = {p[0]: p[1] for p in pnl_history} if pnl_history else {}

        # CSV 1: History
        if history:
            output_hist = io.StringIO()
            writer = csv.writer(output_hist)
            writer.writerow(["Timestamp", "Date", "Equity", "PnL (Cumulative)"])
            
            for p in history:
                try:
                    ts_ms = p[0]
                    val = p[1]
                    pnl_val = pnl_map.get(ts_ms, "0")
                    dt = datetime.datetime.fromtimestamp(ts_ms/1000).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow([ts_ms, dt, val, pnl_val])
                except:
                    continue
                
            output_hist.seek(0)
            doc_hist = BufferedInputFile(output_hist.getvalue().encode(), filename=f"history_{wallet[:6]}.csv")
            await call.message.answer_document(doc_hist, caption=f"📊 Equity & PnL History: {wallet[:6]}")

        # CSV 2: Fills
        if fills:
            output_fills = io.StringIO()
            writer = csv.writer(output_fills)
            writer.writerow(["Time", "Symbol", "Side", "Price", "Size", "Value", "Fee", "Realized PnL", "Type"])
            
            # Sort fills by time desc
            fills.sort(key=lambda x: x.get("time", 0), reverse=True)
            
            for f in fills:
                try:
                    ts = f.get("time", 0)
                    dt = datetime.datetime.fromtimestamp(ts/1000).strftime("%Y-%m-%d %H:%M:%S")
                    coin = f.get("coin", "")
                    if coin.startswith("@"):
                        try:
                            coin = await get_symbol_name(coin)
                        except:
                            pass
                        
                    side = f.get("side", "")
                    direction = f.get("dir", "")
                    if not direction:
                        direction = "Buy" if side == "B" else "Sell"
                        
                    px = float(f.get("px", 0))
                    sz = float(f.get("sz", 0))
                    val = px * sz
                    fee = f.get("fee", 0)
                    cl_pnl = f.get("closedPnl", 0)
                    
                    writer.writerow([dt, coin, direction, px, sz, f"{val:.2f}", fee, cl_pnl, "Fill"])
                except:
                    continue

            output_fills.seek(0)
            doc_fills = BufferedInputFile(output_fills.getvalue().encode(), filename=f"fills_{wallet[:6]}.csv")
            await call.message.answer_document(doc_fills, caption=f"📝 Trade History: {wallet[:6]}")

    try:
        if not found_any:
            await status_msg.edit_text("❌ No data found for any tracked wallets.")
        else:
            await status_msg.delete()
    except:
        pass

@router.callback_query(F.data == "cb_menu")
async def cb_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    text = _t(lang, "welcome")
    if wallets:
        text += "\n\n" + _t(lang, "tracking").format(wallet=f"{wallets[0][:6]}...{wallets[0][-4:]}")
    
    await call.message.edit_text(text, reply_markup=_main_menu_kb(lang), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "sub:portfolio")
async def cb_sub_portfolio(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.edit_text(_t(lang, "menu_portfolio"), reply_markup=_portfolio_kb(lang), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "sub:trading")
async def cb_sub_trading(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.edit_text(_t(lang, "menu_trading"), reply_markup=_trading_kb(lang), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "sub:market")
async def cb_sub_market(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.edit_text(_t(lang, "menu_market"), reply_markup=_market_kb(lang), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()

@router.callback_query(F.data == "cb_balance")
async def cb_balance(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang, "sub:portfolio"), parse_mode="HTML")
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
                hold = float(b.get("hold", 0) or 0)
                
                if amount <= 0: continue
                
                px = 0.0
                if ws: px = ws.get_price(coin_name)
                if not px: px = await get_mid_price(coin_name)
                
                val = amount * px
                wallet_total += val
                
                line = f"▫️ <b>{coin_name}</b>: {amount:.4f} (${pretty_float(val, 0)})"
                if hold > 0:
                    line += f" (🔒 {hold:.4f})"
                wallet_lines.append(line)

        perps_equity = 0.0
        margin_used = 0.0
        total_ntl = 0.0
        total_upnl = 0.0
        withdrawable = 0.0
        maint_margin = 0.0
        
        if perps_state:
            withdrawable = float(perps_state.get("withdrawable", 0) or 0)
            maint_margin = float(perps_state.get("crossMaintenanceMarginUsed", 0) or 0)
            
            # Margin Summary
            if "marginSummary" in perps_state:
                ms = perps_state["marginSummary"]
                perps_equity = float(ms.get("accountValue", 0) or 0)
                margin_used = float(ms.get("totalMarginUsed", 0) or 0)
                total_ntl = float(ms.get("totalNtlPos", 0) or 0)
            
            # Calculate Total uPnL
            for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {})
                coin_id = pos.get("coin")
                szi = float(pos.get("szi", 0))
                entry_px = float(pos.get("entryPx", 0))
                
                if szi == 0: continue
                
                sym = await get_symbol_name(coin_id)
                mark_px = 0.0
                if ws: mark_px = ws.get_price(sym)
                if not mark_px: mark_px = await get_mid_price(sym)
                
                if mark_px:
                     total_upnl += (mark_px - entry_px) * szi

        header = f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b>"
        body = ""
        if wallet_lines:
            body += f"\n   <b>Spot:</b> ${pretty_float(wallet_total, 2)}\n   " + "\n   ".join(wallet_lines)
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
    await call.message.edit_text(text, reply_markup=_back_kb(lang, "sub:portfolio"), parse_mode="HTML")

@router.callback_query(F.data.startswith("cb_positions"))
async def cb_positions(call: CallbackQuery):
    # Parse page
    try:
        page = int(call.data.split(":")[1])
    except IndexError:
        page = 0

    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang), parse_mode="HTML")
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
            sym = await get_symbol_name(coin_id)
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
        text = _t(lang, "positions_title") + "\n\n📭 No open positions."
        await call.message.edit_text(text, reply_markup=_back_kb(lang, "sub:trading"), parse_mode="HTML")
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

    text = f"{_t(lang, 'positions_title')} ({page+1}/{total_pages})\n\n" + "\n\n".join(msg_parts)
    
    kb = _pagination_kb(lang, page, total_pages, "cb_positions", back_target="sub:trading")
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

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
            sym = await get_symbol_name(coin_id)
            entry = float(pos.get("entryPx", 0))
            mark = 0.0
            if ws: mark = ws.get_price(sym)
            if not mark: mark = await get_mid_price(sym)
            
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
    
    await call.message.edit_text(_t(lang, "select_pos"), reply_markup=kb.as_markup())

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
            sym_name = await get_symbol_name(coin_id)
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
    
    buf = generate_pnl_card(data)
    if buf:
        photo = BufferedInputFile(buf.read(), filename=f"pnl_{symbol}.png")
        await call.message.answer_photo(photo)
    else:
        await call.message.answer(_t(lang, "card_error"))

@router.callback_query(F.data.startswith("cb_orders"))
async def cb_orders(call: CallbackQuery):
    try:
        page = int(call.data.split(":")[1])
    except IndexError:
        page = 0
        
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang))
        return

    all_orders = []
    for wallet in wallets:
        orders = await get_open_orders(wallet)
        if isinstance(orders, dict): orders = orders.get("orders", [])
        if not orders: continue
        
        for o in orders:
            o["wallet"] = wallet
            all_orders.append(o)
            
    if not all_orders:
        text = _t(lang, "orders_title") + "\n\n📭 No open orders."
        await call.message.edit_text(text, reply_markup=_back_kb(lang, "sub:trading"), parse_mode="HTML")
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
        # Resolve coin name
        coin_raw = o.get("coin")
        sym = await get_symbol_name(coin_raw)
        
        sz = float(o.get("sz", 0))
        px = float(o.get("limitPx", 0))
        side = o.get("side")
        
        icon = "🟢" if str(side).lower().startswith("b") else "🔴"
        w_short = f"{o['wallet'][:4]}..{o['wallet'][-3:]}"
        
        val_usd = math.floor(sz * px)
        msg_parts.append(f"{icon} <b>{sym}</b>: {sz} (${val_usd}) по ${pretty_float(px)} [{w_short}]")

    text = f"{_t(lang, 'orders_title')} ({page+1}/{total_pages})\n\n" + "\n\n".join(msg_parts)
    kb = _pagination_kb(lang, page, total_pages, "cb_orders", back_target="sub:trading")
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

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
    alerts = await db.get_user_alerts(call.message.chat.id)
    for a in alerts:
        await db.delete_alert(str(a["_id"]))
    await cb_alerts(call)

@router.callback_query(F.data.startswith("del_alert:"))
async def cb_del_alert(call: CallbackQuery):
    aid = call.data.split(":")[1]
    await db.delete_alert(aid)
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
        
        lines.append(
            f"🔹 <b>{sym}</b>: ${pretty_float(price, 4)}\n"
            f"   F: {funding_rate*100:.4f}% ({apr:.1f}% APR) | Vol: ${vol_str}"
        )
    
    # Add timestamp
    ts = time.strftime("%H:%M:%S", time.gmtime())
    text = f"{_t(lang, 'market_title')} (updated {ts})\n\n" + "\n\n".join(lines)
    text += "\n\nℹ️ <i>/watch SYM | /unwatch SYM</i>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_heatmap"), callback_data="cb_heatmap")
    kb.button(text=_t(lang, "btn_refresh"), callback_data="cb_market")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.delete()
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "cb_heatmap")
async def cb_heatmap(call: CallbackQuery):
    await call.answer("Generating Market Overview...")
    lang = await db.get_lang(call.message.chat.id)
    
    ctx = await get_perps_context()
    if not ctx or not isinstance(ctx, list) or len(ctx) != 2:
        await call.message.answer("❌ Error fetching market data.")
        return
        
    universe = ctx[0].get("universe", [])
    asset_ctxs = ctx[1]
    
    # Generate Image
    from bot.analytics import generate_market_overview_image
    
    # Default sort by Volume
    buf = generate_market_overview_image(asset_ctxs, universe, sort_by="vol")
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "sort_funding"), callback_data="cb_heatmap_sort:funding")
    kb.button(text=_t(lang, "sort_oi"), callback_data="cb_heatmap_sort:oi")
    kb.button(text=_t(lang, "sort_change"), callback_data="cb_heatmap_sort:change")
    kb.button(text=_t(lang, "btn_back"), callback_data="cb_market")
    kb.adjust(2, 2)
    
    if buf:
        photo = BufferedInputFile(buf.read(), filename="market_overview.png")
        # If editing a text message, we must delete and send photo, or send photo new.
        # Can't edit text into photo.
        await call.message.delete()
        await call.message.answer_photo(photo, caption="📊 <b>Market Fundamentals</b>", reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await call.message.answer("❌ Error generating image.")

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

@router.callback_query(F.data == "cb_pnl")
async def cb_pnl(call: CallbackQuery):
    await call.answer("Loading...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang), parse_mode="HTML")
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
                sym = await get_symbol_name(coin)
                px = 0.0
                if ws: px = ws.get_price(sym)
                if not px: px = await get_mid_price(sym)
                
                val = amount * px
                w_spot_eq += val
                
                # uPnL for Spot (Approximate)
                entry = extract_avg_entry_from_balance(b)
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
                    sym = await get_symbol_name(coin_id)
                    mark = 0.0
                    if ws: mark = ws.get_price(sym)
                    if not mark: mark = await get_mid_price(sym)
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
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:portfolio")
    kb.adjust(1)
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "cb_pnl_graph")
async def cb_pnl_graph(call: CallbackQuery):
    await call.answer("Generating graph...")
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        return
        
    # Generate for the first wallet for now (or loop/select)
    # Simple v1: just first wallet
    wallet = wallets[0]
    portf = await get_user_portfolio(wallet)
    
    if not portf:
        await call.message.answer("❌ Error fetching history.")
        return

    history = []
    # Handle list response: [["day", {...}], ["week", {...}], ...]
    if isinstance(portf, list):
        # Prefer "allTime" or "month" or "week", else first
        target_data = {}
        for item in portf:
            if isinstance(item, list) and len(item) == 2:
                period, p_data = item
                if period == "allTime":
                    target_data = p_data
                    break
        
        if not target_data and portf and isinstance(portf[0], list) and len(portf[0]) == 2:
             target_data = portf[0][1]
             
        history = target_data.get("accountValueHistory", [])
    elif isinstance(portf, dict):
        # Fallback for old/unexpected dict structure
        data = portf.get("data", {})
        history = data.get("accountValueHistory", [])
    
    if not history:
        await call.message.answer("📭 No history data for graph.")
        return
        
    buf = generate_pnl_chart(history, wallet)
    if buf:
        photo = BufferedInputFile(buf.read(), filename="chart.png")
        await call.message.answer_photo(photo, caption=f"📈 PnL Curve: {wallet}")
    else:
        await call.message.answer("❌ Error generating chart.")

# --- CALCULATOR ---

class CalcStates(StatesGroup):
    mode = State() # spot / perp
    side = State() # long / short
    balance = State()
    entry = State()
    sl = State()
    tp = State()
    risk = State()

class MarketAlertStates(StatesGroup):
    waiting_for_time = State()

@router.callback_query(F.data == "cb_market_alerts")
async def cb_market_alerts(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    user_settings = await db.get_user_settings(call.message.chat.id)
    alert_times = user_settings.get("market_alert_times", [])
    
    text = f"{_t(lang, 'market_alerts_title')}\n\n{_t(lang, 'market_alerts_msg')}\n\n"
    
    kb = InlineKeyboardBuilder()
    if not alert_times:
        text += f"<i>{_t(lang, 'no_market_alerts')}</i>"
    else:
        for t in sorted(alert_times):
            text += f"⏰ <b>{t} UTC</b>\n"
            kb.button(text=f"❌ {t}", callback_data=f"del_market_alert:{t}")
    
    kb.button(text=_t(lang, "btn_add_time"), callback_data="cb_add_market_alert_time")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "cb_add_market_alert_time")
async def cb_add_market_alert_time(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.answer(_t(lang, "add_time_prompt"), parse_mode="HTML")
    await state.set_state(MarketAlertStates.waiting_for_time)
    await call.answer()

@router.message(MarketAlertStates.waiting_for_time)
async def process_market_alert_time(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    time_str = message.text.strip()
    
    # Validate format HH:MM
    try:
        parts = time_str.split(":")
        if len(parts) != 2: raise ValueError
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
        time_str = f"{h:02d}:{m:02d}"
    except ValueError:
        await message.answer(_t(lang, "invalid_time"))
        return

    user_settings = await db.get_user_settings(message.chat.id)
    alert_times = user_settings.get("market_alert_times", [])
    if time_str not in alert_times:
        alert_times.append(time_str)
        await db.update_user_settings(message.chat.id, {"market_alert_times": alert_times})
        
    await state.clear()
    await message.answer(_t(lang, "market_alert_added").format(time=time_str), reply_markup=_back_kb(lang, "cb_market_alerts"), parse_mode="HTML")

@router.callback_query(F.data.startswith("del_market_alert:"))
async def cb_del_market_alert(call: CallbackQuery):
    time_str = call.data.split(":")[1]
    lang = await db.get_lang(call.message.chat.id)
    
    user_settings = await db.get_user_settings(call.message.chat.id)
    alert_times = user_settings.get("market_alert_times", [])
    if time_str in alert_times:
        alert_times.remove(time_str)
        await db.update_user_settings(call.message.chat.id, {"market_alert_times": alert_times})
        
    await call.answer(_t(lang, "market_alert_removed").format(time=time_str))
    await cb_market_alerts(call)

@router.callback_query(F.data == "calc_start")
async def calc_start(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "calc_spot"), callback_data="calc_mode:spot")
    kb.button(text=_t(lang, "calc_perp"), callback_data="calc_mode:perp")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:trading")
    kb.adjust(2, 1)
    
    await call.message.edit_text(_t(lang, "calc_mode"), reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(CalcStates.mode)

@router.callback_query(CalcStates.mode, F.data.startswith("calc_mode:"))
async def calc_set_mode(call: CallbackQuery, state: FSMContext):
    mode = call.data.split(":")[1]
    await state.update_data(mode=mode)
    lang = await db.get_lang(call.message.chat.id)
    
    if mode == "spot":
        await state.update_data(side="long")
        await call.message.edit_text(_t(lang, "calc_balance"), parse_mode="HTML")
        await state.set_state(CalcStates.balance)
    else:
        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "calc_long"), callback_data="calc_side:long")
        kb.button(text=_t(lang, "calc_short"), callback_data="calc_side:short")
        kb.adjust(2)
        
        await call.message.edit_text(_t(lang, "calc_side_msg"), reply_markup=kb.as_markup(), parse_mode="HTML")
        await state.set_state(CalcStates.side)
    
    await call.answer()

@router.callback_query(CalcStates.side, F.data.startswith("calc_side:"))
async def calc_set_side(call: CallbackQuery, state: FSMContext):
    side = call.data.split(":")[1]
    await state.update_data(side=side)
    lang = await db.get_lang(call.message.chat.id)
    await call.message.answer(_t(lang, "calc_balance"), parse_mode="HTML")
    await state.set_state(CalcStates.balance)
    await call.answer()

@router.message(CalcStates.balance)
async def calc_set_balance(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(balance=val)
        await message.answer(_t(lang, "calc_entry"), parse_mode="HTML")
        await state.set_state(CalcStates.entry)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.entry)
async def calc_set_entry(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(entry=val)
        await message.answer(_t(lang, "calc_sl"), parse_mode="HTML")
        await state.set_state(CalcStates.sl)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.sl)
async def calc_set_sl(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(sl=val)
        await message.answer(_t(lang, "calc_tp"), parse_mode="HTML")
        await state.set_state(CalcStates.tp)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.tp)
async def calc_set_tp(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    try:
        # For now support single TP for simple logic, but store as float
        val = float(message.text.replace(",", "."))
        await state.update_data(tp=val)
        await message.answer(_t(lang, "calc_risk"), parse_mode="HTML")
        await state.set_state(CalcStates.risk)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.risk)
async def calc_finish(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    try:
        risk = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer(_t(lang, "calc_error"))
        return

    data = await state.get_data()
    await state.clear()
    
    mode = data["mode"]
    side = data["side"]
    balance = data["balance"]
    entry = data["entry"]
    sl = data["sl"]
    tp = data["tp"]
    
    if entry == sl:
        await message.answer("❌ Entry == SL")
        return
        
    is_long = (side == "long")
    is_perp = (mode == "perp")
    
    # 1. Distances
    dist_sl = abs(entry - sl)
    dist_tp = abs(entry - tp)
    sl_pct = (dist_sl / entry) * 100
    tp_pct = (dist_tp / entry) * 100
    
    # 2. Position Size
    # Risk = Size_Coins * Dist_SL -> Size_Coins = Risk / Dist_SL
    size_coins = risk / dist_sl
    size_usd = size_coins * entry
    
    # 3. Leverage
    leverage = size_usd / balance if balance > 0 else 0
    
    # 4. Fees (Hyperliquid: Taker 0.035%)
    # Open fee + Close fee
    fee_rate = 0.00035 
    fees = size_usd * fee_rate * 2
    
    # 5. Liquidation (Isolated approximation)
    # Maintenance margin ~0.5% on HL for small accounts, but let's use standard formula
    # Long: Liq = Entry * (1 - 1/Lev + MM)
    # Short: Liq = Entry * (1 + 1/Lev - MM)
    mm = 0.005 # 0.5%
    liq_px = 0.0
    if is_perp and leverage > 0:
        if is_long:
            liq_px = entry * (1 - (1/leverage) + mm)
        else:
            liq_px = entry * (1 + (1/leverage) - mm)
    
    # 6. PnL with Fees
    rr = dist_tp / dist_sl
    gross_profit = risk * rr
    total_profit = gross_profit - fees
    total_loss = risk + fees
    
    # 7. Scaling (50/50)
    # TP1 at 50% of the way to TP (conservative) or just 50% size at target?
    # User usually means: 50% size at TP1, 50% size at TP2.
    # Let's show: Profit if we close 50% at current TP, and 50% if it goes further?
    # Actually, simpler scaling: Profit if TP hit with 50% size.
    p50 = (gross_profit * 0.5) - (fees * 0.75) # Half closing fee saved? No, same fee usually.
    p100 = total_profit
    
    # Result formatting
    liq_str = f"{liq_px:.2f}" if liq_px > 0 else _t(lang, "calc_none")
    
    lev_row = ""
    liq_row = ""
    if is_perp:
        lev_row = _t(lang, "calc_lev_lbl", lev=f"{leverage:.1f}")
        liq_row = _t(lang, "calc_liq_lbl", liq=liq_str)

    mode_label = _t(lang, "calc_spot") if mode == "spot" else _t(lang, "calc_perp")
    side_label = _t(lang, "calc_long") if is_long else _t(lang, "calc_short")

    res = _t(lang, "calc_result").format(
        side=side_label,
        mode=mode_label,
        balance=pretty_float(balance, 2),
        risk=pretty_float(risk, 2),
        entry=pretty_float(entry),
        sl=pretty_float(sl),
        sl_pct=f"{sl_pct:.2f}",
        tp=pretty_float(tp),
        tp_pct=f"{tp_pct:.2f}",
        rr=f"{rr:.2f}",
        lev_row=lev_row,
        liq_row=liq_row,
        size_usd=pretty_float(size_usd, 2),
        size_coins=pretty_float(size_coins, 4),
        fees=f"{fees:.2f}",
        total_loss=f"{total_loss:.2f}",
        total_profit=f"{total_profit:.2f}",
        p50=f"{p50:.2f}",
        p100=f"{p100:.2f}"
    )
    
    # Warnings
    warnings = ""
    if is_perp:
        if is_long and liq_px > sl:
            warnings += _t(lang, "calc_liq_warn")
        if not is_long and liq_px < sl and liq_px > 0:
            warnings += _t(lang, "calc_liq_warn")
            
    if mode == "spot" and leverage > 1.05:
         warnings += _t(lang, "calc_low_bal", need=pretty_float(size_usd, 0))
         
    # Direction check
    if is_long and sl > entry: warnings += _t(lang, "calc_side_wrong")
    if not is_long and sl < entry: warnings += _t(lang, "calc_side_wrong")
    
    await message.answer(res + warnings, reply_markup=_back_kb(lang, "sub:trading"), parse_mode="HTML")

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

@router.callback_query(F.data == "cb_stats")
async def cb_stats(call: CallbackQuery):
    await call.answer("Calculating Stats...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.edit_text(_t(lang, "need_wallet"), reply_markup=_back_kb(lang), parse_mode="HTML")
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
    text += f"{_t(lang, 'total_trades')}: <b>{total_trades}</b>\n"
    text += f"{_t(lang, 'win_rate')}: <b>{win_rate:.1f}%</b>\n"
    text += f"{_t(lang, 'profit_factor')}: <b>{pf:.2f}</b>\n\n"
    text += f"{_t(lang, 'gross_profit')}: 🟢 <b>${pretty_float(total_gp, 2)}</b>\n"
    text += f"{_t(lang, 'gross_loss')}: 🔴 <b>${pretty_float(total_gl, 2)}</b>\n"
    
    icon = "🟢" if net_pnl >= 0 else "🔴"
    text += f"\n{_t(lang, 'net_pnl')}: {icon} <b>${pretty_float(net_pnl, 2)}</b>"
    
    # Check PnL History for graph
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_pnl"), callback_data="cb_pnl")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:trading")
    kb.adjust(1)
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "cb_whales")
async def cb_whales(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    user_settings = await db.get_user_settings(call.message.chat.id)
    
    is_on = user_settings.get("whale_alerts", False)
    threshold = user_settings.get("whale_threshold", 100_000)
    
    status = _t(lang, "whale_alerts_on") if is_on else _t(lang, "whale_alerts_off")
    
    text = f"{_t(lang, 'whales_title')}\n\n"
    text += _t(lang, "whale_intro") + "\n\n"
    text += f"{status}\n"
    text += f"Min Value: <b>${pretty_float(threshold, 0)}</b>"
    
    kb = InlineKeyboardBuilder()
    
    toggle_txt = _t(lang, "disable") if is_on else _t(lang, "enable")
    kb.button(text=toggle_txt, callback_data=f"toggle_whales:{'off' if is_on else 'on'}")
    
    kb.button(text="✏️ Threshold", callback_data="set_whale_thr_prompt")
    kb.button(text=_t(lang, "btn_back"), callback_data="sub:market")
    kb.adjust(1)
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("toggle_whales:"))
async def cb_toggle_whales(call: CallbackQuery):
    action = call.data.split(":")[1]
    is_on = (action == "on")
    await db.update_user_settings(call.message.chat.id, {"whale_alerts": is_on})
    await cb_whales(call)

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
async def cb_set_prox_prompt(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.answer(_t(lang, "prox_input"), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "set_vol_prompt")
async def cb_set_vol_prompt(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    await call.message.answer(_t(lang, "vol_input"), parse_mode="HTML")
    await call.answer()

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
    
    await call.message.edit_text(_t(lang, "flex_title"), reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("cb_flex_gen:"))
async def cb_flex_gen(call: CallbackQuery):
    period = call.data.split(":")[1]
    await call.answer("Generating...")
    
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    
    if not wallets:
        await call.message.answer(_t(lang, "need_wallet"))
        return

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
    
    # Label
    p_label = _t(lang, f"flex_period_{period}")
    w_label = "Net Worth" if len(wallets) > 1 else f"Wallet {wallets[0][:4]}"
    
    buf = generate_flex_pnl_card(pnl_val, pnl_pct, p_label, is_positive, w_label)
    
    if buf:
        photo = BufferedInputFile(buf.read(), filename="flex_pnl.png")
        await call.message.answer_photo(photo)
    else:
        await call.message.answer(_t(lang, "flex_gen_error"))
