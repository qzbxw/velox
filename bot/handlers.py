from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import db
from bot.services import extract_avg_entry_from_balance, extract_spot_symbol_map, get_mid_price, get_open_orders, get_spot_balances, get_user_state, get_spot_meta, normalize_spot_coin, pretty_float
from bot.config import settings
import logging
import time
import html

router = Router()
logger = logging.getLogger(__name__)


def _main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/balance"), KeyboardButton(text="/orders")],
            [KeyboardButton(text="/pnl"), KeyboardButton(text="/market")],
            [KeyboardButton(text="/watchlist"), KeyboardButton(text="/price")],
            [KeyboardButton(text="/add_wallet"), KeyboardButton(text="/lang")],
            [KeyboardButton(text="/help")],
        ],
        resize_keyboard=True,
    )


def _t(lang: str, key: str) -> str:
    l = (lang or "ru").lower()
    ru = {
        "welcome": "Привет! Это <b>Velox</b> — бот для watch-only мониторинга Spot на Hyperliquid.",
        "set_wallet": "Используй /add_wallet <code>0x...</code>, чтобы начать отслеживание кошелька.",
        "need_wallet": "Сначала добавь кошелёк через /add_wallet",
        "usage_add_wallet": "Использование: /add_wallet <code>0x...</code>",
        "invalid_address": "Неверный формат адреса. Должен быть 0x...",
        "tracking": "Отслеживаю кошелёк:",
        "help": (
            "🤖 <b>Velox</b> — watch-only бот для <b>Hyperliquid Spot</b>.\n\n"
            "<b>Что умеет:</b>\n"
            "- 🟢/🔴 Уведомления о fills (покупка/продажа)\n"
            "- ⚠️ Proximity alerts по лимиткам (BUY/SELL, % и $ thresholds)\n"
            "- 🧾 /orders — открытые лимитки (to fill / edge / 🎯)\n"
            "- 🧮 /pnl — Realized PnL за 24h/7d/30d (best-effort)\n"
            "- 📊 /market — движения/вола BTC/ETH\n"
            "- 👀 watchlist + price-move alerts\n\n"
            "<b>Как начать (быстро):</b>\n"
            "1) /add_wallet <code>0x...</code>\n"
            "2) /balance и /orders\n"
            "3) (опц.) /watch BTC или /watch ETH\n\n"
            "<b>Важно про PnL:</b>\n"
            "- uPnL берём из текущих балансов + Avg Entry (если API отдаёт)\n"
            "- Realized считается по recorded fills в Mongo — если бот был offline, PnL может быть неполным\n"
            "- Никаких приватных ключей: бот <b>не</b> торгует, только мониторит\n\n"
            "<b>Команды:</b>\n"
            "/start — меню\n"
            "/add_wallet <code>0x...</code> — добавить кошелёк\n"
            "/balance — баланс/uPnL/Realized + доли портфеля\n"
            "/orders — открытые лимитки\n"
            "/pnl — Realized по периодам 24h/7d/30d\n"
            "/price [symbol] — цена (без символа покажет market)\n"
            "/market — BTC/ETH moves+vol\n"
            "/watch <code>SYMBOL</code> | /unwatch <code>SYMBOL</code> | /watchlist\n"
            "/lang — язык"
        ),
        "lang_title": "🌍 <b>Выбор языка</b>",
        "lang_set_ru": "✅ Язык установлен: Русский",
        "lang_set_en": "✅ Language set: English",
        "unknown_symbol": "Неизвестный символ:",
        "market_not_ready": "Рынок ещё не готов — подожди пару секунд.",
        "no_open_orders": "Открытых ордеров не найдено.",
        "price_usage": "Использование: /price <code>SYMBOL</code>",
        "watch_usage": "Использование: /watch <code>SYMBOL</code>",
        "unwatch_usage": "Использование: /unwatch <code>SYMBOL</code>",
        "watch_added": "✅ Добавил в watchlist:",
        "watch_removed": "🗑️ Убрал из watchlist:",
        "balance_title": "🏦 <b>Spot Balances</b>",
        "totals_title": "📊 <b>Totals</b>",
        "pnl_title": "🧮 <b>PnL Summary</b>",
        "pnl_note": "<i>Note: Realized — best-effort из записанных fills. Если бот был offline — история может быть неполной.</i>",
        "current_upl": "📌 <b>Current uPnL snapshot</b>",
        "portfolio_ex_usdc": "Portfolio (ex-USDC):",
        "market_title": "📊 <b>Market (Spot mids)</b>",
        "watchlist_title": "👀 <b>Watchlist</b>",
    }
    en = {
        "welcome": "Hi! This is <b>Velox</b> — a watch-only Spot monitoring bot for Hyperliquid.",
        "set_wallet": "Use /add_wallet <code>0x...</code> to start tracking a wallet.",
        "need_wallet": "Please set a wallet first with /add_wallet",
        "usage_add_wallet": "Usage: /add_wallet <code>0x...</code>",
        "invalid_address": "Invalid address format. Must be 0x...",
        "tracking": "Tracking wallet:",
        "help": (
            "🤖 <b>Velox</b> is a watch-only bot for <b>Hyperliquid Spot</b>.\n\n"
            "<b>What it does:</b>\n"
            "- 🟢/🔴 Fill notifications (buy/sell)\n"
            "- ⚠️ Proximity alerts for limit orders (BUY/SELL, % and $ thresholds)\n"
            "- 🧾 /orders — open limits (to fill / edge / 🎯)\n"
            "- 🧮 /pnl — Realized PnL for 24h/7d/30d (best-effort)\n"
            "- 📊 /market — BTC/ETH moves & volatility\n"
            "- 👀 watchlist + price-move alerts\n\n"
            "<b>Quick start:</b>\n"
            "1) /add_wallet <code>0x...</code>\n"
            "2) /balance and /orders\n"
            "3) (opt.) /watch BTC or /watch ETH\n\n"
            "<b>Important about PnL:</b>\n"
            "- uPnL comes from current balances + Avg Entry (if API provides it)\n"
            "- Realized is calculated from recorded fills in Mongo; if the bot was offline, it may be incomplete\n"
            "- No private keys: the bot does <b>not</b> trade, it only monitors\n\n"
            "<b>Commands:</b>\n"
            "/start — menu\n"
            "/add_wallet <code>0x...</code> — track wallet\n"
            "/balance — balances/uPnL/Realized + portfolio %\n"
            "/orders — open limit orders\n"
            "/pnl — Realized by periods 24h/7d/30d\n"
            "/price [symbol] — price (no symbol shows market)\n"
            "/market — BTC/ETH moves+vol\n"
            "/watch <code>SYMBOL</code> | /unwatch <code>SYMBOL</code> | /watchlist\n"
            "/lang — language"
        ),
        "lang_title": "🌍 <b>Language</b>",
        "lang_set_ru": "✅ Язык установлен: Русский",
        "lang_set_en": "✅ Language set: English",
        "unknown_symbol": "Unknown symbol:",
        "market_not_ready": "Market data is not ready yet — wait a bit.",
        "no_open_orders": "No open orders found.",
        "price_usage": "Usage: /price <code>SYMBOL</code>",
        "watch_usage": "Usage: /watch <code>SYMBOL</code>",
        "unwatch_usage": "Usage: /unwatch <code>SYMBOL</code>",
        "watch_added": "✅ Added to watchlist:",
        "watch_removed": "🗑️ Removed from watchlist:",
        "balance_title": "🏦 <b>Spot Balances</b>",
        "totals_title": "📊 <b>Totals</b>",
        "pnl_title": "🧮 <b>PnL Summary</b>",
        "pnl_note": "<i>Note: Realized is best-effort from recorded fills. If the bot was offline, history may be incomplete.</i>",
        "current_upl": "📌 <b>Current uPnL snapshot</b>",
        "portfolio_ex_usdc": "Portfolio (ex-USDC):",
        "market_title": "📊 <b>Market (Spot mids)</b>",
        "watchlist_title": "👀 <b>Watchlist</b>",
    }
    table = ru if l == "ru" else en
    return table.get(key, key)

