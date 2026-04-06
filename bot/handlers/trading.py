import logging
import datetime
import time
import math
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_symbol_name, get_mid_price, get_perps_state, get_user_fills, get_user_funding
)
from bot.analytics import calculate_trade_stats
from bot.handlers._common import (
    smart_edit, _back_kb
)
from bot.utils import format_money, pretty_float
from bot.handlers.states import CalcStates

router = Router(name="trading")
logger = logging.getLogger(__name__)

@router.callback_query(F.data.startswith("cb_stats"))
async def cb_stats(call: CallbackQuery):
    parts = call.data.split(":")
    context = parts[1] if len(parts) > 1 else "trading"
    back_target = "sub:trading" if context != "portfolio" else "sub:portfolio"
    await call.answer("Calculating Stats...")
    lang, wallets = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id)
    if not wallets:
        await smart_edit(call, _t(lang, "need_wallet"), reply_markup=_back_kb(lang, back_target))
        return
    total_wins, total_loss, total_gp, total_gl = 0, 0, 0.0, 0.0
    for wallet in wallets:
        stats = calculate_trade_stats(await get_user_fills(wallet))
        if stats:
            total_wins += stats["wins"]
            total_loss += stats["losses"]
            total_gp += stats["gross_profit"]
            total_gl += stats["gross_loss"]
    total_trades = total_wins + total_loss
    net_pnl = total_gp - total_gl
    text = f"{_t(lang, 'stats_title')}\n\n{_t(lang, 'stats_trades')}: <b>{total_trades}</b>\n{_t(lang, 'stats_winrate')}: <b>{(total_wins / total_trades * 100) if total_trades > 0 else 0.0:.1f}%</b>\n{_t(lang, 'stats_pf')}: <b>{(total_gp / total_gl) if total_gl > 0 else (999.0 if total_gp > 0 else 0):.2f}</b>\n\n{_t(lang, 'gross_profit')}: 🟢 <b>${pretty_float(total_gp, 2)}</b>\n{_t(lang, 'gross_loss')}: 🔴 <b>${pretty_float(total_gl, 2)}</b>\n\n{_t(lang, 'net_pnl')}: {'🟢' if net_pnl >= 0 else '🔴'} <b>${pretty_float(net_pnl, 2)}</b>"
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_pnl"), callback_data=f"cb_pnl:{context}")
    kb.button(text=_t(lang, "btn_back"), callback_data=back_target)
    kb.adjust(1)
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "cb_fills")
async def cb_fills(call: CallbackQuery):
    await call.answer("Fetching history...")
    lang, wallets = await db.get_lang(call.message.chat.id), await db.list_wallets(call.message.chat.id)
    if not wallets:
        await call.message.answer(_t(lang, "need_wallet"))
        return
    all_fills = []
    for wallet in wallets:
        fills = await get_user_fills(wallet)
        for f in fills:
            f['wallet'] = wallet
        all_fills.extend(fills)
    all_fills.sort(key=lambda x: x.get("time", 0), reverse=True)
    lines = [f"📜 <b>Recent Trades (Last 10)</b>"]
    for f in all_fills[:10]:
        coin, side = f.get("coin", "???"), f.get("dir") or f.get("side", "")
        if coin.startswith("@"):
             try:
                 coin = await get_symbol_name(coin, is_spot=True)
             except Exception:
                 pass
        px, sz, pnl = float(f.get("px", 0)), float(f.get("sz", 0)), float(f.get("closedPnl", 0) or 0)
        lines.append(f"{'🟢' if side == 'B' else '🔴'} <b>{coin}</b> {_t(lang, 'hist_buy' if side == 'B' else 'hist_sell')} ${pretty_float(px)}\n   <i>{datetime.datetime.fromtimestamp(f.get('time', 0)/1000).strftime('%H:%M')} | Sz: {sz} (${pretty_float(px*sz, 0)}){(' | PnL: ' + ('+' if pnl>0 else '') + pretty_float(pnl, 2)) if pnl != 0 else ''}</i>")
    if not all_fills:
        lines.append("\n<i>No recent trades found.</i>")
    await smart_edit(call, "\n".join(lines), reply_markup=_back_kb(lang, "sub:trading"))

