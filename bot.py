"""INFINITRIX SEARCH — entry point.  Run with:  python bot.py"""
from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from config import APP_NAME, ConfigError, Settings, load_settings


def setup_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.log_level, logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file_handler = RotatingFileHandler(
        settings.log_dir / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


async def main() -> None:
    settings = load_settings()
    setup_logging(settings)
    log = logging.getLogger("infinitrix")

    # Imported here so that a missing .env is reported before heavy imports.
    import aiohttp
    from aiogram import Bot, Dispatcher
    from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
    from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

    from ai_client import OpenRouterClient
    from core import AppContext
    from database import Database
    from handlers import on_error, router
    from search import SerpApiClient
    from utils import AntiSpam

    db = Database(settings.db_path)
    await db.init()

    session = aiohttp.ClientSession(headers={"User-Agent": "INFINITRIX-SEARCH/1.0"})
    ai = OpenRouterClient(
        session,
        settings.openrouter_api_key,
        settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_output_tokens,
        timeout=settings.ai_timeout_seconds,
        app_name=APP_NAME,
        app_url=settings.app_url,
    )
    search = SerpApiClient(
        session,
        settings.serpapi_key,
        timeout=settings.search_timeout_seconds,
        num_results=settings.search_results_count,
        hl=settings.serpapi_hl,
        gl=settings.serpapi_gl,
    )
    antispam = AntiSpam(
        settings.min_interval_seconds,
        settings.burst_max,
        settings.burst_window_seconds,
        settings.cooldown_seconds,
    )
    ctx = AppContext(settings=settings, db=db, ai=ai, search=search, session=session, antispam=antispam)

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp["ctx"] = ctx
    dp.include_router(router)
    dp.errors.register(on_error)

    public_commands = [
        BotCommand(command="start", description="بدء الاستخدام"),
        BotCommand(command="help", description="دليل الأوامر"),
        BotCommand(command="ask", description="سؤال مع بحث مباشر"),
        BotCommand(command="search", description="بحث الويب"),
        BotCommand(command="images", description="بحث الصور"),
        BotCommand(command="videos", description="بحث الفيديو"),
        BotCommand(command="news", description="بحث الأخبار"),
        BotCommand(command="reverse", description="بحث عكسي بالصورة"),
        BotCommand(command="autosearch", description="البحث التلقائي on/off"),
        BotCommand(command="clear", description="مسح ذاكرة المحادثة"),
        BotCommand(command="status", description="حالتي واستخدامي"),
    ]
    owner_commands = public_commands + [
        BotCommand(command="setprompt", description="(المالك) تغيير البرومبت"),
        BotCommand(command="showprompt", description="(المالك) عرض البرومبت"),
        BotCommand(command="resetprompt", description="(المالك) البرومبت الافتراضي"),
    ]

    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            log.critical("TELEGRAM_BOT_TOKEN is invalid. Check your .env file.")
            return
        log.info("Starting %s as @%s | model=%s | owner=%s | search=%s",
                 APP_NAME, me.username, settings.model, settings.owner_id,
                 "on" if search.enabled else "OFF (no SERPAPI_API_KEY)")
        if not search.enabled:
            log.warning("SERPAPI_API_KEY is empty: search commands are disabled.")

        await bot.delete_webhook(drop_pending_updates=True)
        try:
            await bot.set_my_commands(public_commands, scope=BotCommandScopeDefault())
            await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=settings.owner_id))
        except TelegramAPIError as exc:
            # e.g. the owner never opened the bot yet; commands still work.
            log.warning("Could not set the command menu: %s", exc)

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await session.close()
        await db.close()
        log.info("Bot stopped.")


def run() -> None:
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(f"\n[CONFIG ERROR] {exc}\n", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    run()