# We need a reference to ws_manager to subscribe new wallets
# We can inject it or access it via bot instance if we attach it there.
# For simplicity, we'll assume it's attached to the bot instance in main.py as `bot.ws_manager`

@router.message(Command("start"))
async def cmd_start(message: Message):
    lang = await db.get_lang(message.chat.id)
    await message.answer(
        _t(lang, "welcome") + "\n" + _t(lang, "set_wallet"),
        reply_markup=_main_keyboard(),
        parse_mode="HTML",
    )
    # Save user with no wallet yet
    await db.add_user(message.chat.id, None)


@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = await db.get_lang(message.chat.id)
    await message.answer(
        _t(lang, "help"),
        reply_markup=_main_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("lang"))
async def cmd_lang(message: Message):
    lang = await db.get_lang(message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Русский", callback_data="lang:ru")
    kb.button(text="English", callback_data="lang:en")
    kb.adjust(2)
    await message.answer(_t(lang, "lang_title"), reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(callback):
    try:
        new_lang = callback.data.split(":", 1)[1]
    except Exception:
        new_lang = "ru"
    await db.set_lang(callback.message.chat.id, new_lang)
    lang = await db.get_lang(callback.message.chat.id)
    text = _t(lang, "lang_set_ru") if lang == "ru" else _t(lang, "lang_set_en")
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


@router.message(Command("market"))
async def cmd_market(message: Message):
    lang = await db.get_lang(message.chat.id)
    symbols = ["BTC", "ETH"]
    if not hasattr(message.bot, "ws_manager"):
        await message.answer(_t(lang, "market_not_ready"))
        return

    lines = []
    for sym in symbols:
        snap = message.bot.ws_manager.get_market_snapshot(sym)
        if not snap:
            # fallback: current only
            px = message.bot.ws_manager.get_price(sym) or await get_mid_price(sym)
            if px:
                lines.append(f"\n<b>{sym}</b> ${pretty_float(px, 4)}")
            continue

        def fmt(x):
            return "n/a" if x is None else f"{x:+.2f}%"

        lines.append(
            "\n" +
            f"<b>{sym}</b> <b>${pretty_float(snap['px'], 4)}</b>\n"
            f"Moves: 1m {fmt(snap['chg_1m'])} | 5m {fmt(snap['chg_5m'])} | 15m {fmt(snap['chg_15m'])}\n"
            f"Vol: 1m {fmt(snap['vol_1m'])} | 5m {fmt(snap['vol_5m'])} | 15m {fmt(snap['vol_15m'])}"
        )

    msg = _t(lang, "market_title") + "\n" + "\n".join(lines)
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message):
    lang = await db.get_lang(message.chat.id)
    wl = await db.get_watchlist(message.chat.id)
    if not wl:
        wl = ["BTC", "ETH"]
    msg = _t(lang, "watchlist_title") + "\n" + "\n".join([f"- {x}" for x in wl])
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("watch"))
async def cmd_watch(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "watch_usage"))
        return
    sym = args[1].upper()

    # Validate symbol exists
    px = 0.0
    if hasattr(message.bot, "ws_manager"):
        px = message.bot.ws_manager.get_price(sym)
    if not px:
        px = await get_mid_price(sym)
    if not px:
        await message.answer(f"{_t(lang, 'unknown_symbol')} {sym}")
        return

    await db.add_watch_symbol(message.chat.id, sym)
    if hasattr(message.bot, "ws_manager"):
        message.bot.ws_manager.watch_subscribers[sym].add(message.chat.id)
    await message.answer(f"{_t(lang, 'watch_added')} <b>{sym}</b>", parse_mode="HTML")


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "unwatch_usage"))
        return
    sym = args[1].upper()
    await db.remove_watch_symbol(message.chat.id, sym)
    if hasattr(message.bot, "ws_manager"):
        if sym in message.bot.ws_manager.watch_subscribers:
            message.bot.ws_manager.watch_subscribers[sym].discard(message.chat.id)
    await message.answer(f"{_t(lang, 'watch_removed')} <b>{sym}</b>", parse_mode="HTML")