@router.callback_query(F.data == "cb_risk_check")
async def cb_risk_check(call: CallbackQuery):
    await call.answer("Scanning for risks...")
    lang = await db.get_lang(call.message.chat.id)
    wallets = await db.list_wallets(call.message.chat.id)
    ws = getattr(call.message.bot, "ws_manager", None)
    risky_positions = []
    if not wallets:
        return
    for wallet in wallets:
        state = await get_perps_state(wallet)
        if not state:
            continue
        if "marginSummary" in state:
            ms = state["marginSummary"]
            util = (float(ms.get("totalMarginUsed", 0)) / float(ms.get("accountValue", 0)) * 100) if float(ms.get("accountValue", 0)) > 0 else 0
            if util > 70:
                risky_positions.append(f"⚠️ <b>Wallet {wallet[:6]}...</b> Margin Usage: {util:.1f}%")
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            szi, coin_id, liq = float(pos.get("szi", 0)), pos.get("coin"), float(pos.get("liquidationPx", 0) or 0)
            if szi == 0 or liq <= 0:
                continue
            sym = await get_symbol_name(coin_id, is_spot=False)
            mark = (ws.get_price(sym, coin_id) if ws else 0.0) or await get_mid_price(sym, coin_id)
            if mark > 0:
                dist = abs(mark - liq) / mark * 100
                if dist < 10:
                    risky_positions.append(f"🚨 <b>{sym}</b> {'LONG' if szi > 0 else 'SHORT'} [{wallet[:4]}..]\n   Price: {pretty_float(mark)} | Liq: {pretty_float(liq)}\n   Buffer: <b>{dist:.2f}%</b>")
    await smart_edit(call, _t(lang, "risk_healthy" if not risky_positions else "risk_warning") + ("\n\n" + "\n\n".join(risky_positions) if risky_positions else ""), reply_markup=_back_kb(lang, "sub:trading"))

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
    mode, lang = call.data.split(":")[1], await db.get_lang(call.message.chat.id)
    await state.update_data(mode=mode)
    if mode == "spot":
        await state.update_data(side="long")
        await call.message.edit_text(_t(lang, "calc_balance"), reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.balance)
    elif mode == "reverse":
        await call.message.edit_text("🛡️ <b>Reverse Risk Calculator</b>\n\nEnter <b>Entry Price</b>:", reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.entry)
    else:
        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "calc_long"), callback_data="calc_side:long")
        kb.button(text=_t(lang, "calc_short"), callback_data="calc_side:short")
        kb.button(text=_t(lang, "btn_back"), callback_data="calc_start")
        kb.adjust(2, 1)
        await call.message.edit_text(_t(lang, "calc_side_msg"), reply_markup=kb.as_markup(), parse_mode="HTML")
        await state.set_state(CalcStates.side)
    await call.answer()

@router.callback_query(CalcStates.side, F.data.startswith("calc_side:"))
async def calc_set_side(call: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(call.message.chat.id)
    await state.update_data(side=call.data.split(":")[1])
    await call.message.edit_text(_t(lang, "calc_balance"), reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
    await state.set_state(CalcStates.balance)
    await call.answer()

@router.message(CalcStates.balance)
async def calc_set_balance(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    try:
        await state.update_data(balance=float(message.text.replace(",", ".")))
        try:
            await message.delete()
        except Exception:
            pass
        if data.get("menu_msg_id"):
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=data["menu_msg_id"],
                text=_t(lang, "calc_entry"),
                reply_markup=_back_kb(lang, "calc_start"),
                parse_mode="HTML"
            )
        else:
            await message.answer(_t(lang, "calc_entry"), reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.entry)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.entry)
async def calc_set_entry(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    try:
        await state.update_data(entry=float(message.text.replace(",", ".")))
        try:
            await message.delete()
        except Exception:
            pass
        if data.get("menu_msg_id"):
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=data["menu_msg_id"],
                text=_t(lang, "calc_sl"),
                reply_markup=_back_kb(lang, "calc_start"),
                parse_mode="HTML"
            )
        else:
            await message.answer(_t(lang, "calc_sl"), reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.sl)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.sl)
