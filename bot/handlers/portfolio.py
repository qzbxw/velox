import math
import html
import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_symbol_name, get_mid_price, get_spot_balances, 
    get_perps_state, pretty_float, get_user_portfolio,
    extract_avg_entry_from_balance, get_user_vault_equities
)
from bot.analytics import (
    generate_pnl_chart, generate_pnl_card, prepare_portfolio_composition_data,
    prepare_pnl_card_data, prepare_positions_table_data
)
from bot.renderer import render_html_to_image
from bot.handlers._common import (
    smart_edit, smart_edit_media, _back_kb, _pagination_kb,
    _ensure_billing_feature, _consume_billing_usage, BILLING_USAGE_SHARE_PNL,
    format_money
)
from bot.utils import _vault_display_name
from bot.handlers.states import CalcStates

router = Router(name="portfolio")
logger = logging.getLogger(__name__)

@router.callback_query(F.data.startswith("cb_balance"))
async def cb_balance(call: CallbackQuery):
    await call.answer("Loading...")
    parts = call.data.split(":")
    context = parts[1] if len(parts) > 1 else "portfolio"
    back_target = "sub:portfolio" if context != "trading" else "sub:trading"
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
        return
    msg_parts, ws = [], getattr(call.message.bot, "ws_manager", None)
    for wallet in wallets:
        spot_bals, perps_state, vault_equities = await get_spot_balances(wallet), await get_perps_state(wallet), await get_user_vault_equities(wallet)
        wallet_lines, wallet_total = [], 0.0
        if spot_bals:
            for b in spot_bals:
                coin_id = b.get("coin")
                name = html.escape(await get_symbol_name(coin_id, is_spot=True))
                amount = float(b.get("total", 0) or 0)
                if amount <= 0: continue
                px = (ws.get_price(name, coin_id) if ws else 0.0) or await get_mid_price(name, coin_id)
                val = amount * px
                wallet_total += val
                entry = extract_avg_entry_from_balance(b)
                if not entry or entry <= 0:
                    try:
                        coin_fills = await db.get_fills_by_coin(wallet, coin_id)
                        from bot.services import calc_avg_entry_from_fills
                        entry = calc_avg_entry_from_fills(coin_fills)
                    except Exception: entry = 0.0
                pnl_str = ""
                if entry > 0 and px > 0:
                    pnl_pct, pnl_usd = ((px / entry) - 1) * 100, (px - entry) * amount
                    pnl_str = f" | {'🟢' if pnl_pct >= 0 else '🔴'} {pnl_pct:+.1f}% ({format_money(pnl_usd, lang)})"
                line = f"▫️ <b>{name}</b>: {amount:.4f} ({format_money(val, lang)})"
                if entry > 0: line += f"\n     └ {_t(lang, 'avg_lbl')}: ${pretty_float(entry)}{pnl_str}"
                if float(b.get("hold", 0) or 0) > 0: line += f" (🔒 {float(b.get('hold', 0)):.4f})"
                wallet_lines.append(line)
        vault_total, vault_lines = 0.0, []
        if vault_equities:
            for v in vault_equities:
                v_equity = float(v.get("equity", 0))
                if v_equity > 1:
                    vault_total += v_equity
                    vault_lines.append(f"🏛 <b>{_vault_display_name(v.get('vaultAddress'))}</b>: {format_money(v_equity, lang)}")
        perps_equity, margin_used, total_ntl, total_upnl, withdrawable, maint_margin = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        if perps_state:
            withdrawable, maint_margin = float(perps_state.get("withdrawable", 0) or 0), float(perps_state.get("crossMaintenanceMarginUsed", 0) or 0)
            if "marginSummary" in perps_state:
                ms = perps_state["marginSummary"]
                perps_equity, margin_used, total_ntl = float(ms.get("accountValue", 0) or 0), float(ms.get("totalMarginUsed", 0) or 0), float(ms.get("totalNtlPos", 0) or 0)
            for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {})
                szi, entry_px, coin_id = float(pos.get("szi", 0)), float(pos.get("entryPx", 0)), pos.get("coin")
                if szi == 0: continue
                mark_px = (ws.get_price(await get_symbol_name(coin_id, is_spot=False), coin_id) if ws else 0.0) or await get_mid_price(await get_symbol_name(coin_id, is_spot=False), coin_id)
                if mark_px: total_upnl += (mark_px - entry_px) * szi
        header = f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b>"
        body = ""
        if wallet_lines: body += f"\n   <b>Spot:</b> {format_money(wallet_total, lang)}\n   " + "\n   ".join(wallet_lines)
        if vault_lines: body += f"\n   <b>{_t(lang, 'vaults_lbl')}:</b> {format_money(vault_total, lang)}\n   " + "\n   ".join(vault_lines)
        if perps_equity > 1 or margin_used > 0:
             body += f"\n   <b>Perps Eq:</b> {format_money(perps_equity, lang)}\n   {_t(lang, 'withdrawable')}: {format_money(withdrawable, lang)}\n   ⚠️ Margin: {format_money(margin_used, lang)}"
             if perps_equity > 0: body += f"\n   {_t(lang, 'leverage')}: {total_ntl / perps_equity:.1f}x | {_t(lang, 'margin_ratio')}: {(maint_margin / perps_equity) * 100:.1f}%"
             body += f"\n   {'🟢' if total_upnl >= 0 else '🔴'} <b>uPnL:</b> {format_money(total_upnl, lang)}"
        msg_parts.append(header + (body or f"\n   {_t(lang, 'empty_state')}"))
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
    lang, wallets, ws, assets_map = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id), getattr(call.message.bot, "ws_manager", None), {}
    for wallet in wallets:
        spot_bals = await get_spot_balances(wallet)
        if spot_bals:
            for b in spot_bals:
                coin_id, amount = b.get("coin"), float(b.get("total", 0) or 0)
                if amount <= 0: continue
                name = await get_symbol_name(coin_id, is_spot=True)
                px = (ws.get_price(name, coin_id) if ws else 0.0) or await get_mid_price(name, coin_id)
                assets_map[name] = assets_map.get(name, 0) + (amount * px)
        perps_state = await get_perps_state(wallet)
        if perps_state and "marginSummary" in perps_state:
             assets_map["USDC (Margin)"] = assets_map.get("USDC (Margin)", 0) + float(perps_state["marginSummary"].get("accountValue", 0) or 0)
    if not assets_map:
        await call.answer("No assets found.", show_alert=True)
        return
    comp_data = prepare_portfolio_composition_data([{"name": k, "value": v} for k, v in assets_map.items() if v > 1])
    try:
        buf = await render_html_to_image("portfolio_composition.html", comp_data, lang=lang)
        await smart_edit_media(call, BufferedInputFile(buf.read(), filename="portfolio.png"), "📊 <b>Portfolio Composition</b>", reply_markup=_back_kb(lang, "cb_balance:portfolio"))
    except Exception as e:
        logger.error(f"Error rendering portfolio composition: {e}")
        await call.message.answer("❌ Error generating image.")