async def cmd_pnl(message: Message):
    lang = await db.get_lang(message.chat.id)
    wallets = await db.list_wallets(message.chat.id)
    if not wallets:
        await message.answer(_t(lang, "need_wallet"))
        return

    now = time.time()

    async def realized_window(wallet: str, start_ts: float, end_ts: float):
        warm_fills = await db.get_fills_before(wallet, start_ts)
        window_fills = await db.get_fills_range(wallet, start_ts, end_ts)

        qty: dict[str, float] = {}
        cost: dict[str, float] = {}

        def is_buy(side: str) -> bool:
            s = (side or "").lower()
            return s in ("b", "buy", "bid")

        def apply_fill(f: dict, count_realized: bool):
            coin = normalize_spot_coin(f.get("coin"))
            if not coin:
                return 0.0, 0.0, 0.0
            try:
                sz = float(f.get("sz", 0) or 0)
                px = float(f.get("px", 0) or 0)
            except (TypeError, ValueError):
                return 0.0, 0.0, 0.0

            val = sz * px
            side = str(f.get("side", ""))
            if is_buy(side):
                qty[coin] = qty.get(coin, 0.0) + sz
                cost[coin] = cost.get(coin, 0.0) + val
                return 0.0, val, 0.0

            # sell
            q = qty.get(coin, 0.0)
            c = cost.get(coin, 0.0)
            if q <= 0:
                return 0.0, 0.0, val
            sell_sz = min(sz, q)
            avg_cost = c / q if q else 0.0
            pnl = sell_sz * (px - avg_cost) if count_realized else 0.0
            qty[coin] = q - sell_sz
            cost[coin] = c - avg_cost * sell_sz
            return pnl, 0.0, val

        # Warm-up
        for f in warm_fills:
            apply_fill(f, False)

        realized = 0.0
        bought = 0.0
        sold = 0.0
        per_coin_realized: dict[str, float] = {}
        for f in window_fills:
            pnl, b, s = apply_fill(f, True)
            realized += pnl
            bought += b
            sold += s
            if pnl:
                coin = normalize_spot_coin(f.get("coin"))
                per_coin_realized[coin] = per_coin_realized.get(coin, 0.0) + pnl

        return realized, bought, sold, per_coin_realized

    periods = [
        ("24h", now - 24 * 3600),
        ("7d", now - 7 * 24 * 3600),
        ("30d", now - 30 * 24 * 3600),
    ]

    lines = []
    total_realized_24h = 0.0
    total_realized_7d = 0.0
    total_realized_30d = 0.0
    for wallet in wallets:
        lines.append(f"\n👛 <b>{wallet[:6]}...{wallet[-4:]}</b>")
        for label, start_ts in periods:
            realized, bought, sold, _ = await realized_window(wallet, start_ts, now)
            sign = "+" if realized >= 0 else "-"
            lines.append(f"{label}: {sign}${abs(realized):.2f}")
            if label == "24h":
                total_realized_24h += realized
            elif label == "7d":
                total_realized_7d += realized
            elif label == "30d":
                total_realized_30d += realized

    # Current uPnL snapshot across all wallets
    total_value = 0.0
    total_upl = 0.0
    for wallet in wallets:
        balances = await get_spot_balances(wallet)
        if not balances:
            continue
        for b in balances:
            coin = b.get("coin")
            norm_coin = normalize_spot_coin(coin)
            amount = float(b.get("total", 0) or 0)
            if not coin or amount <= 0:
                continue
            mid = 0.0
            if hasattr(message.bot, "ws_manager"):
                mid = message.bot.ws_manager.get_price(norm_coin)
            if not mid:
                mid = await get_mid_price(norm_coin)
            if not mid:
                continue
            val = amount * mid
            total_value += val
            avg = extract_avg_entry_from_balance(b)
            if avg:
                total_upl += (mid - avg) * amount

    upl_sign = "+" if total_upl >= 0 else "-"
    msg = _t(lang, "pnl_title") + "\n" + "\n".join(lines)
    msg += (
        f"\n\n{_t(lang, 'current_upl')}\n"
        f"{_t(lang, 'portfolio_ex_usdc')} <b>${total_value:.2f}</b>\n"
        f"uPnL: <b>{upl_sign}${abs(total_upl):.2f}</b>\n"
        f"{_t(lang, 'pnl_note')}"
    )
    await message.answer(msg, parse_mode="HTML")

