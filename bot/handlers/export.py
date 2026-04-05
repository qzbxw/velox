import logging
import asyncio
import datetime
import io
import csv
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from bot.database import db
from bot.locales import _t
from bot.services import (
    get_user_portfolio, get_user_fills, get_user_funding, get_user_ledger,
    get_symbol_name
)
from bot.handlers._common import (
    smart_edit, _ensure_billing_feature, _consume_billing_usage, BILLING_USAGE_EXPORTS
)

router = Router(name="export")
logger = logging.getLogger(__name__)

async def _generate_export_files(wallet: str):
    """Internal helper to generate CSV files for a wallet."""
    portf, fills, funding, ledger = await asyncio.gather(
        get_user_portfolio(wallet), get_user_fills(wallet), get_user_funding(wallet), get_user_ledger(wallet),
        return_exceptions=True
    )
    if isinstance(portf, Exception): portf = None
    fills = [] if isinstance(fills, Exception) else fills
    funding = [] if isinstance(funding, Exception) else funding
    ledger = [] if isinstance(ledger, Exception) else ledger

    history, pnl_history = [], []
    if portf:
        target_data = {}
        if isinstance(portf, list):
            target_data = next((i[1] for i in portf if isinstance(i, list) and len(i) == 2 and i[0] == "allTime"), None)
            if not target_data and portf and isinstance(portf[0], list): target_data = portf[0][1]
        elif isinstance(portf, dict): target_data = portf.get("data", {})
        history, pnl_history = target_data.get("accountValueHistory", []), target_data.get("pnlHistory", [])

    if not history and not fills and not funding and not ledger: return None, None

    combined_history, pnl_map = [], ({p[0]: p[1] for p in pnl_history} if pnl_history else {})
    for p in history: combined_history.append({"ts": p[0], "equity": p[1], "pnl": pnl_map.get(p[0], "0"), "cash": 0, "funding": 0, "type": "Equity Sample"})
    for l in ledger: combined_history.append({"ts": l.get("time", 0), "equity": "", "pnl": "", "cash": l.get("delta", {}).get("amount", 0), "funding": 0, "type": f"Ledger: {l.get('delta', {}).get('type', 'update')}"})
    for f in funding: combined_history.append({"ts": f.get("time", 0), "equity": "", "pnl": "", "cash": 0, "funding": f.get("delta", {}).get("amount", 0), "type": "Funding Payment"})
    combined_history.sort(key=lambda x: x["ts"])

    output_hist = io.StringIO()
    writer_hist = csv.writer(output_hist)
    writer_hist.writerow(["Timestamp", "Date", "Equity", "PnL (Cumulative)", "Cash Flow", "Funding", "Type"])
    for row in combined_history:
        writer_hist.writerow([row["ts"], datetime.datetime.fromtimestamp(row["ts"]/1000).strftime("%Y-%m-%d %H:%M:%S"), row["equity"], row["pnl"], row["cash"], row["funding"], row["type"]])
    
    output_fills = io.StringIO()
    writer_fills = csv.writer(output_fills)
    writer_fills.writerow(["Time", "Symbol", "Side", "Price", "Size", "Value", "Fee", "Realized PnL", "Trade ID", "Liquidity", "Type"])
    combined_fills = [{"time": f.get("time", 0), "coin": f.get("coin", ""), "side": f.get("side", ""), "dir": f.get("dir", ""), "px": f.get("px", 0), "sz": f.get("sz", 0), "fee": f.get("fee", 0), "pnl": f.get("closedPnl", 0), "tid": f.get("tid", ""), "liq": f.get("liquidity", ""), "type": "Fill"} for f in fills]
    for f in funding: combined_fills.append({"time": f.get("time", 0), "coin": f.get("delta", {}).get("coin", ""), "side": "", "dir": "Funding", "px": f.get("delta", {}).get("fundingRate", 0), "sz": f.get("delta", {}).get("szi", 0), "fee": 0, "pnl": f.get("delta", {}).get("amount", 0), "tid": f.get("hash", ""), "liq": "", "type": "Funding"})
    combined_fills.sort(key=lambda x: x["time"], reverse=True)

    for f in combined_fills:
        try:
            coin = f["coin"]
            if coin.startswith("@"):
                try: coin = await get_symbol_name(coin)
                except Exception: pass
            px, sz = float(f["px"]), float(f["sz"])
            writer_fills.writerow([datetime.datetime.fromtimestamp(f["time"]/1000).strftime("%Y-%m-%d %H:%M:%S"), coin, f["dir"] or ("Buy" if f["side"] == "B" else "Sell"), px, sz, f"{px * sz if f['type'] == 'Fill' else 0:.2f}", f["fee"], f["pnl"], f["tid"], f["liq"], f["type"]])
        except Exception: continue

    return BufferedInputFile(output_hist.getvalue().encode(), filename=f"history_{wallet[:6]}.csv"), BufferedInputFile(output_fills.getvalue().encode(), filename=f"fills_{wallet[:6]}.csv")

@router.callback_query(F.data == "cb_export")
async def cb_export(call: CallbackQuery):
    lang = await db.get_lang(call.message.chat.id)
    if not await _ensure_billing_feature(call, call.message.chat.id, lang, "export", "billing_feature_export", is_callback=True) or \
       not await _consume_billing_usage(call, call.message.chat.id, lang, BILLING_USAGE_EXPORTS, "exports_daily", "billing_feature_exports_daily", is_callback=True): return
    await call.answer("Exporting...")
    status_msg = await call.message.answer("⏳ Exporting data...")
    wallets = await db.list_wallets(call.message.chat.id)
    if not wallets:
        await status_msg.edit_text(_t(lang, "need_wallet")); return
    found_any = False
    for wallet in wallets:
        try: await status_msg.edit_text(f"⏳ Exporting {wallet[:6]}... (History & Fills)")
        except Exception: pass
        doc_hist, doc_fills = await _generate_export_files(wallet)
        if doc_hist: found_any = True; await call.message.answer_document(doc_hist, caption=f"📊 Equity & Ledger History: {wallet[:6]}")
        if doc_fills: found_any = True; await call.message.answer_document(doc_fills, caption=f"📝 Trade & Transaction History: {wallet[:6]}")
    if not found_any: await status_msg.edit_text("❌ No data found for any tracked wallets.")
    else: await status_msg.delete()

@router.message(Command("export"))
async def cmd_export(message: Message):
    lang = await db.get_lang(message.chat.id)
    if not await _ensure_billing_feature(message, message.chat.id, lang, "export", "billing_feature_export") or \
       not await _consume_billing_usage(message, message.chat.id, lang, BILLING_USAGE_EXPORTS, "exports_daily", "billing_feature_exports_daily"): return
    status_msg = await message.answer("⏳ Exporting data...")
    wallets = await db.list_wallets(message.chat.id)
    if not wallets:
        await status_msg.edit_text(_t(lang, "need_wallet")); return
    found_any = False
    for wallet in wallets:
        try: await status_msg.edit_text(f"⏳ Exporting {wallet[:6]}... (History & Fills)")
        except Exception: pass
        doc_hist, doc_fills = await _generate_export_files(wallet)
        if doc_hist: found_any = True; await message.answer_document(doc_hist, caption=f"📊 Equity & Ledger History: {wallet[:6]}")
        if doc_fills: found_any = True; await message.answer_document(doc_fills, caption=f"📝 Trade & Transaction History: {wallet[:6]}")
    if not found_any: await status_msg.edit_text("❌ No data found for any tracked wallets.")
    else: await status_msg.delete()
