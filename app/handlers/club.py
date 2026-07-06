"""
Group business club handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext

from app import cache, database
from app.config import (
    ADMIN_IDS,
    CLUB_GROUP_URL,
    REPORTS_GROUP_ID,
)
from app.keyboards.inline.start import club_group_keyboard, club_main_menu, open_private_flow_keyboard
from app.services import cleanup_service, escalation_service, rating_service, report_service, task_service
from app.states.quiz import ReportStates, TaskStates

logger = logging.getLogger(__name__)
router = Router()
KYIV_TZ = ZoneInfo("Europe/Kiev")


def _today() -> str:
    # Клубный день = обычный календарный день (00:00–23:59), дедлайн отчёта 23:59.
    return datetime.now(KYIV_TZ).date().isoformat()


def _last_group_chat_key(user_id: int) -> str:
    return f"last_group_chat:{user_id}"


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


async def _delete_group_command_safely(message: types.Message) -> None:
    if message.chat.type == "private":
        return
    try:
        await message.delete()
    except Exception as exc:
        logger.debug("Failed to delete admin command %s: %s", message.message_id, exc)


def _shorten_alert(text: str, limit: int = 110) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _goal_deadline_text(goal: dict) -> str:
    created_raw = str(goal.get("created_at") or "")
    if not created_raw:
        return ""
    try:
        created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        created_dt = created_dt.astimezone(KYIV_TZ)
        finish_dt = created_dt + timedelta(days=30)
        return (
            f"Поставлена: {created_dt.strftime('%d.%m.%Y')}\n"
            f"До: {finish_dt.strftime('%d.%m.%Y')}"
        )
    except Exception:
        return ""


async def _ensure_group_interaction(event_message: types.Message) -> bool:
    if event_message.chat.type == "private":
        sent = await event_message.answer(
            "Рабочие действия доступны только в группе LedoLab Business To-Do Club.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        cleanup_service.schedule_delete_message(event_message.bot, sent.chat.id, sent.message_id, 120)
        return False
    return True


async def _ensure_group_callback(query: types.CallbackQuery) -> bool:
    if query.message.chat.type == "private":
        sent = await query.message.answer(
            "Рабочие действия доступны только в группе LedoLab Business To-Do Club.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        cleanup_service.schedule_delete_message(query.bot, sent.chat.id, sent.message_id, 120)
        await query.answer()
        return False
    return True


async def _ensure_quiz_for_query(query: types.CallbackQuery) -> bool:
    if await database.has_completed_quiz(query.from_user.id):
        return True

    me = await query.bot.get_me()
    sent = await query.message.answer(
        "🧭 Сначала пройди квиз в личке бота.\n\n"
        "Пока квиз не пройден, рабочие кнопки клуба закрыты 👇",
        reply_markup=open_private_flow_keyboard(me.username, "onboarding", "ПРОЙТИ КВИЗ В ЛИЧКЕ"),
    )
    cleanup_service.schedule_delete_message(query.bot, sent.chat.id, sent.message_id, 120)
    await query.answer()
    return False


async def _ensure_quiz_for_message(message: types.Message) -> bool:
    if await database.has_completed_quiz(message.from_user.id):
        return True

    me = await message.bot.get_me()
    sent = await message.answer(
        "🧭 Сначала пройди квиз в личке бота.\n\n"
        "Пока квиз не пройден, рабочие кнопки клуба закрыты 👇",
        reply_markup=open_private_flow_keyboard(me.username, "onboarding", "ПРОЙТИ КВИЗ В ЛИЧКЕ"),
    )
    cleanup_service.schedule_delete_message(message.bot, sent.chat.id, sent.message_id, 120)
    return False


async def _show_group_menu(message: types.Message) -> None:
    if message.chat.type == "private":
        await message.answer("Рабочее меню живет в группе LedoLab Business Club.")
        return
    if not await _ensure_quiz_for_message(message):
        return

    await cache.set_data(_last_group_chat_key(message.from_user.id), str(message.chat.id), ex=7 * 24 * 60 * 60)
    logger.info("MENU command | user=%s chat=%s type=%s text=%s", message.from_user.id, message.chat.id, message.chat.type, message.text)
    me = await message.bot.get_me()
    await message.answer(
        "LedoLab Business Club — клуб сильнейших\n\nРабочее меню:",
        reply_markup=club_main_menu(bot_username=me.username),
    )


@router.callback_query(F.data == "rules_view")
async def view_rules(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    text = (
        "🎯 Поставь цель на 30 дней, разбей её на 5 дней и сдавай ежедневные отчёты.\n\n"
        "🔥 Чем длиннее твой стрик, тем больше бонусных баллов ты получаешь.\n\n"
        "📈 Каждый отчёт приближает тебя к цели. 🚀"
    )
    await query.answer(text, show_alert=True)


@router.message(Command("admin"))
async def show_admin_help(message: types.Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    text = (
        "🛡 <b>Админ-команды LedoLab</b>\n\n"
        "<code>/admin</code> — показать эту подсказку\n"
        "<code>/reset 516684869</code> — полностью очистить юзера\n"
        "<code>/reset</code> ответом на сообщение юзера — очистить этого юзера\n\n"
        "Reset чистит: квиз, цель, 5-дневный маршрут, задачи, отчеты, голоса, баллы, рефералку и Redis-замки."
    )
    sent = await message.answer(text)
    if message.chat.type != "private":
        await _delete_group_command_safely(message)
        cleanup_service.schedule_delete_message(message.bot, sent.chat.id, sent.message_id, 180)


@router.message(Command("reset"))
async def reset_user_command(message: types.Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await _delete_group_command_safely(message)
        return

    target_id: int | None = None
    raw_arg = (command.args or "").strip()
    if raw_arg:
        first_arg = raw_arg.split()[0].strip()
        if first_arg.isdigit():
            target_id = int(first_arg)
    if target_id is None and message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id

    if target_id is None:
        sent = await message.answer(
            "Используй так:\n"
            "<code>/reset 516684869</code>\n\n"
            "Или ответь <code>/reset</code> на сообщение нужного юзера."
        )
        if message.chat.type != "private":
            await _delete_group_command_safely(message)
            cleanup_service.schedule_delete_message(message.bot, sent.chat.id, sent.message_id, 120)
        return

    me = await message.bot.get_me()
    if target_id == me.id:
        sent = await message.answer("⛔️ Нельзя сбросить самого бота. Укажи telegram_id участника клуба.")
        if message.chat.type != "private":
            await _delete_group_command_safely(message)
            cleanup_service.schedule_delete_message(message.bot, sent.chat.id, sent.message_id, 60)
        return

    await cache.set_data(cache.KeyManager.get_user_reset_key(target_id), "1", ex=120)
    stats = await database.reset_user_data(target_id)
    redis_deleted = await cache.delete_keys_by_patterns(
        escalation_service.all_user_redis_patterns(target_id)
    )
    stats_text = "\n".join(f"{name}: {count}" for name, count in stats.items() if count)
    sent = await message.answer(
        f"♻️ <b>Reset готов</b>\n\n"
        f"Юзер: <code>{target_id}</code>\n"
        f"Redis ключей удалено: <code>{redis_deleted}</code>\n\n"
        f"{stats_text or 'В БД активных записей не было.'}"
    )
    logger.info(
        "ADMIN reset completed | admin=%s target=%s stats=%s redis_deleted=%s",
        message.from_user.id if message.from_user else None,
        target_id,
        stats,
        redis_deleted,
    )
    if message.chat.type != "private":
        await _delete_group_command_safely(message)
        cleanup_service.schedule_delete_message(message.bot, sent.chat.id, sent.message_id, 180)


@router.message(Command("menu"))
async def show_menu_command(message: types.Message) -> None:
    await _show_group_menu(message)


@router.message(F.text.regexp(r"^/menu(?:@[\w_]+)?$"))
async def show_menu_fallback(message: types.Message) -> None:
    await _show_group_menu(message)


@router.callback_query(F.data == "goal_view")
async def start_goal_flow(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    await cache.set_data(_last_group_chat_key(query.from_user.id), str(query.message.chat.id), ex=7 * 24 * 60 * 60)
    logger.info("GROUP goal button | user=%s chat=%s", query.from_user.id, query.message.chat.id)
    club_user = await database.get_club_user(query.from_user.id)
    if club_user:
        active_goal = await database.get_active_goal(club_user["id"])
        if active_goal:
            goal_text = _shorten_alert(str(active_goal.get("goal_text") or "Цель уже активна"))
            deadline_text = _goal_deadline_text(active_goal)
            alert_text = f"🎯 Цель уже активна:\n{goal_text}"
            if deadline_text:
                alert_text += f"\n\n{deadline_text}"
            await query.answer(alert_text, show_alert=True)
            return
    me = await query.bot.get_me()
    sent = await query.message.answer(
        "Цель на 30 дней задается в личке с ботом.",
        reply_markup=open_private_flow_keyboard(
            me.username,
            "goal_setup",
            "ОТКРЫТЬ ЦЕЛЬ В ЛИЧКЕ",
        ),
    )
    cleanup_service.schedule_delete_message(query.bot, sent.chat.id, sent.message_id, 120)
    await query.answer()


@router.callback_query(F.data == "day_view")
async def open_day_view(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    await cache.set_data(_last_group_chat_key(query.from_user.id), str(query.message.chat.id), ex=7 * 24 * 60 * 60)
    logger.info("GROUP day button | user=%s chat=%s", query.from_user.id, query.message.chat.id)
    club_user = await database.get_club_user(query.from_user.id)
    if club_user:
        today = _today()
        today_tasks = await database.get_today_tasks(club_user["id"], today)
        if today_tasks:
            await query.answer(
                "📌 День уже зафиксирован ✅\nПодробности смотри через кнопку «Детально».",
                show_alert=True,
            )
            return
    me = await query.bot.get_me()
    sent = await query.message.answer(
        "Собрать день лучше в личке, чтобы ничего не терялось и весь рабочий путь был в одном месте 👇",
        reply_markup=open_private_flow_keyboard(
            me.username,
            "day_setup",
            "ОТКРЫТЬ МОЙ ДЕНЬ В ЛИЧКЕ",
        ),
    )
    cleanup_service.schedule_delete_message(query.bot, sent.chat.id, sent.message_id, 120)
    await query.answer()


@router.message(TaskStates.waiting_day_tasks)
async def save_day_tasks(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
        await state.clear()
        return
    if not await _ensure_quiz_for_message(message):
        await state.clear()
        return

    raw_tasks = [line.strip("-• \t") for line in (message.text or "").splitlines() if line.strip()]
    if len(raw_tasks) != 3:
        await message.answer("Нужно отправить ровно 3 задачи. Каждую задачу с новой строки.")
        return

    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить профиль участника. Попробуй позже.")
        await state.clear()
        return

    active_goal = await database.get_active_goal(club_user["id"])
    for idx, task_text in enumerate(raw_tasks, 1):
        await task_service.set_daily_task(
            user_id=club_user["id"],
            task_text=task_text,
            today=_today(),
            task_type=f"day_{idx}",
            goal_id=active_goal["id"] if active_goal else None,
        )

    me = await message.bot.get_me()
    await message.answer(
        "📅 День зафиксирован.\n\nТвои 3 задачи сохранены. Вечером возвращайся и сдавай отчет.",
        reply_markup=club_main_menu(bot_username=me.username),
    )
    await state.clear()


@router.callback_query(F.data == "report_submit")
async def start_report_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    await cache.set_data(_last_group_chat_key(query.from_user.id), str(query.message.chat.id), ex=7 * 24 * 60 * 60)
    logger.info("GROUP report button | user=%s chat=%s", query.from_user.id, query.message.chat.id)
    club_user = await database.get_club_user(query.from_user.id)
    if club_user:
        existing_report = await database.get_daily_report(club_user["id"], _today())
        if existing_report and str(existing_report.get("status") or "").lower() not in {"redo_requested", "rejected"}:
            await query.answer("📤 Бро, ты уже сдал отчет за этот день ✅", show_alert=True)
            return
    me = await query.bot.get_me()
    await state.clear()
    sent = await query.message.answer(
        "📤 Сдаем отчет за этот день.\n\n"
        "Я покажу твои задачи,\n"
        "а ты отправишь один кружочек до 1 минуты с коротким отчетом по ним 👇",
        reply_markup=open_private_flow_keyboard(
            me.username,
            "report_setup",
            "ОТКРЫТЬ ОТЧЕТ В ЛИЧКЕ",
        ),
    )
    cleanup_service.schedule_delete_message(query.bot, sent.chat.id, sent.message_id, 120)
    await query.answer()


@router.callback_query(F.data == "detail_view")
async def open_detail_view(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    await cache.set_data(_last_group_chat_key(query.from_user.id), str(query.message.chat.id), ex=7 * 24 * 60 * 60)
    me = await query.bot.get_me()
    sent = await query.message.answer(
        "📋 Все детали уже в личке.\n\n"
        "Открой бота и через меню посмотри цель, план и день 👇",
        reply_markup=open_private_flow_keyboard(
            me.username,
            "details_setup",
            "ОТКРЫТЬ ДЕТАЛИ В ЛИЧКЕ",
        ),
    )
    cleanup_service.schedule_delete_message(query.bot, sent.chat.id, sent.message_id, 120)
    await query.answer()


RATING_VIEW_THROTTLE_SECONDS = 10 * 60


@router.callback_query(F.data == "rating_view")
async def show_rating(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    if not await cache.acquire_lock("rating_view_throttle", ex=RATING_VIEW_THROTTLE_SECONDS):
        await query.answer(
            "Рейтинг можно смотреть раз в 10 минут.\nПоследний рейтинг уже есть ниже в чате — прокрути сообщения вниз 👇",
            show_alert=True,
        )
        return

    users = await rating_service.get_current_week_leaderboard()
    text = await rating_service.format_rating_text(users, viewer_telegram_id=query.from_user.id)
    await query.message.answer(text)
    await query.answer("Рейтинг обновлен.")


@router.callback_query(F.data.startswith("report_vote:"))
async def vote_for_report(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    _, vote_type, report_id = query.data.split(":", 2)
    logger.info("GROUP report vote | user=%s report_id=%s vote=%s", query.from_user.id, report_id, vote_type)
    report_before_vote = await database.get_daily_report_by_id(report_id)
    if not report_before_vote:
        await query.answer("Отчет не найден.", show_alert=True)
        return
    voter_user = await database.get_club_user(query.from_user.id)
    if voter_user and voter_user.get("id") == report_before_vote.get("user_id"):
        await query.answer("Нельзя голосовать за свой собственный отчет.", show_alert=True)
        return

    report = await report_service.vote_on_report(report_id, query.from_user.id, vote_type)
    if not report:
        await query.answer("Ты уже голосовал по этому отчету или отчет не найден.", show_alert=True)
        return

    await query.message.edit_reply_markup(
        reply_markup=report_service.group_report_vote_keyboard(
            report_id,
            report.get("ok_count", 0),
            report.get("flag_count", 0),
        )
    )

    if report.get("status") == "suspicious" and report.get("flag_count", 0) == report_service.SUSPICIOUS_FLAGS_THRESHOLD:
        club_user = await database.get_club_user_by_id(report["user_id"])
        goal = await database.get_active_goal(report["user_id"])
        user_label = (
            f"@{club_user['username']}"
            if club_user and club_user.get("username")
            else (club_user or {}).get("first_name", "Участник")
        )
        summary = report_service.build_admin_summary(
            user_label=user_label,
            goal_text=(goal or {}).get("goal_text", ""),
            entries=report.get("report_payload", []),
            flags=report.get("flag_count", 0),
        )
        for admin_id in ADMIN_IDS:
            try:
                await query.bot.send_message(
                    admin_id,
                    summary,
                    reply_markup=report_service.admin_review_keyboard(report_id),
                )
            except Exception as e:
                logger.warning("Failed to notify admin %s about suspicious report %s: %s", admin_id, report_id, e)

    await query.answer("Голос принят.")


@router.callback_query(F.data.startswith("admin_report:approve:"))
async def approve_report_by_admin(query: types.CallbackQuery) -> None:
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Только для админа.", show_alert=True)
        return

    report_id = query.data.split(":", 2)[2]
    report = await database.get_daily_report_by_id(report_id)
    if not report:
        await query.answer("Отчет не найден.", show_alert=True)
        return

    await database.set_daily_report_status(report_id, "approved_admin")
    if report.get("group_chat_id") and report.get("group_message_id"):
        try:
            await query.bot.edit_message_text(
                chat_id=report["group_chat_id"],
                message_id=report["group_message_id"],
                text=report_service.build_admin_approved_summary(report.get("summary_text", "")),
                reply_markup=report_service.group_report_vote_keyboard(
                    report_id,
                    await database.count_daily_report_votes(report_id, "ok"),
                    await database.count_daily_report_votes(report_id, "flag"),
                ),
            )
        except Exception as e:
            logger.warning("Could not mark group report as admin-approved: %s", e)

    await query.answer("Отчет подтвержден.")


@router.callback_query(F.data.startswith("admin_report:reject:"))
async def reject_report_by_admin(query: types.CallbackQuery) -> None:
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Только для админа.", show_alert=True)
        return

    report_id = query.data.split(":", 2)[2]
    report = await database.get_daily_report_by_id(report_id)
    if not report:
        await query.answer("Отчет не найден.", show_alert=True)
        return

    await database.set_daily_report_status(report_id, "rejected")
    # score_awarded уже включает streak-бонус (report_service.save_daily_report), снимаем его целиком.
    await database.award_score(report["user_id"], -int(report.get("score_awarded") or 30), "Daily report rejected by admin")
    if report.get("group_chat_id") and report.get("group_message_id"):
        try:
            await query.bot.edit_message_text(
                chat_id=report["group_chat_id"],
                message_id=report["group_message_id"],
                text=report_service.build_admin_rejected_summary(report.get("summary_text", "")),
                reply_markup=None,
            )
        except Exception as e:
            logger.warning("Could not mark group report as rejected: %s", e)
    warnings = await database.increment_user_warnings(report["user_id"], 3)
    if int((warnings or {}).get("warnings_count") or 0) >= 2:
        await database.award_score(report["user_id"], -report_service.WARNING_SCORE_PENALTY, "Warning penalty")

    club_user = await database.get_club_user_by_id(report["user_id"])
    if club_user and club_user.get("telegram_id"):
        await query.bot.send_message(
            club_user["telegram_id"],
            "⚠️ Админ пометил твой отчет как сомнительный.\n\n"
            "Баллы за него сняты.\n"
            "Сегодня пересдать его уже нельзя.\n"
            "Завтра начнешь новый день и новый отчет.\n\n"
            "Важно: еще такие случаи — и ты вылетишь из клуба.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )

    await query.answer("Отчет отклонен. 3 предупреждения выданы.")


@router.callback_query(F.data.startswith("admin_report:comment:"))
async def request_report_comment(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Только для админа.", show_alert=True)
        return

    report_id = query.data.split(":", 2)[2]
    report = await database.get_daily_report_by_id(report_id)
    if not report:
        await query.answer("Отчет не найден.", show_alert=True)
        return

    await state.set_state(ReportStates.waiting_admin_comment)
    await state.update_data(admin_report_id=report_id)
    await query.message.answer("Напиши комментарий для пользователя: что именно не так и что переделать.")
    await query.answer()


@router.message(ReportStates.waiting_admin_comment)
async def save_admin_report_comment(message: types.Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return

    data = await state.get_data()
    report_id = data.get("admin_report_id")
    if not report_id:
        await state.clear()
        return

    report = await database.get_daily_report_by_id(report_id)
    if not report:
        await message.answer("Не нашел отчет для комментария.")
        await state.clear()
        return

    comment_text = (message.text or "").strip()
    await database.set_daily_report_status(report_id, "redo_requested", admin_comment=comment_text)
    # score_awarded уже включает streak-бонус (report_service.save_daily_report), снимаем его целиком.
    await database.award_score(report["user_id"], -int(report.get("score_awarded") or 30), "Daily report sent back for redo")
    if report.get("group_chat_id") and report.get("group_message_id"):
        try:
            await message.bot.edit_message_text(
                chat_id=report["group_chat_id"],
                message_id=report["group_message_id"],
                text=report_service.build_admin_returned_summary(report.get("summary_text", "")),
                reply_markup=None,
            )
        except Exception as e:
            logger.warning("Could not mark group report as returned: %s", e)

    user_info = await database.get_club_user_by_id(report["user_id"])
    if user_info and user_info.get("telegram_id"):
        await message.bot.send_message(
            user_info["telegram_id"],
            "💬 Админ вернул твой отчет с комментарием.\n\n"
            f"{comment_text}\n\n"
            "Выбери, что делать дальше:",
            reply_markup=report_service.redo_report_keyboard(report_id),
        )

    await state.clear()
    await message.answer("Комментарий отправлен пользователю.")


@router.callback_query(F.data.startswith("esc_delete_ask:"))
async def ask_delete_escalated_user(query: types.CallbackQuery) -> None:
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Только для админа.", show_alert=True)
        return

    target_id = int(query.data.split(":", 1)[1])
    await query.message.edit_reply_markup(
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"esc_delete_confirm:{target_id}"),
                    types.InlineKeyboardButton(text="↩️ Отмена", callback_data=f"esc_delete_cancel:{target_id}"),
                ]
            ]
        )
    )
    await query.answer("Точно удалить? Это нельзя отменить.", show_alert=True)


@router.callback_query(F.data.startswith("esc_delete_confirm:"))
async def confirm_delete_escalated_user(query: types.CallbackQuery) -> None:
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Только для админа.", show_alert=True)
        return

    target_id = int(query.data.split(":", 1)[1])
    stats = await escalation_service.delete_user_everywhere(query.bot, target_id)
    logger.info("ADMIN escalation delete | admin=%s target=%s stats=%s", query.from_user.id, target_id, stats)

    kicked_text = "кикнут из группы ✅" if stats["kicked"] else "кикнуть из группы не удалось ⚠️ (проверь права бота)"
    db_stats = stats.get("db_stats") or {}
    db_text = "\n".join(f"{name}: {count}" for name, count in db_stats.items() if count)
    await query.message.edit_text(
        f"🗑 Юзер <code>{target_id}</code> удален.\n\n"
        f"{kicked_text}\n"
        f"Redis ключей удалено: {stats['redis_deleted']}\n\n"
        f"{db_text or 'В БД активных записей не было.'}"
    )
    await query.answer("Удалено.")


@router.callback_query(F.data.startswith("esc_delete_cancel:"))
async def cancel_delete_escalated_user(query: types.CallbackQuery) -> None:
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Только для админа.", show_alert=True)
        return

    target_id = int(query.data.split(":", 1)[1])
    await query.message.edit_reply_markup(reply_markup=escalation_service.admin_escalation_keyboard(target_id))
    await query.answer("Отменено.")
