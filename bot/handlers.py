from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from bot.database import db
from bot.services import get_user_state, get_spot_meta
from bot.config import settings
import logging

router = Router()
logger = logging.getLogger(__name__)

# We need a reference to ws_manager to subscribe new wallets
# We can inject it or access it via bot instance if we attach it there.
# For simplicity, we'll assume it's attached to the bot instance in main.py as `bot.ws_manager`

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Welcome to the Hyperliquid Watcher Bot!\n"
        "Use /add_wallet <address> to start tracking a wallet."
    )
    # Save user with no wallet yet
    await db.add_user(message.chat.id, None)

@router.message(Command("add_wallet"))
async def cmd_add_wallet(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /add_wallet <address>")
        return
    
    wallet = args[1]
    # Basic validation (Hyperliquid addresses are 0x...)
    if not wallet.startswith("0x") or len(wallet) != 42:
         await message.answer("Invalid address format. Must be 0x...")
         return
         
    await db.add_user(message.chat.id, wallet)
    
    # Trigger WS subscription
    if hasattr(message.bot, "ws_manager"):
        message.bot.ws_manager.track_wallet(wallet)
        await message.bot.ws_manager.subscribe_user(wallet)
        
    await message.answer(f"Tracking wallet: {wallet}")

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    user = await db.get_user(message.chat.id)
    if not user or not user.get("wallet_address"):
        await message.answer("Please set a wallet first with /add_wallet")
        return
        
    wallet = user.get("wallet_address")
    state = await get_user_state(wallet)
    
    if not state:
        await message.answer("Could not fetch balances.")
        return

    # Check for Spot Balances
    # clearinghouseState has `balances` for spot? 
    # Actually `clearinghouseState` is usually for perps.
    # For Spot, we might need `spotClearinghouseState` or parse `balances` from state if it's unified.
    # The docs for `clearinghouseState` say "withdrawable", "assetPositions" (Perps).
    # Spot balances are often in `balances` list in the response if it's the unified account or separate.
    # Let's check `spotClearinghouseState` via info endpoint if `clearinghouseState` doesn't have it.
    # But usually, `clearinghouseState` is for the Perp account.
    # The Hyperliquid API usually separates Spot and Perp states.
    # I should use `spotClearinghouseState` type for info request if available.
    # If not, I'll rely on what `get_user_state` returns. 
    # Let's modify `services.py` to try `spotClearinghouseState` if I suspect it exists, 
    # but based on docs `spotClearinghouseState` is likely the one for Spot.
    
    # Assuming `state` contains `balances` (Spot)
    balances = state.get("balances", []) # List of { coin: str, total: str, ... }
    
    if not balances:
         await message.answer("No spot balances found or incorrect state type fetched.")
         return

    msg = "<b>Spot Balances:</b>\n"
    for bal in balances:
        coin = bal.get("coin")
        amount = float(bal.get("total", 0))
        if amount > 0:
            # We could fetch price to show value
            # access mid_prices from ws_manager if possible
            price = 0
            if hasattr(message.bot, "ws_manager"):
                price = message.bot.ws_manager.mid_prices.get(coin, 0)
            
            value = amount * price
            msg += f"- {coin}: {amount:.4f} (${value:.2f})\n"
            
    await message.answer(msg, parse_mode="HTML")

@router.message(Command("price"))
async def cmd_price(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /price <symbol> (e.g. ETH, HYPE)")
        return
        
    symbol = args[1].upper()
    
    price = 0
    if hasattr(message.bot, "ws_manager"):
        price = message.bot.ws_manager.mid_prices.get(symbol)
        
    if price:
        await message.answer(f"{symbol}: ${price}")
    else:
        await message.answer(f"Price for {symbol} not available (or invalid symbol).")
