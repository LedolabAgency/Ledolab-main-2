from __future__ import annotations

import logging
import time
from datetime import datetime
from html import escape

from aiogram import Bot

from app.config import ADMIN_IDS

logger = logging.getLogger(__name__)

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

    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
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