async def calc_set_sl(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    try:
        await state.update_data(sl=float(message.text.replace(",", ".")))
        prompt = "💰 Enter <b>Risk Amount ($)</b> (e.g. 50):" if data.get("mode") == "reverse" else _t(lang, "calc_tp")
        try:
            await message.delete()
        except Exception:
            pass
        if data.get("menu_msg_id"):
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=data["menu_msg_id"],
                text=prompt,
                reply_markup=_back_kb(lang, "calc_start"),
                parse_mode="HTML"
            )
        else:
            await message.answer(prompt, reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.tp)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.tp)
async def calc_set_tp(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    try:
        val = float(message.text.replace(",", "."))
        await state.update_data(tp=val)
        try:
            await message.delete()
        except Exception:
            pass
        if data.get("mode") == "reverse":
            e = float(data.get("entry", 0))
            sl = float(data.get("sl", 0))
            if e <= 0 or sl <= 0 or val <= 0 or e == sl:
                await message.answer("❌ Invalid inputs.")
                await state.clear()
                return
            dist = abs(e - sl) / e
            sz = val / dist
            res = (
                f"🛡️ <b>Risk Calculation Result</b>\n\n"
                f"Risk: <b>{format_money(val)}</b>\n"
                f"Entry: ${e}\n"
                f"Stop Loss: ${sl} ({'LONG' if e > sl else 'SHORT'})\n"
                f"Distance: {dist*100:.2f}%\n\n"
                f"👉 <b>Position Size: {format_money(sz)}</b>\n"
                f"(Qty: {sz/e:.4f})"
            )
            kb = InlineKeyboardBuilder()
            kb.button(text=_t(lang, "btn_back"), callback_data="calc_start")
            if data.get("menu_msg_id"):
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=data["menu_msg_id"],
                        text=res,
                        reply_markup=kb.as_markup(),
                        parse_mode="HTML"
                    )
                except Exception:
                    await message.answer(res, reply_markup=kb.as_markup(), parse_mode="HTML")
            else:
                await message.answer(res, reply_markup=kb.as_markup(), parse_mode="HTML")
            await state.clear()
            return
        if data.get("menu_msg_id"):
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=data["menu_msg_id"],
                text=_t(lang, "calc_risk"),
                reply_markup=_back_kb(lang, "calc_start"),
                parse_mode="HTML"
            )
        else:
            await message.answer(_t(lang, "calc_risk"), reply_markup=_back_kb(lang, "calc_start"), parse_mode="HTML")
        await state.set_state(CalcStates.risk)
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