@router.callback_query(F.data.startswith("cb_positions"))
async def cb_positions(call: CallbackQuery):
    parts = call.data.split(":")
    context = parts[1] if len(parts) >= 2 else "trading"
    try: page = int(parts[2]) if len(parts) >= 3 else (int(parts[1]) if len(parts) == 2 else 0)
    except Exception: page = 0
    back_target = "sub:portfolio" if context == "portfolio" else "sub:trading"
    await call.answer("Loading...")
    lang, wallets, all_positions_data, ws = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id), [], getattr(call.message.bot, "ws_manager", None)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
        return
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            szi, coin_id = float(pos.get("szi", 0)), pos.get("coin")
            if szi == 0: continue
            sym = await get_symbol_name(coin_id, is_spot=False)
            entry_px, leverage, liq_px = float(pos.get("entryPx", 0)), float(pos.get("leverage", {}).get("value", 0)), float(pos.get("liquidationPx", 0) or 0)
            mark_px = (ws.get_price(sym, coin_id) if ws else 0.0) or await get_mid_price(sym, coin_id)
            upnl = (mark_px - entry_px) * szi if mark_px else 0.0
            roi = (upnl / (abs(szi) * entry_px / leverage)) * 100 if (leverage and szi and entry_px) else 0.0
            all_positions_data.append({"wallet": wallet, "sym": sym, "szi": szi, "entry": entry_px, "lev": leverage, "liq": liq_px, "upnl": upnl, "roi": roi})
    if not all_positions_data:
        await smart_edit(call, _t(lang, "positions_title") + "\n\n" + _t(lang, "no_open_positions"), reply_markup=_back_kb(lang, back_target))
        return
    ITEMS_PER_PAGE = 5
    total_pages = math.ceil(len(all_positions_data) / ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_items = all_positions_data[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]
    msg_parts = [f"{'🟢' if i['szi'] > 0 else '🔴'} <b>{i['sym']}</b> {i['lev']}x [{i['wallet'][:4]}..{i['wallet'][-3:]}]\n   Sz: {i['szi']:.4f} @ ${pretty_float(i['entry'])}\n   Liq: ${pretty_float(i['liq'])} | uPnL: <b>${pretty_float(i['upnl'], 2)}</b> ({i['roi']:+.0f}%)" for i in page_items]
    kb = _pagination_kb(lang, page, total_pages, f"cb_positions:{context}", back_target=back_target)
    for i in page_items:
        is_l = 1 if i['szi'] > 0 else 0
        cb_data = f"cx:{i['sym']}:{i['entry']:.2f}:{abs(i['szi']):.4f}:{i['lev']:.0f}:{is_l}:{i['liq']:.2f}"
        if len(cb_data) > 64: cb_data = f"cx:{i['sym']}:{i['entry']:.1f}:{abs(i['szi']):.2f}:{i['lev']:.0f}:{is_l}:{i['liq']:.1f}"
        kb.inline_keyboard.insert(-1, [InlineKeyboardButton(text=_t(lang, "calc_exit_btn", sym=i['sym']), callback_data=cb_data)])
    kb.inline_keyboard.insert(-1, [InlineKeyboardButton(text="🖼 Positions Table", callback_data="cb_positions_img")])
    await smart_edit(call, f"{_t(lang, 'positions_title')} ({page+1}/{total_pages})\n\n" + "\n\n".join(msg_parts), reply_markup=kb)

@router.callback_query(F.data == "cb_positions_img")
async def cb_positions_img(call: CallbackQuery):
    await call.answer("Generating Table...")
    lang, wallets, combined_positions, ws = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id), [], getattr(call.message.bot, "ws_manager", None)
    if not wallets: return
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if state:
            for p in state.get("assetPositions", []):
                pos = p.get("position", {})
                szi, coin_id = float(pos.get("szi", 0)), pos.get("coin")
                if szi == 0: continue
                sym = await get_symbol_name(coin_id, is_spot=False)
                entry, leverage, liq = float(pos.get("entryPx", 0)), float(pos.get("leverage", {}).get("value", 0)), float(pos.get("liquidationPx", 0) or 0)
                mark = (ws.get_price(sym, coin_id) if ws else 0.0) or await get_mid_price(sym, coin_id)
                pnl = (mark - entry) * szi if mark else 0.0
                roi = (pnl / (abs(szi) * entry / leverage)) * 100 if (leverage and szi and entry) else 0.0
                combined_positions.append({"symbol": sym, "side": "LONG" if szi > 0 else "SHORT", "leverage": leverage, "size_usd": abs(szi * mark), "entry": entry, "mark": mark, "liq": liq, "pnl": pnl, "roi": roi})
        spot_bals = await get_spot_balances(wallet)
        if spot_bals:
            for b in spot_bals:
                coin_id, amount = b.get("coin"), float(b.get("total", 0) or 0)
                if amount <= 0: continue
                name = await get_symbol_name(coin_id, is_spot=True)
                px = (ws.get_price(name, coin_id) if ws else 0.0) or await get_mid_price(name, coin_id)
                entry = extract_avg_entry_from_balance(b)
                if not entry or entry <= 0:
                    try: entry = calc_avg_entry_from_fills(await db.get_fills_by_coin(wallet, coin_id))
                    except Exception: entry = 0.0
                spot_pnl = (px - entry) * amount if (entry > 0 and px > 0) else 0.0
                combined_positions.append({"symbol": name, "side": "SPOT", "leverage": "SPOT", "size_usd": amount * px, "entry": entry, "mark": px, "liq": 0.0, "pnl": spot_pnl, "roi": ((px / entry) - 1) * 100 if entry > 0 else 0.0})
    if not combined_positions:
        await call.answer("No open positions.", show_alert=True)
        return
    try:
        buf = await render_html_to_image("positions_table.html", prepare_positions_table_data(combined_positions), lang=lang)
        await smart_edit_media(call, BufferedInputFile(buf.read(), filename="positions.png"), "📋 <b>Open Positions</b>", reply_markup=_back_kb(lang, "sub:trading"))
    except Exception as e:
        logger.error(f"Error rendering positions table: {e}")
        await call.message.answer("❌ Error generating image.")

