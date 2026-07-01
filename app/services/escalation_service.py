"""
Missed-task escalation pipeline.

A user can only have ONE unresolved daily task set at a time (database.py
blocks creating a new day's tasks while the previous date has no report),
so the date of an unreported task set is always the single date the user
got stuck on. We re-check that same date on day+1, day+4 and day+7 to fire
the three escalation stages, gated by a per-stage Redis lock so each stage
fires exactly once.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from aiogram import Bot, types

from app import cache, database
from app.config import ADMIN_IDS, REPORTS_GROUP_ID

logger = logging.getLogger(__name__)
KYIV_TZ = ZoneInfo("Europe/Kiev")

STAGE_OFFSET_DAYS = {1: 1, 2: 4, 3: 7}
ESCALATION_LOCK_TTL = 30 * 24 * 60 * 60


def _escalation_lock_key(telegram_id: int, stuck_date: str, stage: int) -> str:
    return f"escalation:{telegram_id}:{stuck_date}:{stage}"


def _format_task_list(tasks: list[str]) -> str:
    return "\n".join(f"• {t}" for t in tasks) if tasks else "—"


def admin_escalation_keyboard(telegram_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🥶 ОСТУДИТЬ", url=f"tg://user?id={telegram_id}")],
            [types.InlineKeyboardButton(text="🗑 УДАЛИТЬ", callback_data=f"esc_delete_ask:{telegram_id}")],
        ]
    )


async def _send_stage_reminder(bot: Bot, user: dict[str, Any], stuck_date: str, stage: int) -> None:
    telegram_id = user.get("telegram_id")
    if not telegram_id:
        return
    tasks_text = _format_task_list(user.get("tasks") or [])
    if stage == 1:
        text = (
            f"⏰ Ты не закрыл отчётом задачи за {stuck_date}:\n\n"
            f"{tasks_text}\n\n"
            "Закрой их отчётом, чтобы двигаться дальше."
        )
    else:
        text = (
            f"🥶 Уже несколько дней без отчёта по задачам за {stuck_date}:\n\n"
            f"{tasks_text}\n\n"
            "Закрой их отчётом — иначе дальше об этом узнает админ клуба."
        )
    try:
        await bot.send_message(telegram_id, text)
    except Exception as e:
        logger.warning("Failed to send escalation stage %s reminder to %s: %s", stage, telegram_id, e)


async def _send_admin_alert(bot: Bot, user: dict[str, Any], stuck_date: str, days_overdue: int) -> None:
    telegram_id = user.get("telegram_id")
    if not telegram_id or not ADMIN_IDS:
        return
    label = f"@{user['username']}" if user.get("username") else (user.get("first_name") or "Участник")
    tasks_text = _format_task_list(user.get("tasks") or [])
    text = (
        f"🥶 Юзер {label} (id <code>{telegram_id}</code>) на морозе уже {days_overdue} дней "
        f"(с {stuck_date}).\n\n"
        f"Незакрытые задачи:\n{tasks_text}\n\n"
        "Остудить или удалить?"
    )
    keyboard = admin_escalation_keyboard(telegram_id)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=keyboard)
        except Exception as e:
            logger.warning("Failed to send escalation admin alert for %s to admin %s: %s", telegram_id, admin_id, e)


async def send_escalation_reminders(bot: Bot, now: datetime | None = None) -> None:
    """Run the 3-stage escalation check: day+1, day+4 reminders, day+7 admin alert."""
    now = now or datetime.now(KYIV_TZ)
    today = now.date()

    for stage, offset in STAGE_OFFSET_DAYS.items():
        stuck_date = (today - timedelta(days=offset)).isoformat()
        users = await database.get_users_with_tasks_no_report(stuck_date)
        for user in users:
            telegram_id = user.get("telegram_id")
            if not telegram_id:
                continue
            lock_key = _escalation_lock_key(telegram_id, stuck_date, stage)
            if not await cache.acquire_lock(lock_key, ex=ESCALATION_LOCK_TTL):
                continue
            if stage == 3:
                await _send_admin_alert(bot, user, stuck_date, offset)
            else:
                await _send_stage_reminder(bot, user, stuck_date, stage)
            logger.info("Escalation stage %s sent | user=%s stuck_since=%s", stage, telegram_id, stuck_date)


async def delete_user_everywhere(bot: Bot, telegram_id: int) -> dict[str, Any]:
    """Kick the user from the club group, wipe their DB rows and clear Redis state."""
    result: dict[str, Any] = {"kicked": False, "db_stats": {}, "redis_deleted": 0}

    await cache.set_data(cache.KeyManager.get_user_reset_key(telegram_id), "1", ex=120)

    if REPORTS_GROUP_ID:
        try:
            await bot.ban_chat_member(chat_id=REPORTS_GROUP_ID, user_id=telegram_id)
            await bot.unban_chat_member(chat_id=REPORTS_GROUP_ID, user_id=telegram_id)
            result["kicked"] = True
        except Exception as e:
            logger.warning("Failed to kick %s from group %s: %s", telegram_id, REPORTS_GROUP_ID, e)

    result["db_stats"] = await database.reset_user_data(telegram_id)
    result["redis_deleted"] = await cache.delete_keys_by_patterns(
        [
            f"quiz_done:{telegram_id}",
            f"pending_referrer:{telegram_id}",
            f"goal_lock:{telegram_id}",
            f"goal_day_lock:{telegram_id}:*",
            f"day_plan_lock:{telegram_id}:*",
            f"streak:{telegram_id}",
            f"last_report_date:{telegram_id}",
            f"last_group_chat:{telegram_id}",
            f"group_welcome:{telegram_id}",
            f"group_referral_welcome:{telegram_id}",
            f"throttle:*:{telegram_id}",
            f"leda_fsm:*{telegram_id}*",
            f"route_started:{telegram_id}",
            f"goal_thinking:{telegram_id}",
            f"escalation:{telegram_id}:*",
        ]
    )
    return result
