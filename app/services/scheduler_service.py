from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from app import cache
from app.services import community_service
from app.services.alert_service import notify_admins_about_error

logger = logging.getLogger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kiev")
_scheduler_task: asyncio.Task | None = None


def _is_reminder_window(now: datetime) -> bool:
    return now.hour == 20 and now.minute < 5


def _is_weekly_final_window(now: datetime) -> bool:
    return now.weekday() == 6 and now.hour == 22 and now.minute < 5


async def _tick(bot: Bot) -> None:
    now = datetime.now(KYIV_TZ)

    if _is_reminder_window(now):
        reminder_key = f"job:report_reminder:{now.date().isoformat()}"
        if await cache.acquire_lock(reminder_key, ex=12 * 60 * 60):
            await community_service.send_report_deadline_reminder(bot, now)
            logger.info("Scheduled report reminder sent for %s", now.date().isoformat())

    if _is_weekly_final_window(now):
        weekly_key = f"job:weekly_final:{now.date().isoformat()}"
        if await cache.acquire_lock(weekly_key, ex=8 * 24 * 60 * 60):
            await community_service.send_weekly_final(bot, now)
            logger.info("Scheduled weekly final sent for %s", now.date().isoformat())


async def _loop(bot: Bot) -> None:
    while True:
        try:
            await _tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Scheduler tick failed: %s", e, exc_info=True)
            await notify_admins_about_error(bot, "scheduler.tick", e)
        await asyncio.sleep(30)


async def start_scheduler(bot: Bot) -> None:
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        return
    _scheduler_task = asyncio.create_task(_loop(bot), name="ledolab-scheduler")
    logger.info("✅ Background scheduler started")


async def stop_scheduler() -> None:
    global _scheduler_task
    if not _scheduler_task:
        return
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None
