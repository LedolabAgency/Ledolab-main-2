from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from app import cache, database
from app.config import REPORTS_GROUP_ID
from app.services import mention_service, rating_service

logger = logging.getLogger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kiev")


def _week_window(now: datetime) -> tuple[datetime, datetime]:
    days_since_sunday = (now.weekday() + 1) % 7
    last_sunday = now.date() - timedelta(days=days_since_sunday)
    week_start = datetime.combine(last_sunday, time(22, 0), tzinfo=KYIV_TZ)
    if now < week_start:
        week_start -= timedelta(days=7)
    return week_start, week_start + timedelta(days=7)


def _build_regular_welcome(display_name: str) -> str:
    return (
        "🔥 Новое пополнение в LedoLab Business Club\n\n"
        f"{display_name} прошел квиз и зашел в клуб.\n\n"
        "Здесь побеждают не самые громкие, а самые системные.\n"
        "Поддержите новичка огнем и включите его в ритм 🔥"
    )


def _build_referral_welcome(display_name: str, referrer_name: str) -> str:
    return (
        "🚀 Реферальное пополнение в LedoLab Business Club\n\n"
        f"Новый участник {display_name} зашел по приглашению {referrer_name}.\n\n"
        "Если новичок дойдет до 3-го отчета, оба получат бонусы по рефералке 🔥"
    )


async def _resolve_target_group_ids(
    *,
    telegram_id: int,
    referral: dict | None = None,
) -> list[int]:
    candidate_ids: list[int] = []

    cached_group_chat_id = await cache.get_data(f"last_group_chat:{telegram_id}")
    if cached_group_chat_id:
        try:
            candidate_ids.append(int(cached_group_chat_id))
        except ValueError:
            pass

    if referral and referral.get("referrer_telegram_id"):
        referrer_group_chat_id = await cache.get_data(f"last_group_chat:{int(referral['referrer_telegram_id'])}")
        if referrer_group_chat_id:
            try:
                referrer_chat_id = int(referrer_group_chat_id)
                if referrer_chat_id not in candidate_ids:
                    candidate_ids.append(referrer_chat_id)
            except ValueError:
                pass

    if REPORTS_GROUP_ID and REPORTS_GROUP_ID not in candidate_ids:
        candidate_ids.append(REPORTS_GROUP_ID)

    return candidate_ids


async def announce_member_joined(
    bot: Bot,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
) -> None:
    referral = await database.get_referral_by_referred_telegram(telegram_id)
    display_name = mention_service.build_user_mention(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        fallback=f"ID:{telegram_id}",
    )
    key_prefix = "group_referral_welcome" if referral else "group_welcome"
    dedupe_key = f"{key_prefix}:{telegram_id}"
    if await cache.get_data(dedupe_key):
        logger.info("GROUP welcome skipped | user=%s reason=dedupe", telegram_id)
        return

    text = _build_regular_welcome(display_name)
    if referral and referral.get("referrer_telegram_id"):
        referrer = await database.get_club_user(int(referral["referrer_telegram_id"]))
        referrer_name = mention_service.build_user_mention(
            telegram_id=int(referral["referrer_telegram_id"]),
            username=(referrer or {}).get("username"),
            first_name=(referrer or {}).get("first_name"),
            fallback="Участник",
        )
        text = _build_referral_welcome(display_name, referrer_name)
    target_group_ids = await _resolve_target_group_ids(telegram_id=telegram_id, referral=referral)
    if not target_group_ids:
        logger.warning("GROUP welcome failed | user=%s reason=no_target_group", telegram_id)
        return

    for target_group_id in target_group_ids:
        try:
            await bot.send_message(target_group_id, text)
            await cache.set_data(dedupe_key, "1", ex=30 * 24 * 60 * 60)
            logger.info(
                "GROUP %s sent | user=%s chat=%s",
                "referral_welcome" if referral else "welcome",
                telegram_id,
                target_group_id,
            )
            return
        except Exception as e:
            logger.warning(
                "GROUP %s failed | user=%s chat=%s error=%s",
                "referral_welcome" if referral else "welcome",
                telegram_id,
                target_group_id,
                e,
            )

    logger.warning(
        "GROUP %s failed | user=%s reason=all_targets_failed",
        "referral_welcome" if referral else "welcome",
        telegram_id,
    )


