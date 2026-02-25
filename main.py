from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path


try:
    from bot.main import main
except ModuleNotFoundError:
    # Fallback for flat deployments where files are placed directly in /app
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.fsm.storage.memory import MemoryStorage

    try:
        from admin import admin_router
        from config import load_settings
        from handlers import user_router
        from llm import NScaleClient
        from logger import ChannelLogger
        from storage import InMemoryStorage
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            'Cannot import bot modules. Use either /app/bot/* structure or flat /app/*.py structure.'
        ) from exc

    async def main() -> None:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        )

        settings = load_settings()

        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = Dispatcher(storage=MemoryStorage())

        storage = InMemoryStorage('bot_state.json')
        llm = NScaleClient(
            api_key=settings.nscale_service_token,
            model=settings.nscale_model,
            timeout_seconds=settings.request_timeout,
            base_url=settings.nscale_base_url,
            proxy_url=settings.proxy_url,
            max_tokens=settings.nscale_max_tokens,
        )
        channel_logger = ChannelLogger(bot, settings.log_channel_id)

        dp.include_router(admin_router(settings, storage, channel_logger))
        dp.include_router(user_router(settings, storage, llm, channel_logger))

        await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
