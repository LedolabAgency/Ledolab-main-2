from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from app import cache, database
from aiogram import types as aiogram_types
from app.config import CLUB_GROUP_URL, CLUB_MENU_URL, REPORTS_GROUP_ID
from app.services import mention_service, rating_service

logger = logging.getLogger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kiev")

MIDDAY_REMINDER_PHRASES = [
    "⏳ День уже раскрутился. Если еще не тронулся с места — сейчас лучший момент сделать первый сильный шаг.",
    "🔥 Обед — не пауза, а точка перезапуска. Закрой одну важную вещь и не отпускай день в пустоту.",
    "📌 Кто двигается в середине дня, тот вечером не догоняет — а уже закрепляет результат.",
    "⚡ Полдень — время не думать, а фиксировать действие. Один честный шаг сегодня лучше десяти планов завтра.",
    "🧭 Если фокус уже расползается, вернись в маршрут. Сейчас день еще легко можно выровнять.",
    "💪 Середина дня — это не финиш, а контрольная точка. Покажи себе, что темп у тебя есть.",
    "🚀 До вечера еще далеко, а значит, сегодня можно сделать больше, чем ты сам от себя ожидал.",
    "🎯 Не жди идеального настроя. Закрой важное сейчас и забери себе спокойный вечер.",
]

DAY_REMINDER_PHRASES = [
    "⚡ Время ускоряться. Если день еще не собран, сейчас самое подходящее окно его собрать.",
    "📈 Днем выигрывает не тот, кто громче думает, а тот, кто быстрее делает.",
    "🔥 Еще есть запас хода. Один хороший шаг сейчас может спасти весь день.",
    "🛠️ Не отпускай ритм: чем раньше закрыта задача, тем сильнее ощущается контроль над днем.",
    "💼 Бизнес любит движение. Сейчас хороший момент превратить намерение в действие.",
    "🎯 Если день начал буксовать, не жди вечера — выправляй траекторию прямо сейчас.",
    "🚀 Твой темп сегодня складывается из маленьких решений. Первое — сделать шаг в работу.",
    "🧠 Не перегружай себя. Просто вернись к одному четкому действию и закрой его.",
]

DEADLINE_REMINDER_PHRASES = [
    "⏰ До дедлайна отчета осталось 2 часа. Сейчас самое время зафиксировать результат и не потерять день.",
    "🔥 Если отчет еще не сдан — у тебя еще есть окно, чтобы закрыть его красиво и без суеты.",
    "📌 Вечером выигрывает дисциплина. До 22:00 сдай отчет и забери свой LedoScore.",
    "🕗 День близится к финалу. Кто сдает отчет вовремя — тот держит ритм и растит рейтинг.",
    "🚀 Еще есть шанс завершить день сильным действием. Не оставляй отчет на последний рывок.",
    "💪 Один отчет сегодня может стоить больше, чем сотня обещаний завтра.",
    "🏁 Финал близко. Закрой день честно, зафиксируй результат и двигайся дальше.",
    "🎯 Не теряй вечер. Сейчас важнее не идеальность, а факт выполненного отчета.",
]

EVENING_REMINDER_PHRASES = [
    "🌙 Вечерний чек-ап LedoLab: день уже показывает характер. Закрывай его в плюс.",
    "🔥 У кого сегодня был результат — тот уже в игре. У кого тишина — еще есть шанс включиться.",
    "📈 Вечер — момент, когда дисциплина становится видимой. Не прячь сегодняшний прогресс.",
    "💼 Клуб живет не словами, а вечерними отчетами. Сейчас лучшее время это доказать.",
    "🧠 Если день был неровный, вечер еще можно собрать. Один отчет способен все выровнять.",
    "🚀 Кто закрывает день до 22:00, тот держит контроль над своим ритмом.",
    "🎯 Вечером решает не эмоция, а зафиксированный результат. Не оставляй день пустым.",
    "🏆 Сегодняшний темп формирует завтрашний рейтинг. Закрой день сильным финишем.",
]


def _pick_phrase(phrases: list[str], now: datetime) -> str:
    if not phrases:
        return ""
    seed = f"{now.date().isoformat()}:{now.hour}:{now.minute}"
    rng = random.Random(seed)
    return rng.choice(phrases)