async def send_report_deadline_reminder(bot: Bot, now: datetime | None = None) -> None:
    if not REPORTS_GROUP_ID:
        return

    now = now or datetime.now(KYIV_TZ)
    week_start, week_end = _week_window(now)
    if not (week_start <= now < week_end):
        return

    elapsed_days = (now - week_start).days
    if not (0 <= elapsed_days < 5):
        return

    analytics = await database.get_admin_analytics(now.date().isoformat())
    missing_reports = max(int(analytics.get("missing_reports_today", 0)), 0)
    text = (
        "⏰ До дедлайна отчета осталось 2 часа.\n\n"
        f"Сегодня без отчета еще {missing_reports} участ.\n"
        "Кто двигается — тот фиксирует результат.\n"
        "До 22:00 закрой день, сдай отчет и забери свой LedoScore 🔥"
    )
    await bot.send_message(REPORTS_GROUP_ID, text)


async def send_evening_checkup(bot: Bot, now: datetime | None = None) -> None:
    if not REPORTS_GROUP_ID:
        return

    now = now or datetime.now(KYIV_TZ)
    if now.hour != 21:
        return

    top_users = await rating_service.get_rating_leaderboard(limit=3)
    medal_lines = []
    medals = ["🥇", "🥈", "🥉"]
    for idx, user in enumerate(top_users, 1):
        user_label = mention_service.build_user_mention(
            telegram_id=int(user.get("telegram_id") or 0),
            username=user.get("username"),
            first_name=user.get("first_name"),
            fallback="Участник",
        )
        medal_lines.extend(
            [
                f"{medals[idx - 1]} {user_label} — {int(user.get('total_score', 0))} LedoScore",
            ]
        )
    top_block = "\n".join(medal_lines)
    text = (
        "🌙 Вечерний чек-ап LedoLab.\n\n"
        "До 22:00 еще можно закрыть день и зафиксировать LedoScore.\n"
        "Кто уже сдал отчет — держит темп. Кто еще в тишине — сейчас лучшее время не терять ритм 🔥\n\n"
        + (
            "🏆 ТОП-3 СЕЙЧАС:\n\n" + top_block
            if top_block
            else "🏆 Пока топ не сформирован, но вечер уже зовет закрывать день сильным финишем."
        )
        + "\n\n📈 Твой путь сегодня: не теряй темп и закрой день сильным отчетом."
    )
    await bot.send_message(REPORTS_GROUP_ID, text, parse_mode="HTML")


async def send_weekly_final(bot: Bot, now: datetime | None = None) -> None:
    if not REPORTS_GROUP_ID:
        return

    now = now or datetime.now(KYIV_TZ)
    current_week_start, _ = _week_window(now)
    previous_week_start = current_week_start - timedelta(days=7)
    users = await rating_service.get_period_leaderboard(
        previous_week_start.isoformat(),
        current_week_start.isoformat(),
        limit=3,
    )

    if not users:
        await bot.send_message(
            REPORTS_GROUP_ID,
            "🏁 Недельная финалка LedoLab Business Club\n\n"
            "Неделя закрыта.\n"
            "Пока без ярко выраженных лидеров — значит, новая неделя ждет первого мощного рывка 🔥",
        )
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏁 Недельная финалка LedoLab Business Club\n", "Лучшие за закрытую неделю:\n"]
    for idx, user in enumerate(users, 1):
        lines.extend(
            [
                f"{medals[idx - 1]} {rating_service._display_label(user)}",
                f"LedoScore: {int(user.get('total_score', 0))}",
                f"Стрик: {int(user.get('streak', 0))} дн.",
                "",
            ]
        )
    lines.append("Новая неделя уже началась. Не выигрывают самые громкие — выигрывают те, кто держит ритм каждый день 🚀")
    await bot.send_message(REPORTS_GROUP_ID, "\n".join(lines).strip())
