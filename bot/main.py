import asyncio
import logging
from aiogram import Bot, Dispatcher
from bot.config import settings
from bot.handlers import router
from bot.ws_manager import WSManager
from bot.scheduler import setup_scheduler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # Initialize Bot
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    
    # Register Routers
    dp.include_router(router)
    
    # Initialize WS Manager
    ws_manager = WSManager(bot)
    # Attach to bot for access in handlers (a bit hacky but effective for simple bot)
    bot.ws_manager = ws_manager
    
    # Start WS Manager in background
    ws_task = asyncio.create_task(ws_manager.start())
    
    # Setup Scheduler
    scheduler = setup_scheduler(bot)
    
    # Start Polling
    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    finally:
        ws_manager.running = False
        ws_task.cancel()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