@router.callback_query(F.data.startswith("cx:"))
async def cb_calc_exit(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    sym, entry, size, lev, is_long = parts[1], float(parts[2]), float(parts[3]), float(parts[4]), parts[5] == "1"
    liq_px, lang = float(parts[6]) if len(parts) > 6 else 0.0, await db.get_lang(call.message.chat.id)
    await state.update_data(mode="perp", side="long" if is_long else "short", entry=entry, size=size, lev=lev, is_exit=True, symbol=sym, liq_px=liq_px, balance=(size * entry) / lev if lev > 0 else size * entry)
    await call.message.answer(_t(lang, "exit_calc_title", sym=sym) + _t(lang, "calc_sl"), parse_mode="HTML")
    await state.set_state(CalcStates.sl)
    await call.answer()

@router.callback_query(F.data.startswith("cb_share_pnl_menu"))
async def cb_share_pnl_menu(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "share_pnl", "billing_feature_share_pnl", is_callback=True): return
    await call.answer("Loading...")
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets: return
    parts = call.data.split(":")
    context = parts[1] if len(parts) >= 2 and parts[1] else "trading"
    try: page = int(parts[2]) if len(parts) >= 3 else 0
    except Exception: page = 0
    kb, ws, has_pos = InlineKeyboardBuilder(), getattr(call.message.bot, "ws_manager", None), False
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            szi, coin_id = float(pos.get("szi", 0)), pos.get("coin")
            if szi == 0: continue
            has_pos, sym = True, await get_symbol_name(coin_id, is_spot=False)
            entry = float(pos.get("entryPx", 0))
            mark = (ws.get_price(sym) if ws else 0.0) or await get_mid_price(sym, coin_id)
            upnl = (mark - entry) * szi if mark else 0.0
            kb.button(text=f"{sym} {'+' if upnl >= 0 else '-'}${pretty_float(abs(upnl), 0)}", callback_data=f"cb_share_pnl:{context}:{page}:{sym}")
    if not has_pos:
        await call.answer("No open positions to share.", show_alert=True)
        return
    kb.button(text=_t(lang, "btn_back"), callback_data=f"cb_positions:{context}:{page}")
    kb.adjust(2)
    await smart_edit(call, _t(lang, "select_pos"), reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("cb_share_pnl:"))
async def cb_share_pnl(call: CallbackQuery):
    parts = call.data.split(":")
    context, symbol = (parts[1], parts[3]) if len(parts) >= 4 else ("trading", parts[1])
    try: page = int(parts[2]) if len(parts) >= 4 else 0
    except Exception: page = 0
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "share_pnl", "billing_feature_share_pnl", is_callback=True) or \
       not await _consume_billing_usage(call, call.message.chat.id, lang, BILLING_USAGE_SHARE_PNL, "share_pnl_daily", "billing_feature_share_pnl_daily", is_callback=True): return
    await call.answer(f"Generating card for {symbol}...")
    wallets, ws, target_pos = await db.list_wallets(call.message.chat.id), getattr(call.message.bot, "ws_manager", None), None
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state: continue
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            if (await get_symbol_name(pos.get("coin"), is_spot=False)) == symbol and float(pos.get("szi", 0)) != 0:
                target_pos = pos; break
        if target_pos: break
    if not target_pos:
        await call.message.answer(_t(lang, "pos_not_found")); return
    szi, entry, leverage = float(target_pos.get("szi", 0)), float(target_pos.get("entryPx", 0)), float(target_pos.get("leverage", {}).get("value", 1))
    mark = (ws.get_price(symbol) if ws else 0.0) or await get_mid_price(symbol)
    upnl = (mark - entry) * szi
    roi = (upnl / (abs(szi) * entry / leverage)) * 100 if (leverage and szi and entry) else 0.0
    try:
        buf = await render_html_to_image("pnl_card.html", prepare_pnl_card_data({"symbol": symbol, "side": "LONG" if szi > 0 else "SHORT", "leverage": leverage, "entry": entry, "mark": mark, "roi": roi, "pnl": upnl}), lang=lang)
        await smart_edit_media(call, BufferedInputFile(buf.read(), filename="pnl.png"), f"🚀 <b>{symbol} Position</b>", reply_markup=_back_kb(lang, f"cb_positions:{context}:{page}"))
    except Exception as e:
        logger.error(f"Error rendering PnL card: {e}")
        await call.message.answer("❌ Error generating image.")

