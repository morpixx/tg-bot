from __future__ import annotations

import asyncio
import logging

import structlog
from aiogram.types import BotCommand

from bot.core.bot import bot
from bot.core.config import settings
from bot.core.dispatcher import create_dispatcher


def setup_logging() -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


async def _register_commands() -> None:
    """Populate the Telegram hamburger-menu commands."""
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="menu", description="🏠 Главное меню"),
        BotCommand(command="cancel", description="❌ Отменить текущее действие"),
    ])


async def main() -> None:
    setup_logging()
    log = structlog.get_logger()
    log.info("Starting bot")

    dp = create_dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    await _register_commands()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