@router.message(CalcStates.risk)
async def calc_calculate(message: Message, state: FSMContext):
    lang = await db.get_lang(message.chat.id)
    data = await state.get_data()
    try:
        risk = float(message.text.replace(",", "."))
        await state.clear()
        b = data.get("balance", 0)
        e = data.get("entry", 0)
        sl = data.get("sl", 0)
        tp = data.get("tp", 0)
        side = data.get("side")
        if (side == "long" and sl >= e) or (side == "short" and sl <= e):
            await message.answer(_t(lang, "calc_side_wrong"), parse_mode="HTML")
            return
        rpc = abs(e - sl)
        if rpc == 0:
            await message.answer(_t(lang, "calc_error"))
            return
        pos_coins = risk / rpc
        pos_usd = pos_coins * e
        fees = pos_usd * 0.00035 * 2
        lev = pos_usd / b if b > 0 else 1.0
        rr = abs(tp - e) / rpc
        liq_px = 0
        if side == "long":
            liq_px = (e * (1 - (1/lev) + 0.01))
        elif side == "short" and lev > 1:
            liq_px = (e * (1 + (1/lev) - 0.01))

        total_p = (pos_coins * abs(tp - e)) - fees
        msg = _t(
            lang, "calc_result",
            side=side.upper(),
            mode="PERP" if lev > 1 else "SPOT",
            balance=pretty_float(b),
            risk=pretty_float(risk),
            entry=pretty_float(e),
            sl=pretty_float(sl),
            sl_pct=f"{((sl - e) / e) * 100:+.2f}",
            tp=pretty_float(tp),
            tp_pct=f"{((tp - e) / e) * 100:+.2f}",
            rr=f"{rr:.2f}",
            lev_row=(_t(lang, "calc_lev_lbl", lev=f"{lev:.1f}") if lev > 1 else ""),
            liq_row=(_t(lang, "calc_liq_lbl", liq=pretty_float(liq_px)) if liq_px > 0 else ""),
            size_usd=pretty_float(pos_usd),
            size_coins=pretty_float(pos_coins, 4),
            fees=pretty_float(fees),
            total_loss=pretty_float(risk + fees),
            total_profit=pretty_float(total_p),
            p50=pretty_float(total_p/2),
            p100=pretty_float(total_p)
        )
        if (lev > 1 and ((side == "long" and liq_px > sl) or (side == "short" and liq_px < sl))):
            msg += _t(lang, "calc_liq_warn")

        try:
            await message.delete()
        except Exception:
            pass

        kb = InlineKeyboardBuilder()
        kb.button(text=_t(lang, "btn_back"), callback_data="sub:trading")
        if data.get("menu_msg_id"):
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=data["menu_msg_id"],
                    text=msg,
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML"
                )
            except Exception:
                await message.answer(msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await message.answer(msg, reply_markup=kb.as_markup(), parse_mode="HTML")
    except ValueError:
        await message.answer(_t(lang, "calc_error"))

async def _render_funding_page(bot, chat_id, page=0, edit=False, msg_id=None):
    lang = await db.get_lang(chat_id)
    wallets = await db.list_wallets(chat_id)
    if not wallets:
        if edit and msg_id:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_t(lang, "need_wallet"), parse_mode="HTML")
            except Exception:
                pass
        else:
            await bot.send_message(chat_id, _t(lang, "need_wallet"), parse_mode="HTML")
        return
    start_ts = int((time.time() - 86400) * 1000)
    all_updates = []
    for wallet in wallets:
        updates = await get_user_funding(wallet, start_time=start_ts)
        if updates:
            for u in updates:
                u['wallet'] = wallet
                all_updates.append(u)
    all_updates.sort(key=lambda x: int(x.get("time", 0)), reverse=True)
    ITEMS_PER_PAGE = 10
    total_items = len(all_updates)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
    if total_items > 0:
        page = max(0, min(page, total_pages - 1))
    else:
        page = 0
    items = all_updates[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]
    total_sum_usd = sum([float(u.get("delta", {}).get("amount", 0) or 0) for u in all_updates])
    
    msg_text = f"💰 <b>{_t(lang, 'funding_log_title')}</b>\nTotal (24h): <b>${pretty_float(total_sum_usd, 2)}</b>\n\n"
    if not items:
        msg_text += f"<i>{_t(lang, 'funding_empty')}</i>"
    else:
        log_lines = []
        for item in items:
            ts = int(item.get('time', 0))
            time_str = datetime.datetime.fromtimestamp(ts / 1000).strftime('%H:%M')
            coin = item.get('delta', {}).get('coin', '???')
            amount = float(item.get('delta', {}).get('amount', 0) or 0)
            wallet_short = f"{item['wallet'][:4]}..{item['wallet'][-3:]}"
            log_lines.append(f"• {time_str} <b>{coin}</b>: <b>${amount:+.2f}</b> [{wallet_short}]")
        msg_text += "\n".join(log_lines)
    
    msg_text += f"\n\n<i>Page {page+1}/{max(1, total_pages)}</i>"
    
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
            return
        except Exception:
            pass
    await bot.send_message(chat_id, msg_text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.message(Command("funding"))
async def cmd_funding(message: Message):
    await _render_funding_page(message.bot, message.chat.id, page=0, edit=False)

@router.callback_query(F.data.startswith("cb_funding:"))
async def cb_funding_page(call: CallbackQuery):
    await _render_funding_page(
        call.message.bot, 
        call.message.chat.id, 
        page=int(call.data.split(":")[1]), 
        edit=True, 
        msg_id=call.message.message_id
    )
    await call.answer()