@router.callback_query(F.data.startswith("cb_orders"))
async def cb_orders(call: CallbackQuery):
    parts = call.data.split(":")
    context = parts[1] if len(parts) >= 2 else "trading"
    try: page = int(parts[2]) if len(parts) >= 3 else (int(parts[1]) if len(parts) == 2 else 0)
    except Exception: page = 0
    back_target = "sub:portfolio" if context == "portfolio" else "sub:trading"
    await call.answer("Loading...")
    lang, wallets = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target)); return
    all_orders, wallet_data = [], {}
    from bot.services import get_open_orders
    for wallet in wallets:
        orders = await get_open_orders(wallet)
        orders = orders.get("orders", []) if isinstance(orders, dict) else orders
        if not orders: continue
        wallet_data[wallet] = {"spot": await get_spot_balances(wallet), "perps": await get_perps_state(wallet)}
        for o in orders: o["wallet"] = wallet; all_orders.append(o)
    if not all_orders:
        await smart_edit(call, _t(lang, "orders_title") + "\n\n" + _t(lang, "no_open_orders"), reply_markup=_back_kb(lang, back_target)); return
    ITEMS_PER_PAGE = 5
    total_pages = math.ceil(len(all_orders) / ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_items = all_orders[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]
    msg_parts = []
    for o in page_items:
        wallet, coin_raw = o["wallet"], o.get("coin")
        is_spot = str(coin_raw).startswith("@")
        sym, sz, px = await get_symbol_name(coin_raw, is_spot=is_spot), float(o.get("sz", 0)), float(o.get("limitPx", 0))
        is_buy = str(o.get("side", "")).lower().startswith("b")
        current_px = await get_mid_price(sym, coin_raw)
        dist_str = f"<b>{((px - current_px) / current_px) * 100:+.2f}%</b>" if (current_px > 0 and px > 0) else "n/a"
        profit_line, avg_entry, current_sz = "", 0.0, 0.0
        if is_spot:
            for b in wallet_data[wallet]["spot"]:
                if str(b.get("coin")) == str(coin_raw): avg_entry, current_sz = extract_avg_entry_from_balance(b), float(b.get("total", 0)); break
        elif wallet_data[wallet]["perps"]:
            for p in wallet_data[wallet]["perps"].get("assetPositions", []):
                pos = p.get("position", {})
                if str(pos.get("coin")) == str(coin_raw): avg_entry, current_sz = float(pos.get("entryPx", 0)), float(pos.get("szi", 0)); break
        if not is_buy and avg_entry > 0:
            pnl_usd = (px - avg_entry) * sz if (is_spot or current_sz >= 0) else (avg_entry - px) * sz
            pnl_pct = ((px / avg_entry) - 1) * 100 if (is_spot or current_sz >= 0) else ((avg_entry / px) - 1) * 100
            profit_line = f"\n   " + _t(lang, "profit_if_filled", val=f"{'🟢' if pnl_usd >= 0 else '🔴'}\"${pretty_float(pnl_usd, 2)}", pct=f"{pnl_pct:+.1f}")
        elif is_buy and avg_entry > 0:
            if not is_spot and current_sz < 0:
                pnl_usd, pnl_pct = (avg_entry - px) * sz, ((avg_entry / px) - 1) * 100
                profit_line = f"\n   " + _t(lang, "profit_if_filled", val=f"{'🟢' if pnl_usd >= 0 else '🔴'}\"${pretty_float(pnl_usd, 2)}", pct=f"{pnl_pct:+.1f}")
            elif current_sz > 0:
                new_avg = ((current_sz * avg_entry) + (sz * px)) / (current_sz + sz)
                profit_line = f"\n   " + _t(lang, "new_avg_if_filled", val=pretty_float(new_avg, 2), pct=f"{((new_avg / avg_entry) - 1) * 100:+.1f}")
        msg_parts.append(f"{'🟢' if is_buy else '🔴'} <b>{sym}</b> [{'Spot' if is_spot else 'Perp'}]\n   {'BUY' if is_buy else 'SELL'}: {sz} @ \"${pretty_float(px)}\" (~${pretty_float(sz*px, 2)})\n   Цена: ${pretty_float(current_px)} | До входа: {dist_str} [{wallet[:4]}..{wallet[-3:]}]{profit_line}")
    await smart_edit(call, f"{_t(lang, 'orders_title')} ({page+1}/{total_pages})\n\n" + "\n\n".join(msg_parts), reply_markup=_pagination_kb(lang, page, total_pages, f"cb_orders:{context}", back_target=back_target))

@router.callback_query(F.data.startswith("cb_pnl"))
async def cb_pnl(call: CallbackQuery):
    await call.answer("Loading...")
    parts = call.data.split(":")
    context = parts[1] if len(parts) > 1 else "portfolio"
    back_target = {"trading": "sub:trading", "stats": "cb_stats"}.get(context, "sub:portfolio")
    lang, wallets = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target)); return
    ws, g_spot_eq, g_perps_eq, g_spot_upnl, g_perps_upnl, wallet_cards = getattr(call.message.bot, "ws_manager", None), 0.0, 0.0, 0.0, 0.0, []
    for wallet in wallets:
        w_spot_eq, w_spot_upnl, w_perps_eq, w_perps_upnl = 0.0, 0.0, 0.0, 0.0
        spot_bals = await get_spot_balances(wallet)
        if spot_bals:
            for b in spot_bals:
                coin, amount = b.get("coin"), float(b.get("total", 0) or 0)
                if amount <= 0: continue
                sym = await get_symbol_name(coin, is_spot=True)
                px = (ws.get_price(sym, coin) if ws else 0.0) or await get_mid_price(sym, coin)
                w_spot_eq += amount * px
                entry = extract_avg_entry_from_balance(b) or (lambda: 0.0)()
                if not entry:
                    try: entry = calc_avg_entry_from_fills(await db.get_fills_by_coin(wallet, coin))
                    except Exception: entry = 0.0
                if entry > 0 and px > 0: w_spot_upnl += (px - entry) * amount
        perps_state = await get_perps_state(wallet)
        if perps_state:
            if "marginSummary" in perps_state: w_perps_eq = float(perps_state["marginSummary"].get("accountValue", 0) or 0)
            for p in perps_state.get("assetPositions", []):
                pos = p.get("position", {})
                szi, entry_px, coin_id = float(pos.get("szi", 0)), float(pos.get("entryPx", 0)), pos.get("coin")
                if szi != 0:
                    sym = await get_symbol_name(coin_id, is_spot=False)
                    mark = (ws.get_price(sym, coin_id) if ws else 0.0) or await get_mid_price(sym, coin_id)
                    if mark: w_perps_upnl += (mark - entry_px) * szi
        portf, pnl_stats = await get_user_portfolio(wallet), ""
        history_points = portf.get("data", {}).get("accountValueHistory", []) if isinstance(portf, dict) else (portf if isinstance(portf, list) else [])
        if history_points and len(history_points) > 1:
            try:
                history_points.sort(key=lambda x: x[0])
                now_ms = history_points[-1][0]
                def get_change(delta):
                    t = now_ms - delta
                    c = min(history_points, key=lambda x: abs(x[0] - t))
                    return (float(history_points[-1][1]) - float(c[1])) if abs(c[0] - t) <= 86400000 * 2 else 0.0
                pnl_stats = f"\n   24h: {'🟢' if get_change(86400000)>=0 else '🔴'} ${pretty_float(get_change(86400000), 2)} | 7d: {'🟢' if get_change(86400000*7)>=0 else '🔴'} ${pretty_float(get_change(86400000*7), 2)} | 30d: {'🟢' if get_change(86400000*30)>=0 else '🔴'} ${pretty_float(get_change(86400000*30), 2)}"
            except Exception: pass
        g_spot_eq += w_spot_eq; g_perps_eq += w_perps_eq; g_spot_upnl += w_spot_upnl; g_perps_upnl += w_perps_upnl
        card = f"👛 <b>{wallet[:6]}...{wallet[-4:]}</b>\n   <b>{_t(lang, 'total_lbl')}: ${pretty_float(w_spot_eq + w_perps_eq, 2)}</b>"
        if w_spot_eq > 1: card += f"\n   {_t(lang, 'spot_bal')}: ${pretty_float(w_spot_eq, 2)} (uPnL: {'🟢' if w_spot_upnl>=0 else '🔴'}${pretty_float(w_spot_upnl, 2)})"
        if w_perps_eq > 1 or w_perps_upnl != 0: card += f"\n   {_t(lang, 'perps_bal')}: ${pretty_float(w_perps_eq, 2)} (uPnL: {'🟢' if w_perps_upnl>=0 else '🔴'}${pretty_float(w_perps_upnl, 2)})"
        wallet_cards.append(card + pnl_stats)
    g_upnl = g_spot_upnl + g_perps_upnl
    text = f"{_t(lang, 'pnl_title')}\n\n{_t(lang, 'net_worth')}: <b>${pretty_float(g_spot_eq + g_perps_eq, 2)}</b>\n   {_t(lang, 'spot_bal')}: ${pretty_float(g_spot_eq, 2)}\n   {_t(lang, 'perps_bal')}: ${pretty_float(g_perps_eq, 2)}\n   {_t(lang, 'total_upnl')}: {'🟢' if g_upnl>=0 else '🔴'} <b>${pretty_float(g_upnl, 2)}</b>\n\n" + "\n\n".join(wallet_cards)
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_graph"), callback_data="cb_pnl_graph")
    kb.button(text=_t(lang, "btn_back"), callback_data=back_target)
    kb.adjust(1)
    await smart_edit(call, text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "cb_pnl_graph")
