from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.database import db
from bot.services import get_user_state
from bot.config import settings
import time
import logging

logger = logging.getLogger(__name__)

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
        
        # 1. Realized PnL from Fills (Flow)
        fills = await db.get_fills(wallet, start_time, end_time)
        
        total_bought_val = 0.0
        total_sold_val = 0.0
        
        for fill in fills:
            val = float(fill['sz']) * float(fill['px'])
            side = fill['side']
            
            if side == 'B' or side.lower() == 'buy':
                total_bought_val += val
            else:
                total_sold_val += val
        
        net_flow = total_sold_val - total_bought_val

        # 2. Unrealized PnL (Current Value vs Approximate Cost)
        # Fetch current balances
        state = await get_user_state(wallet)
        unrealized_msg = ""
        
        if state and "balances" in state:
            balances = state["balances"]
            total_current_value = 0.0
            
            # Since we don't have full history for Cost Basis, we can only report current Holdings Value
            # Or if we have some fills, we can try to estimate average entry for those fills? 
            # But that's misleading if they held before.
            # Best effort: Report Current Holdings Value.
            # "Unrealized PnL: Current value of holdings vs Entry cost"
            # Without Entry Cost, we can't do PnL.
            # We will show Current Value.
            
            holdings_details = []
            
            for bal in balances:
                coin = bal.get("coin")
                amount = float(bal.get("total", 0))
                if amount > 0:
                    # Get current price from bot memory if available
                    price = 0
                    if hasattr(bot, "ws_manager"):
                         price = bot.ws_manager.mid_prices.get(coin, 0)
                    
                    val = amount * price
                    total_current_value += val
                    holdings_details.append(f"- {coin}: ${val:.2f}")
            
            unrealized_msg = (
                f"\n💰 <b>Current Holdings Value:</b> ${total_current_value:.2f}\n" 
                + "\n".join(holdings_details)
            )

        msg = (
            f"📅 <b>Weekly Summary</b>\n"
            f"Wallet: {wallet[:6]}...{wallet[-4:]}\n\n"
            f"<b>Weekly Flow (Realized):</b>\n"
            f"Total Bought: ${total_bought_val:.2f}\n"
            f"Total Sold: ${total_sold_val:.2f}\n"
            f"Net Flow: ${net_flow:.2f} (Sold - Bought)\n"
            f"{unrealized_msg}\n\n"
            f"<i>Note: Unrealized PnL requires full history. Only current value is shown.</i>"
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