@router.message(Command("add_wallet"))
async def cmd_add_wallet(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer(_t(lang, "usage_add_wallet"))
        return
    
    wallet = args[1].lower()
    # Basic validation (Hyperliquid addresses are 0x...)
    if not wallet.startswith("0x") or len(wallet) != 42:
         await message.answer(_t(lang, "invalid_address"))
         return
         
    await db.add_wallet(message.chat.id, wallet)
    
    # Trigger WS subscription
    if hasattr(message.bot, "ws_manager"):
        message.bot.ws_manager.track_wallet(wallet)
        await message.bot.ws_manager.subscribe_user(wallet)
        
    await message.answer(f"{_t(lang, 'tracking')} {wallet}")


@router.message(Command("remove_wallet"))
async def cmd_remove_wallet(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /remove_wallet <address>")
        return
    wallet = args[1].lower()
    if not wallet.startswith("0x") or len(wallet) != 42:
        await message.answer(_t(lang, "invalid_address"))
        return
    await db.remove_wallet(message.chat.id, wallet)
    if hasattr(message.bot, "ws_manager"):
        message.bot.ws_manager.untrack_wallet(wallet)
    await message.answer(f"🗑️ Removed wallet {wallet}")


@router.message(Command("list_wallets"))
async def cmd_list_wallets(message: Message):
    wallets = await db.list_wallets(message.chat.id)
    if not wallets:
        await message.answer("No wallets added. Use /add_wallet <address> to start.")
        return
    lines = [f"- {w[:6]}...{w[-4:]}" for w in wallets]
    await message.answer("👛 <b>Your wallets</b>\n" + "\n".join(lines), parse_mode="HTML")

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    lang = await db.get_lang(message.chat.id)
    wallets = await db.list_wallets(message.chat.id)
    if not wallets:
        await message.answer(_t(lang, "need_wallet"))
        return

    lines = []
    total_value = 0.0
    total_unrealized = 0.0
    total_realized = 0.0

    for wallet in wallets:
        balances = await get_spot_balances(wallet)
        if not balances:
            continue

        # Compute per-coin stats from stored fills (best-effort)
        rows = []
        wallet_total = 0.0
        wallet_unrealized = 0.0
        wallet_realized = 0.0

        for bal in balances:
            coin = bal.get("coin")
            norm_coin = normalize_spot_coin(coin)
            amount = float(bal.get("total", 0) or 0)
            if not coin or amount <= 0:
                continue

            price = 0.0
            if hasattr(message.bot, "ws_manager"):
                price = message.bot.ws_manager.get_price(norm_coin)
            if not price:
                price = await get_mid_price(norm_coin)

            value = amount * price
            wallet_total += value
            rows.append((bal, norm_coin, amount, price, value))

        # Build per-wallet output
        wallet_lines = []
        for bal, norm_coin, amount, price, value in rows:
            share = (value / wallet_total * 100.0) if wallet_total else 0.0

            avg_entry = extract_avg_entry_from_balance(bal)
            realized = 0.0
            if avg_entry and price:
                realized = (price - avg_entry) * amount
                wallet_realized += realized

            pnl = (price - avg_entry) * amount if avg_entry else 0.0
            wallet_unrealized += pnl

            r_sign = "+" if realized >= 0 else "-"
            pnl_sign = "+" if pnl >= 0 else "-"

            if avg_entry:
                wallet_lines.append(
                    f"<b>{norm_coin}</b> <i>({share:.1f}%)</i>\n"
                    f"Amount: <code>{amount:.6f}</code>\n"
                    f"Value: <b>${value:.2f}</b> (mid ${pretty_float(price, 6)})\n"
                    f"Avg Entry: <b>${pretty_float(avg_entry, 6)}</b>\n"
                    f"uPnL: <b>{pnl_sign}${abs(pnl):.2f}</b>\n"
                    f"Realized: <b>{r_sign}${abs(realized):.2f}</b>\n"
                )
            else:
                wallet_lines.append(
                    f"<b>{norm_coin}</b> <i>({share:.1f}%)</i>\n"
                    f"Amount: <code>{amount:.6f}</code>\n"
                    f"Value: <b>${value:.2f}</b> (mid ${pretty_float(price, 6)})\n"
                    f"Realized: <b>{r_sign}${abs(realized):.2f}</b>\n"
                )

        wallet_header = f"\n👛 <b>{wallet[:6]}...{wallet[-4:]}</b>\n"
        lines.append(wallet_header + "\n".join(wallet_lines))

        total_value += wallet_total
        total_unrealized += wallet_unrealized
        total_realized += wallet_realized

    msg = _t(lang, "balance_title") + "\n" + "\n".join(lines)
    msg += (
        f"\n\n{_t(lang, 'totals_title')}\n"
        f"Total Value: <b>${total_value:.2f}</b>\n"
        f"Total uPnL (best-effort): <b>{'+' if total_unrealized >= 0 else '-'}${abs(total_unrealized):.2f}</b>\n"
        f"Total Realized (best-effort): <b>{'+' if total_realized >= 0 else '-'}${abs(total_realized):.2f}</b>"
    )
    await message.answer(msg, parse_mode="HTML")
@router.message(Command("orders"))
async def cmd_orders(message: Message):
    lang = await db.get_lang(message.chat.id)
    wallets = await db.list_wallets(message.chat.id)
    if not wallets:
        await message.answer(_t(lang, "need_wallet"))
        return

    buy_lines = []
    sell_lines = []
    for wallet in wallets:
        orders = []
        if hasattr(message.bot, "ws_manager"):
            try:
                orders = message.bot.ws_manager.get_open_orders_cached(wallet)
            except Exception:
                orders = []

        if not orders:
            data = await get_open_orders(wallet)
            if isinstance(data, dict) and isinstance(data.get("orders"), list):
                orders = data["orders"]
            elif isinstance(data, list):
                orders = data

        for order in orders:
            coin = order.get("coin")
            side = order.get("side")
            sz = float(order.get("sz", 0) or 0)
            limit_px = float(order.get("limitPx", 0) or float(order.get("limit_px", 0)) or 0)
            if not coin or sz <= 0 or limit_px <= 0:
                continue

            norm_coin = normalize_spot_coin(coin)
            mid = 0.0
            if hasattr(message.bot, "ws_manager"):
                mid = message.bot.ws_manager.get_price(norm_coin)
            if not mid:
                mid = await get_mid_price(norm_coin)

            value = sz * limit_px
            # Calculate distance from mid price
            # Positive if limit > mid (unlikely for buy unless marketable), Negative if limit < mid
            dist_pct = ((limit_px - mid) / mid * 100) if mid else 0.0
            
            if str(side).lower().startswith("b"): # Buy
                # For buy: Edge/Discount = how much lower is limit than mid?
                # If limit=90, mid=100 -> dist_pct = -10%. Edge = 10%
                edge = -dist_pct
                buy_lines.append(
                    f"{norm_coin} ${pretty_float(limit_px, 6)} x {sz:.6f} (${value:.2f})\n"
                    f"Dist: {dist_pct:+.2f}%"
                )
            else: # Sell
                # For sell: Profit/Premium = how much higher is limit than mid?
                # If limit=110, mid=100 -> dist_pct = +10%. Profit = 10%
                profit = dist_pct
                sell_lines.append(
                    f"{norm_coin} ${pretty_float(limit_px, 6)} x {sz:.6f} (${value:.2f})\n"
                    f"Dist: {dist_pct:+.2f}%"
                )

    if not buy_lines and not sell_lines:
        await message.answer(_t(lang, "no_open_orders"))
        return

    msg = "🧾 <b>Open Orders</b>\n"
    if buy_lines:
        msg += "\n🟢 <b>Buy</b>\n" + "\n".join(buy_lines) + "\n"
    if sell_lines:
        msg += "\n🔴 <b>Sell</b>\n" + "\n".join(sell_lines) + "\n"

    await message.answer(msg, parse_mode="HTML")

@router.message(Command("price"))
async def cmd_price(message: Message):
    lang = await db.get_lang(message.chat.id)
    args = message.text.split()
    if len(args) < 2:
        # Market dashboard
        symbols = ["BTC", "ETH", "HYPE", "SOL"]
        lines = []
        freshness = ""
        if hasattr(message.bot, "ws_manager"):
            ts = getattr(message.bot.ws_manager, "last_mids_update_ts", 0.0)
            if ts:
                age = max(0.0, __import__("time").time() - ts)
                freshness = f" (ws age {age:.0f}s)"

        for s in symbols:
            px = 0.0
            if hasattr(message.bot, "ws_manager"):
                px = message.bot.ws_manager.get_price(s)
            if not px:
                px = await get_mid_price(s)
            if px:
                lines.append(f"- <b>{s}</b>: ${pretty_float(px, 4)}")

        msg = "📈 <b>Market</b>" + freshness + "\n" + "\n".join(lines)
        msg += "\n\n" + _t(lang, "price_usage")
        await message.answer(msg, parse_mode="HTML")
        return

    symbol = args[1].upper()
    safe_symbol = html.escape(symbol)

    price = 0.0
    if hasattr(message.bot, "ws_manager"):
        price = message.bot.ws_manager.get_price(symbol)

    if not price:
        price = await get_mid_price(symbol)

    if price:
        await message.answer(f"<b>{safe_symbol}</b>: ${pretty_float(price, 6)}", parse_mode="HTML")
    else:
        await message.answer(f"Price for {safe_symbol} not available (or invalid symbol).", parse_mode="HTML")
