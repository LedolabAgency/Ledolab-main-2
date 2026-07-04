"""
Missed-task escalation pipeline.

A user can only have ONE unresolved daily task set at a time (database.py
blocks creating a new day's tasks while the previous date has no report),
so the date of an unreported task set is always the single date the user
got stuck on. We re-check that same date on day+1, day+4, day+7 and day+10
to fire the four escalation stages, gated by a per-stage Redis lock so each
stage fires exactly once.

Stage 1 (day+1): personal nudge — mild reminder with tasks list.
Stage 2 (day+4): stern warning — includes auto-delete countdown.
Stage 3 (day+7): admin alert — ОСТУДИТЬ / УДАЛИТЬ buttons.
Stage 4 (day+10): auto-deletion — only if user has ≥1 prior report.
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

STAGE_OFFSET_DAYS = {1: 1, 2: 4, 3: 7, 4: 10}
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
            f"🔥 Эй, стоп.\n\n"
            f"Вчера ты поставил задачи — и не закрыл отчётом:\n\n"
            f"{tasks_text}\n\n"
            "В LedoLab цепочка одна: задача → действие → отчёт.\n"
            "Разорвёшь её — потеряешь день и LedoScore.\n\n"
            "Закрой отчётом прямо сейчас. Пока не поздно."
        )
    else:
        text = (
            f"🥶 Четыре дня тишины.\n\n"
            f"Задачи от {stuck_date} висят без отчёта:\n\n"
            f"{tasks_text}\n\n"
            "Это не клуб мотивации — здесь работают или уходят.\n\n"
            "Через 6 дней аккаунт будет удалён автоматически.\n"
            "Последний шанс закрыть отчётом и остаться в игре."
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


async def _auto_delete_user(bot: Bot, user: dict[str, Any], stuck_date: str, days_overdue: int) -> None:
    """Stage 4: auto-delete users who are 10+ days overdue and have ≥1 prior report."""
    telegram_id = user.get("telegram_id")
    internal_id = user.get("id")
    if not telegram_id or not internal_id:
        return

    report_count = await database.count_daily_reports_for_user(internal_id)
    if report_count < 1:
        logger.info(
            "Auto-delete skipped (no prior reports) | user=%s stuck_since=%s",
            telegram_id, stuck_date,
        )
        return

    logger.info(
        "Auto-deleting user=%s stuck_since=%s reports_before=%s",
        telegram_id, stuck_date, report_count,
    )
    result = await delete_user_everywhere(bot, telegram_id)

    label = f"@{user['username']}" if user.get("username") else (user.get("first_name") or "Участник")
    tasks_text = _format_task_list(user.get("tasks") or [])
    admin_text = (
        f"🗑 Юзер {label} (id <code>{telegram_id}</code>) автоматически удалён "
        f"после {days_overdue} дней без отчёта (с {stuck_date}).\n\n"
        f"Незакрытые задачи:\n{tasks_text}\n\n"
        f"Кикнут: {result.get('kicked')}, "
        f"ключей Redis удалено: {result.get('redis_deleted')}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(
                "Failed to send auto-delete alert for %s to admin %s: %s",
                telegram_id, admin_id, e,
            )


async def send_escalation_reminders(bot: Bot, now: datetime | None = None) -> None:
    """Run the 4-stage escalation pipeline.

    Stage 1 (day+1)  — personal nudge.
    Stage 2 (day+4)  — stern warning with auto-delete countdown.
    Stage 3 (day+7)  — admin alert (ОСТУДИТЬ / УДАЛИТЬ).
    Stage 4 (day+10) — auto-delete if user has ≥1 prior report.
    """
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
            elif stage == 4:
                await _auto_delete_user(bot, user, stuck_date, offset)
            else:
                await _send_stage_reminder(bot, user, stuck_date, stage)
            logger.info("Escalation stage %s sent | user=%s stuck_since=%s", stage, telegram_id, stuck_date)


def all_user_redis_patterns(telegram_id: int) -> list[str]:
    """Complete list of per-user Redis key patterns used across the whole bot.
    Used by both /reset command and delete_user_everywhere to guarantee
    identical, exhaustive cleanup."""
    tid = telegram_id
    return [
        f"quiz_done:{tid}",
        f"pending_quiz:{tid}",
        f"pending_referrer:{tid}",
        f"referral_throttle:{tid}",
        f"goal_lock:{tid}",
        f"goal_day_lock:{tid}:*",
        f"goal_thinking:{tid}",
        f"day_plan_lock:{tid}:*",
        f"streak:{tid}",
        f"last_report_date:{tid}",
        f"score:{tid}",
        f"last_group_chat:{tid}",
        f"group_welcome:{tid}",
        f"group_referral_welcome:{tid}",
        f"route_started:{tid}",
        f"escalation:{tid}:*",
        f"task:{tid}:*",
        f"morning_push:{tid}:*",
        f"day_advance_push:{tid}:*",
        f"day_closed_sent:{tid}:*",
        f"evening_push:{tid}:*",
        f"throttle:*:{tid}",
        f"leda_fsm:*{tid}*",
    ]


async def delete_user_everywhere(bot: Bot, telegram_id: int) -> dict[str, Any]:
    """Kick the user from the club group, wipe their DB rows and clear all Redis state."""
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
    result["redis_deleted"] = await cache.delete_keys_by_patterns(all_user_redis_patterns(telegram_id))
    return result
