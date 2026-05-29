"""
Main bot entry point for LedoLab.
Initializes and runs the Telegram bot.
"""

import asyncio
import logging

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder

from app.config import BOT_TOKEN, SENTRY_DSN
from app.logging_config import logger
from app.middlewares.throttle import ThrottleMiddleware
from app import database, cache
from app.handlers import start_router, quiz_router, callbacks_router, club_router
from app.services import scheduler_service

# Initialize Sentry if configured
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,
    )
    logger.info("🛡️ Sentry monitoring enabled")


async def on_startup(bot: Bot) -> None:
    """
    Startup hook - initialize database and cache.
    """
    logger.info("🚀 Bot starting up...")
    
    try:
        # Initialize Supabase
        database.init_supabase()
        logger.info("✅ Supabase initialized")
        
        logger.info("✅ Redis initialized")
        await scheduler_service.start_scheduler(bot)

        me = await bot.get_me()
        logger.info(f"✅ Bot @{me.username} is ready")
        
    except Exception as e:
        logger.error(f"❌ Startup error: {e}", exc_info=True)
        raise


async def on_shutdown(bot: Bot) -> None:
    """
    Shutdown hook - close connections.
    """
    logger.info("🛑 Bot shutting down...")
    
    try:
        await scheduler_service.stop_scheduler()
        await cache.close_redis()
        await bot.session.close()
        logger.info("✅ Connections closed")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


async def main() -> None:
    """
    Main bot entry point.
    Starts polling or webhook depending on configuration.
    """
    
    # Initialize storage
    redis_client = await cache.init_redis()
    storage = RedisStorage(
        redis=redis_client,
        key_builder=DefaultKeyBuilder(with_destiny=True, prefix="leda_fsm"),
    )
    
    # Initialize bot and dispatcher
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML",
            link_preview_is_disabled=True,
        ),
    )
    
    dp = Dispatcher(storage=storage)
    throttle = ThrottleMiddleware()
    dp.message.outer_middleware(throttle)
    dp.callback_query.outer_middleware(throttle)
    
    # Register routers
    dp.include_router(start_router)
    dp.include_router(quiz_router)
    dp.include_router(callbacks_router)
    dp.include_router(club_router)
    
    # Register lifecycle hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Start polling
    try:
        logger.info("⏳ Polling started...")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    except KeyboardInterrupt:
        logger.info("⏸️ Polling stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise
