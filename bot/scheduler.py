from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.database import db
from bot.services import get_spot_balances
from bot.config import settings
import time
import logging

logger = logging.getLogger(__name__)

def _is_buy(side: str) -> bool:
    s = (side or "").lower()
    return s in ("b", "buy", "bid")

def _calc_coin_avg_entry_from_fills(fills: list[dict]) -> float:
    if not fills:
        return 0.0

    fills_sorted = sorted(fills, key=lambda x: float(x.get("time", 0)))
    qty = 0.0
    cost = 0.0
    for f in fills_sorted:
        sz = float(f.get("sz", 0) or 0)
        px = float(f.get("px", 0) or 0)
        if _is_buy(str(f.get("side", ""))):
            qty += sz
            cost += sz * px
        else:
            if qty <= 0:
                continue
            sell_sz = min(sz, qty)
            avg_cost = cost / qty if qty else 0.0
            qty -= sell_sz
            cost -= avg_cost * sell_sz

    if qty > 0 and cost > 0:
        return cost / qty
    return 0.0

async def send_weekly_summary(bot):
    """Generate and send weekly summary to all users."""
    logger.info("Generating weekly summary...")
    users = await db.get_all_users()
    
    end_time = time.time()
    start_time = end_time - (7 * 24 * 60 * 60) # 7 days ago
    
    for user in users:
        chat_id = user.get("chat_id")
        wallet = user.get("wallet_address")
        
        if not wallet: continue
        
        fills = await db.get_fills(wallet, start_time, end_time)

        # Realized PnL (weekly): compute per-coin moving average cost, accumulate sell pnl.
        realized_pnl = 0.0
        total_bought_val = 0.0
        total_sold_val = 0.0
        per_coin_qty: dict[str, float] = {}
        per_coin_cost: dict[str, float] = {}

        fills_sorted = sorted(fills, key=lambda x: float(x.get("time", 0)))
        for fill in fills_sorted:
            coin = fill.get("coin")
            if not isinstance(coin, str) or not coin:
                continue

            sz = float(fill.get("sz", 0) or 0)
            px = float(fill.get("px", 0) or 0)
            val = sz * px
            side = str(fill.get("side", ""))

            if _is_buy(side):
                total_bought_val += val
                per_coin_qty[coin] = per_coin_qty.get(coin, 0.0) + sz
                per_coin_cost[coin] = per_coin_cost.get(coin, 0.0) + val
            else:
                total_sold_val += val
                qty = per_coin_qty.get(coin, 0.0)
                cost = per_coin_cost.get(coin, 0.0)
                if qty <= 0:
                    continue
                sell_sz = min(sz, qty)
                avg_cost = cost / qty if qty else 0.0
                realized_pnl += sell_sz * (px - avg_cost)
                per_coin_qty[coin] = qty - sell_sz
                per_coin_cost[coin] = cost - avg_cost * sell_sz

        net_flow = total_sold_val - total_bought_val

        # Unrealized PnL: current holdings value vs avg entry derived from stored fills.
        unrealized_msg = ""
        balances = await get_spot_balances(wallet)
        if balances:
            total_current_value = 0.0
            total_unrealized_pnl = 0.0
            holdings_details = []
            for bal in balances:
                coin = bal.get("coin")
                amount = float(bal.get("total", 0) or 0)
                if not coin or amount <= 0:
                    continue

                price = 0.0
                if hasattr(bot, "ws_manager"):
                    price = bot.ws_manager.get_price(coin)
                val = amount * price
                total_current_value += val

                avg_entry = 0.0
                try:
                    coin_fills = await db.get_fills_by_coin(wallet, coin)
                    avg_entry = _calc_coin_avg_entry_from_fills(coin_fills)
                except Exception:
                    avg_entry = 0.0

                upl = (price - avg_entry) * amount if avg_entry else 0.0
                total_unrealized_pnl += upl
                if avg_entry:
                    holdings_details.append(f"- {coin}: ${val:.2f} | Avg: ${avg_entry:.6f} | uPnL: ${upl:.2f}")
                else:
                    holdings_details.append(f"- {coin}: ${val:.2f}")

            unrealized_msg = (
                f"\n💰 <b>Holdings:</b> ${total_current_value:.2f}\n"
                f"📈 <b>Unrealized PnL (best-effort):</b> ${total_unrealized_pnl:.2f}\n"
                + "\n".join(holdings_details)
            )

        msg = (
            f"📅 <b>Velox — Weekly Summary</b>\n"
            f"Wallet: {wallet[:6]}...{wallet[-4:]}\n\n"
            f"<b>Weekly Flow:</b>\n"
            f"Total Bought: ${total_bought_val:.2f}\n"
            f"Total Sold: ${total_sold_val:.2f}\n"
            f"Net Flow: ${net_flow:.2f} (Sold - Bought)\n"
            f"\n<b>Realized PnL (best-effort):</b> ${realized_pnl:.2f}\n"
            f"{unrealized_msg}\n\n"
            f"<i>Note: PnL is best-effort from stored fills and may be incomplete if the bot was offline.</i>"
        )
        
        try:
            await bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send summary to {chat_id}: {e}")

def setup_scheduler(bot):
    scheduler = AsyncIOScheduler()
    # Schedule every Sunday at 23:59 UTC
    scheduler.add_job(
        send_weekly_summary, 
        'cron', 
        day_of_week='sun', 
        hour=23, 
        minute=59, 
        args=[bot]
    )
    scheduler.start()
    return scheduler