def _menu_link_line() -> str:
    """Кликабельная текстовая ссылка на закреплённое меню (работает в приватной группе у участников, в отличие от инлайн-кнопки)."""
    if not CLUB_MENU_URL:
        return ""
    return f"\n\n📌 <a href=\"{CLUB_MENU_URL}\">Меню клуба</a>"


def _week_window(now: datetime) -> tuple[datetime, datetime]:
    days_since_sunday = (now.weekday() + 1) % 7
    last_sunday = now.date() - timedelta(days=days_since_sunday)
    week_start = datetime.combine(last_sunday, time(22, 0), tzinfo=KYIV_TZ)
    if now < week_start:
        week_start -= timedelta(days=7)
    return week_start, week_start + timedelta(days=7)


def _is_active_report_window(now: datetime) -> bool:
    week_start, week_end = _week_window(now)
    if not (week_start <= now < week_end):
        return False
    elapsed_days = (now - week_start).days
    return 0 <= elapsed_days < 5


def _build_regular_welcome(display_name: str) -> str:
    return (
        "🔥 Новое пополнение в LedoLab Business Club\n\n"
        f"{display_name} прошел квиз и зашел в клуб.\n\n"
        "Здесь побеждают не самые громкие, а самые системные.\n"
        "Поддержите новичка огнем и включите его в ритм 🔥\n\n"
        "Всё рабочее меню — в закреплённом сообщении вверху чата.\n"
        "Нажимай, ставь цели и расти вместе с лучшими 💪"
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


async def send_morning_private_reminders(bot: Bot, now: datetime | None = None) -> None:
    """08:30 — личный пуш каждому юзеру с задачами на сегодня."""
    now = now or datetime.now(KYIV_TZ)
    today = now.date().isoformat()
    users = await database.get_users_with_tasks_no_report(today)
    me = await bot.get_me()
    bot_username = me.username or ""
    for user in users:
        tg_id = int(user.get("telegram_id") or 0)
        if not tg_id:
            continue
        dedupe_key = f"morning_push:{tg_id}:{today}"
        if await cache.get_data(dedupe_key):
            continue
        tasks = user.get("tasks", [])
        name = user.get("first_name") or "друг"
        task_lines = "\n".join(f"• {t}" for t in tasks) if tasks else ""
        text = (
            f"☀️ Доброе утро, {name}!\n\n"
            + (f"Твои задачи на сегодня:\n{task_lines}\n\n" if task_lines else "")
            + "Держи ритм и закрой день сильным отчётом 💪"
            + _menu_link_line()
        )
        try:
            await bot.send_message(tg_id, text, parse_mode="HTML")
            await cache.set_data(dedupe_key, "1", ex=20 * 60 * 60)
        except Exception as e:
            logger.warning("Morning push failed | user=%s error=%s", tg_id, e)


async def send_morning_day_advance_reminders(bot: Bot, now: datetime | None = None) -> None:
    """08:30 — напоминание юзерам, закрывшим вчерашний день, поставить задачи на сегодня."""
    now = now or datetime.now(KYIV_TZ)
    today = now.date().isoformat()
    yesterday = (now.date() - timedelta(days=1)).isoformat()

    users = await database.get_users_with_report_yesterday_no_tasks_today(yesterday, today)
    for user in users:
        tg_id = int(user.get("telegram_id") or 0)
        if not tg_id:
            continue

        dedupe_key = f"day_advance_push:{tg_id}:{today}"
        if await cache.get_data(dedupe_key):
            continue

        streak = int((await cache.get_data(cache.KeyManager.get_streak_key(tg_id))) or 0)
        if streak >= 5:
            continue

        day_number = min(streak + 1, 5)
        milestones = user.get("milestones") or []
        milestone_index = max(0, min(day_number - 1, len(milestones) - 1))
        focus_text = milestones[milestone_index] if milestones else None

        name = user.get("first_name") or "друг"
        text = f"🌅 <b>Сегодня твой день {day_number} из 5, {name}.</b>\n\n"
        if focus_text:
            text += f"Твой фокус:\n<i>{escape(focus_text)}</i>\n\n"
        text += "Поставь задачи на день и закрой его отчётом до 22:00 💪"

        menu_url = CLUB_MENU_URL or CLUB_GROUP_URL
        keyboard = aiogram_types.InlineKeyboardMarkup(
            inline_keyboard=[[
                aiogram_types.InlineKeyboardButton(text="📌 Меню клуба", url=menu_url)
            ]]
        ) if menu_url else None

        try:
            await bot.send_message(tg_id, text, parse_mode="HTML", reply_markup=keyboard)
            await cache.set_data(dedupe_key, "1", ex=20 * 60 * 60)
            logger.info("Day advance push sent | user=%s day=%s", tg_id, day_number)
        except Exception as e:
            logger.warning("Day advance push failed | user=%s error=%s", tg_id, e)


async def send_personal_evening_reminders(bot: Bot, now: datetime | None = None) -> None:
    """21:00 — личный пуш тем, кто поставил задачи, но ещё не сдал отчёт."""
    now = now or datetime.now(KYIV_TZ)
    today = now.date().isoformat()
    users = await database.get_users_with_tasks_no_report(today)
    for user in users:
        tg_id = int(user.get("telegram_id") or 0)
        if not tg_id:
            continue
        dedupe_key = f"evening_push:{tg_id}:{today}"
        if await cache.get_data(dedupe_key):
            continue
        tasks = user.get("tasks", [])
        name = user.get("first_name") or "друг"
        task_lines = "\n".join(f"• {t}" for t in tasks) if tasks else ""
        text = (
            f"🌙 {name}, осталось меньше часа!\n\n"
            + (f"Твои задачи сегодня:\n{task_lines}\n\n" if task_lines else "")
            + "Отчёт ещё не сдан ⏰\n"
            "Закрой день — ты почти там 💪"
            + _menu_link_line()
        )
        try:
            await bot.send_message(tg_id, text, parse_mode="HTML")
            await cache.set_data(dedupe_key, "1", ex=6 * 60 * 60)
        except Exception as e:
            logger.warning("Evening personal push failed | user=%s error=%s", tg_id, e)


async def send_midday_reminder(bot: Bot, now: datetime | None = None) -> None:
    if not REPORTS_GROUP_ID:
        return

    now = now or datetime.now(KYIV_TZ)
    if not _is_active_report_window(now):
        return
    if now.hour != 13:
        return

    text = (
        f"{_pick_phrase(MIDDAY_REMINDER_PHRASES, now)}\n\n"
        "Если день уже начался — не отпускай его в хаос.\n"
        "Сейчас хороший момент вернуть фокус и сделать один сильный шаг 🔥"
        + _menu_link_line()
    )
    await bot.send_message(REPORTS_GROUP_ID, text, parse_mode="HTML")


async def send_evening_group_post(bot: Bot, now: datetime | None = None) -> None:
    """20:00 — один вечерний пост в группу: мотивация + сколько без отчёта + топ-3."""
    if not REPORTS_GROUP_ID:
        return

    now = now or datetime.now(KYIV_TZ)
    if not _is_active_report_window(now):
        return
    if now.hour != 20:
        return

    analytics = await database.get_admin_analytics(now.date().isoformat())
    missing_reports = max(int(analytics.get("missing_reports_today", 0)), 0)

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
        telegram_id = int(user.get("telegram_id") or 0)
        path_day_number = int((await cache.get_data(cache.KeyManager.get_streak_key(telegram_id))) or 0)
        path_day_number = ((path_day_number - 1) % 5) + 1 if path_day_number > 0 else 0
        medal_lines.extend([
            f"{medals[idx - 1]} {user_label} — {int(user.get('total_score', 0))} LedoScore",
            f"   📈 Путь: {path_day_number}/5" if path_day_number else "   📈 Путь: ещё не начат",
        ])

    top_block = "\n".join(medal_lines)
    intro = _pick_phrase(EVENING_REMINDER_PHRASES, now)
    text = (
        f"{intro}\n\n"
        f"До 22:00 ещё можно закрыть день. Без отчёта: {missing_reports} чел.\n\n"
        + (
            "🏆 ТОП-3 СЕЙЧАС:\n\n" + top_block
            if top_block
            else "🏆 Рейтинг формируется — закрой день первым сильным финишем."
        )
        + _menu_link_line()
    )
    await bot.send_message(
        REPORTS_GROUP_ID,
        text,
        parse_mode="HTML",
    )


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
