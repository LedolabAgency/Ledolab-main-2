from __future__ import annotations

import asyncio
import logging
import time
import traceback
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.config import ADMIN_IDS

logger = logging.getLogger(__name__)
KYIV_TZ = ZoneInfo("Europe/Kiev")

ALERT_COOLDOWN_SECONDS = 300
_last_alerts: dict[str, float] = {}


def _is_on_cooldown(key: str) -> bool:
    now = time.time()
    last_sent = _last_alerts.get(key)
    if last_sent is not None and now - last_sent < ALERT_COOLDOWN_SECONDS:
        return True
    _last_alerts[key] = now
    return False


async def notify_admins_about_error(bot: Bot | None, place: str, error: Exception) -> None:
    if bot is None or not ADMIN_IDS:
        return

    error_key = f"{place}:{type(error).__name__}:{str(error)[:120]}"
    if _is_on_cooldown(error_key):
        return

    now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M:%S")
    text = (
        "🚨 <b>LedoLab Error</b>\n\n"
        f"📍 Место: <code>{escape(place)}</code>\n"
        f"🧨 Тип: <code>{escape(type(error).__name__)}</code>\n"
        f"📝 Ошибка: <code>{escape(str(error)[:700])}</code>\n"
        f"🕓 Время: <code>{escape(now)}</code>"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as send_error:
            logger.debug("Failed to send admin alert to %s: %s", admin_id, send_error)


class TelegramLogHandler(logging.Handler):
    """Forwards every ERROR+ log record from anywhere in the app to ADMIN_IDS in Telegram.

    Centralizes monitoring so existing `logger.error(..., exc_info=True)` calls scattered
    across handlers don't need to be touched one by one.
    """

    def __init__(self, bot: Bot) -> None:
        super().__init__(level=logging.ERROR)
        self._bot = bot

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == __name__:
            return  # never re-notify about our own send failures

        message = record.getMessage()
        if "Conflict: terminated by other getUpdates request" in message:
            return  # harmless overlap between old/new instance during a redeploy

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify(record))

    async def _notify(self, record: logging.LogRecord) -> None:
        key = f"log:{record.name}:{record.funcName}:{record.lineno}"
        if _is_on_cooldown(key):
            return

        now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M:%S")
        emoji = "🔥" if record.levelno >= logging.CRITICAL else "🚨"
        location = f"{record.name} → {record.funcName}() : {record.filename}:{record.lineno}"

        parts = [
            f"{emoji} <b>LedoLab Error</b>\n",
            f"📍 Место: <code>{escape(location)}</code>",
            f"📝 {escape(record.getMessage()[:700])}",
        ]

        if record.exc_info:
            tb = "".join(traceback.format_exception(*record.exc_info))
            parts.append(f"\n<pre>{escape(tb[-2500:])}</pre>")

        parts.append(f"\n🕓 {now}")
        text = "\n".join(parts)[:4000]

        for admin_id in ADMIN_IDS:
            try:
                await self._bot.send_message(admin_id, text)
            except Exception as send_error:
                logger.debug("Failed to send admin log alert to %s: %s", admin_id, send_error)


def attach_telegram_log_handler(bot: Bot) -> None:
    """Call once at startup to forward all ERROR+ logs from the whole app to ADMIN_IDS."""
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS is empty — Telegram error monitoring is disabled.")
        return

    root_logger = logging.getLogger()
    if any(isinstance(h, TelegramLogHandler) for h in root_logger.handlers):
        return

    root_logger.addHandler(TelegramLogHandler(bot))
    logger.info("🛡️ Telegram error monitoring attached for admins: %s", ADMIN_IDS)
