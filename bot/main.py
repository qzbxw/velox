import asyncio
import logging
from aiogram import Bot, Dispatcher
from bot.config import settings
from bot.database import db
from bot.handlers import router
from bot.ws_manager import WSManager
from bot.scheduler import setup_scheduler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # 1. Startup Validation
    if not settings.BOT_TOKEN or ":" not in settings.BOT_TOKEN:
        logger.error("Invalid BOT_TOKEN provided in environment!")
        return

    # 2. Initialize Database
    try:
        logger.info("Initializing database...")
        await db.init_db()
        # Simple ping to verify connectivity
        await db.client.admin.command('ping')
        logger.info("Database connection verified.")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return

    # Initialize Bot
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    
    # Register Routers
    dp.include_router(router)
    
    # Initialize WS Manager
    ws_manager = WSManager(bot)
    bot.ws_manager = ws_manager
    
    # Start WS Manager in background
    ws_task = asyncio.create_task(ws_manager.start())
    
    # Setup Scheduler
    scheduler = setup_scheduler(bot)
    
    # Set Bot Commands
    from aiogram.types import BotCommand
    commands = [
        BotCommand(command="start", description="Main Menu"),
        BotCommand(command="help", description="Show Commands"),
        BotCommand(command="add_wallet", description="Track Wallet"),
        BotCommand(command="overview", description="Hedge AI Market Overview"),
        BotCommand(command="funding", description="Funding Log"),
        BotCommand(command="alert", description="Price Alert"),
        BotCommand(command="watch", description="Watchlist"),
        BotCommand(command="export", description="Export CSV"),
    ]
    await bot.set_my_commands(commands)
    
    # Start Polling
    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")
    finally:
        logger.info("Shutting down...")
        ws_manager.running = False
        if ws_task:
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass
        
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot session closed. Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