async def cb_pnl_graph(call: CallbackQuery):
    await call.answer("Generating graph...")
    lang, wallets = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang)); return
    aggregated_history = {}
    for wallet in wallets:
        portf = await get_user_portfolio(wallet)
        if not portf: continue
        h = []
        if isinstance(portf, list):
            target = next((i[1] for i in portf if isinstance(i, list) and len(i) == 2 and i[0] == "allTime"), None)
            if not target and portf and isinstance(portf[0], list): target = portf[0][1]
            h = target.get("accountValueHistory", []) if target else []
        elif isinstance(portf, dict): h = portf.get("data", {}).get("accountValueHistory", [])
        for ts, equity in h: aggregated_history[ts] = aggregated_history.get(ts, 0.0) + float(equity)
    if not aggregated_history:
        await call.message.answer("📭 No history data for graph."); return
    try:
        buf = generate_pnl_chart([[ts, val] for ts, val in sorted(aggregated_history.items())], "Total Portfolio" if len(wallets) > 1 else wallets[0])
        await smart_edit_media(call, BufferedInputFile(buf.read(), filename="pnl_chart.png"), "📈 <b>Equity History & Drawdown</b>", reply_markup=_back_kb(lang, "cb_pnl"))
    except Exception as e:
        logger.error(f"Error rendering chart: {e}")
        await call.message.answer("❌ Error generating graph.")
