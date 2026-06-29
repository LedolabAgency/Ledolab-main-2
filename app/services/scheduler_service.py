from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from app import cache
from app.services import community_service, escalation_service

logger = logging.getLogger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kiev")
_scheduler_task: asyncio.Task | None = None


def _is_morning_window(now: datetime) -> bool:
    return now.hour == 8 and 30 <= now.minute < 35


def _is_midday_window(now: datetime) -> bool:
    return now.hour == 13 and now.minute < 5


def _is_evening_group_window(now: datetime) -> bool:
    return now.hour == 20 and now.minute < 5


def _is_personal_evening_window(now: datetime) -> bool:
    return now.hour == 21 and now.minute < 5


def _is_weekly_final_window(now: datetime) -> bool:
    return now.weekday() == 6 and now.hour == 22 and now.minute < 5


async def _tick(bot: Bot) -> None:
    now = datetime.now(KYIV_TZ)
    today = now.date().isoformat()

    if _is_morning_window(now):
        morning_key = f"job:morning_push:{today}"
        if await cache.acquire_lock(morning_key, ex=12 * 60 * 60):
            await community_service.send_morning_private_reminders(bot, now)
            logger.info("Morning private push sent for %s", today)

        escalation_key = f"job:escalation:{today}"
        if await cache.acquire_lock(escalation_key, ex=12 * 60 * 60):
            await escalation_service.send_escalation_reminders(bot, now)
            logger.info("Escalation reminders processed for %s", today)

    if _is_midday_window(now):
        midday_key = f"job:midday_reminder:{today}"
        if await cache.acquire_lock(midday_key, ex=12 * 60 * 60):
            await community_service.send_midday_reminder(bot, now)
            logger.info("Midday group reminder sent for %s", today)

    if _is_evening_group_window(now):
        evening_key = f"job:evening_group:{today}"
        if await cache.acquire_lock(evening_key, ex=12 * 60 * 60):
            await community_service.send_evening_group_post(bot, now)
            logger.info("Evening group post sent for %s", today)

    if _is_personal_evening_window(now):
        personal_key = f"job:personal_evening:{today}"
        if await cache.acquire_lock(personal_key, ex=12 * 60 * 60):
            await community_service.send_personal_evening_reminders(bot, now)
            logger.info("Personal evening reminders sent for %s", today)

    if _is_weekly_final_window(now):
        weekly_key = f"job:weekly_final:{today}"
        if await cache.acquire_lock(weekly_key, ex=8 * 24 * 60 * 60):
            await community_service.send_weekly_final(bot, now)
            logger.info("Scheduled weekly final sent for %s", today)


async def _loop(bot: Bot) -> None:
    while True:
        try:
            await _tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Scheduler tick failed: %s", e, exc_info=True)
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
