"""
Private onboarding and goal/day setup flows.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from html import escape

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext

from app import cache, database
from app.config import ADMIN_IDS, CLUB_GROUP_URL, GOAL_SCORE, REPORTS_GROUP_ID, WEB_APP_URL
from app.keyboards.inline.start import (
    club_group_keyboard,
    contact_reply_keyboard,
    day_start_keyboard,
    day_task_next_keyboard,
    goal_day_step_keyboard,
    goal_edit_days_keyboard,
    goal_ready_keyboard,
    goal_review_keyboard,
    goal_text_confirm_keyboard,
    open_bot_private_keyboard,
    open_private_flow_keyboard,
    private_hub_reply_keyboard,
    quiz_reply_keyboard,
    return_to_group_keyboard,
)
from app.services import report_service
from app.states.quiz import GoalStates, ReportStates, TaskStates

logger = logging.getLogger(__name__)
router = Router()

GOAL_LOCK_TTL = 30 * 24 * 60 * 60
DAYS_IN_WEEKLY_SPRINT = 5


def _goal_lock_key(user_id: int) -> str:
    return f"goal_lock:{user_id}"


def _goal_day_lock_key(user_id: int, day_number: int) -> str:
    return f"goal_day_lock:{user_id}:{day_number}"


def _pending_quiz_key(user_id: int) -> str:
    return f"pending_quiz:{user_id}"


def _last_group_chat_key(user_id: int) -> str:
    return f"last_group_chat:{user_id}"


def _report_media_msg_key(report_id: str) -> str:
    return f"report_media_msg:{report_id}"


def _report_media_reverse_key(chat_id: int, message_id: int) -> str:
    return f"report_media_reverse:{chat_id}:{message_id}"


def _today() -> str:
    return datetime.now().date().isoformat()


async def _delete_command_message_safely(message: types.Message) -> None:
    if message.chat.type == "private":
        return
    try:
        await message.delete()
    except Exception as e:
        logger.warning("Failed to delete admin command message %s: %s", message.message_id, e)


def _current_club_day_index(now: datetime | None = None) -> int | None:
    """Return the current 1..5 working-day index for the Sunday-21:00 weekly cycle."""
    now = now or datetime.now()
    days_since_sunday = (now.weekday() + 1) % 7
    last_sunday = now.date() - timedelta(days=days_since_sunday)
    week_start = datetime.combine(last_sunday, time(21, 0))
    if now < week_start:
        week_start -= timedelta(days=7)

    elapsed_days = (now - week_start).days
    if 0 <= elapsed_days < DAYS_IN_WEEKLY_SPRINT:
        return elapsed_days + 1
    return None


def _goal_intro_text() -> str:
    return (
        "🎯 LedoLab Business Club\n\n"
        "Сейчас мы соберем твою главную цель на ближайшие 30 дней.\n\n"
        "Зачем это нужно:\n"
        "если нет одной понятной цели, человек много двигается, но слабо продвигается вперед.\n\n"
        "Как это работает:\n"
        "1. Ты ставишь 1 большую цель на месяц\n"
        "2. Потом разбиваешь ее на 5 ближайших рабочих дней\n"
        "3. А уже после этого дробишь день на конкретные задачи\n\n"
        "Напиши свою цель на 30 дней 👇"
    )


def _goal_confirmation_text(goal_text: str) -> str:
    return (
        "Вот как я понял твою цель:\n\n"
        f"🎯 {escape(str(goal_text))}\n\n"
        "Если все верно — подтверждай.\n"
        "Если хочешь уточнить формулировку — измени."
    )


def _week_intro_text() -> str:
    return (
        "Отлично 🔥\n\n"
        "Теперь разложим эту цель на 5 ближайших рабочих дней.\n\n"
        "Зачем это нужно:\n"
        "большая цель без ближайшего маршрута остается просто желанием.\n\n"
        "Сейчас не нужны мелкие задачи.\n"
        "Нужны 5 понятных фокусов, которые будут двигать тебя вперед день за днем."
    )


def _day_focus_prompt(day_number: int) -> str:
    hints = {
        1: "Напиши главный фокус на первый рабочий день.",
        2: "Отлично, первый шаг есть. Теперь зафиксируй фокус на второй день.",
        3: "Хорошо идем. Теперь нужен ясный ориентир на третий день.",
        4: "Маршрут уже собирается. Напиши фокус на четвертый день.",
        5: "Финальный шаг недельного плана. Напиши фокус на пятый день.",
    }
    return (
        f"📍 День {day_number}\n\n"
        f"{hints.get(day_number, 'Напиши фокус на этот день.')}\n\n"
        "Это должен быть не хаос из дел, а один понятный результат, который реально приблизит тебя к цели 👇"
    )


def _goal_review_text(goal_text: str, week_plan: list[str]) -> str:
    lines = [
        "Проверь свой маршрут:\n",
        f"🎯 Цель на 30 дней:\n{escape(str(goal_text))}\n",
        "📅 План на 5 дней:",
    ]
    for index, day_text in enumerate(week_plan, 1):
        lines.append(f"{index}. {escape(str(day_text))}")
    lines.append("")
    lines.append("Если все ок — утверждай. Если хочешь поправить — измени.")
    return "\n".join(lines)


def _ready_after_plan_text() -> str:
    return (
        "🚀 План зафиксирован.\n\n"
        "Теперь у тебя есть не просто желание, а понятный маршрут.\n\n"
        "Готов приступить уже сегодня?"
    )


def _start_today_text() -> str:
    return (
        "Отлично 🔥\n\n"
        "Теперь твоя задача — разложить сегодняшний день на конкретные действия.\n\n"
        "Важно:\n"
        "задачи на сегодня действуют до 22:00.\n"
        "Именно по ним вечером ты будешь сдавать отчет."
    )


def _task_prompt(task_number: int) -> str:
    if task_number == 1:
        return (
            "Напиши задачу №1 на сегодня.\n\n"
            "Подсказка:\n"
            "одна задача = одно конкретное действие, которое можно либо сделать, либо не сделать."
        )
    if task_number == 2:
        return (
            "Хорошо.\n\n"
            "Теперь задача №2.\n"
            "Если на сегодня тебе достаточно одной сильной задачи — можешь нажать «Пропустить»."
        )
    return (
        "Супер.\n\n"
        "Теперь задача №3.\n"
        "Если третья задача сегодня не нужна — лучше честно нажми «Пропустить», чем написать ее для галочки."
    )


def _task_skip_reason_text() -> str:
    return (
        "⚠️ Важно:\n\n"
        "Здесь решает не количество задач, а дисциплина.\n\n"
        "📅 Каждый день у тебя есть до 3 задач — это твой фокус\n"
        "🎯 Но баллы ты получаешь не за задачи, а за отчёт\n\n"
        "📤 Сдал отчёт → получил баллы\n"
        "🚫 Не сдал → день не засчитан\n\n"
        "❌ Не выдумывай задачи ради галочки\n"
        "✔️ Делай реальные вещи и честно отчитывайся\n\n"
        "📈 Важно только одно: ты идёшь к своей цели или нет"
    )


def _day_summary_text(tasks: list[str]) -> str:
    lines = ["📌 День зафиксирован.\n", "Твои задачи на сегодня:"]
    for index, task in enumerate(tasks, 1):
        lines.append(f"{index}. {task}")
    lines.extend(
        [
            "",
            "Что дальше:",
            "— выполни их до 22:00",
            "— до 22:00 сдай отчет в группе",
            "— от этого зависят твои LedoScore и место в рейтинге",
            "",
            "Чем стабильнее ты работаешь, тем выше твой шанс стать одним из сильнейших участников клуба 🔥",
        ]
    )
    return "\n".join(lines)


def _group_goal_announcement(display_name: str, goal_text: str, week_plan: list[str]) -> str:
    safe_display_name = escape(str(display_name or "Участник клуба"))
    safe_goal_text = escape(str(goal_text or ""))
    lines = [
        "🔥 Новый участник в игре\n",
        f"{safe_display_name} зафиксировал свою цель на 30 дней и собрал 5-дневный маршрут в LedoLab Business Club.\n",
        f"🎯 Цель:\n{safe_goal_text}\n",
        "📅 Ближайшие 5 рабочих дней:",
    ]
    for index, item in enumerate(week_plan, 1):
        lines.append(f"{index}. {escape(str(item or ''))}")
    lines.extend(
        [
            "",
            "Вот это уже не «когда-нибудь хочу».",
            "Вот это — маршрут.",
            "",
            "Поддержите его огнем 🔥",
        ]
    )
    return "\n".join(lines)


async def _show_phone_request(message: types.Message) -> None:
    await message.answer(
        "📱 Ты уже почти внутри клуба.\n\n"
        "Я вижу твой квиз, осталось только последнее действие — поделиться номером телефона 👇",
        reply_markup=contact_reply_keyboard(),
    )


async def _user_has_phone(user_id: int) -> bool:
    return await database.has_phone_number(user_id)


async def _needs_phone_completion(user: types.User) -> bool:
    if await _user_has_phone(user.id):
        return False
    club_user = await database.get_club_user(user.id)
    return bool(club_user)


async def _can_show_private_hub(user: types.User) -> bool:
    club_user = await database.ensure_club_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        language_code=user.language_code or "ru",
    )
    if not club_user:
        return False
    return await database.has_any_day_tasks(club_user["id"])


async def _ensure_quiz_and_phone_message(message: types.Message) -> bool:
    user_id = message.from_user.id
    quiz_profile = await database.get_user(user_id)
    if (quiz_profile and not await _user_has_phone(user_id)) or await _needs_phone_completion(message.from_user):
        await _show_phone_request(message)
        return False
    if await database.has_completed_quiz(user_id):
        return True
    await message.answer(
        "🧭 Сначала пройди квиз, чтобы я понял твой контекст и открыл рабочие сценарии 👇",
        reply_markup=quiz_reply_keyboard(WEB_APP_URL),
    )
    return False


async def _ensure_quiz_and_phone_query(query: types.CallbackQuery) -> bool:
    user_id = query.from_user.id
    quiz_profile = await database.get_user(user_id)
    if (quiz_profile and not await _user_has_phone(user_id)) or await _needs_phone_completion(query.from_user):
        await _show_phone_request(query.message)
        await query.answer()
        return False
    if await database.has_completed_quiz(user_id):
        return True
    await query.message.answer(
        "🧭 Сначала пройди квиз, чтобы я понял твой контекст и открыл рабочие сценарии 👇",
        reply_markup=quiz_reply_keyboard(WEB_APP_URL),
    )
    await query.answer()
    return False


async def _enter_goal_flow(message: types.Message, state: FSMContext) -> None:
    logger.info("GOAL flow open | user=%s chat=%s", message.from_user.id, message.chat.id)
    if await cache.get_data(_goal_lock_key(message.from_user.id)):
        await message.answer(
            "🔒 Твоя цель на 30 дней уже зафиксирована.\n\n"
            "Это сделано специально: чтобы ты не менял направление каждый день.\n"
            "Сначала пройди текущий цикл, потом соберем новую цель.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        return

    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    active_goal = await database.get_active_goal(club_user["id"]) if club_user else None

    await state.clear()
    await state.set_state(GoalStates.waiting_goal_text)
    if active_goal:
        await message.answer(
            f"🎯 Твоя цель сейчас:\n\n{escape(str(active_goal['goal_text']))}",
            reply_markup=private_hub_reply_keyboard(),
        )
    await message.answer(_goal_intro_text(), reply_markup=private_hub_reply_keyboard())


async def _enter_day_launch(message: types.Message, state: FSMContext) -> None:
    logger.info("DAY flow open | user=%s chat=%s", message.from_user.id, message.chat.id)
    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить твой профиль. Попробуй позже.")
        return

    active_goal = await database.get_active_goal(club_user["id"])
    if not active_goal:
        await message.answer(
            "Сначала собери цель на 30 дней через кнопку `🎯 Моя цель (30 дней)` в группе.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        return

    today = _today()
    existing_tasks = await database.get_today_tasks(club_user["id"], today)
    if existing_tasks:
        lines = ["📌 Твой день уже зафиксирован:\n"]
        for idx, task in enumerate(existing_tasks, 1):
            lines.append(f"{idx}. {escape(str(task['task_text']))}")
        await message.answer("\n".join(lines), reply_markup=private_hub_reply_keyboard())
        await message.answer(
            "Все зафиксировано. Когда захочешь вернуться в клуб — вот кнопка 👇",
            reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
        )
        return

    if datetime.now().hour >= 22:
        await message.answer(
            "⏰ На сегодня окно постановки задач уже закрыто.\n\n"
            "После 22:00 новые задачи на сегодня мы не ставим.\n"
            "Возвращайся завтра и жми кнопку дня в группе.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        return

    club_day_index = _current_club_day_index()
    week_plan = active_goal.get("milestones") or []
    day_focus = week_plan[club_day_index - 1] if club_day_index and len(week_plan) >= club_day_index else None

    await state.clear()
    await state.update_data(
        day_goal_id=active_goal["id"],
        day_focus=day_focus,
        day_tasks=[],
    )
    await state.set_state(GoalStates.day_launch)
    text = _start_today_text()
    if day_focus:
        text += f"\n\nСегодняшний фокус из твоего 5-дневного плана:\n📍 {escape(str(day_focus))}"
    await message.answer(text, reply_markup=day_start_keyboard())
    await message.answer(
        "Если пока не хочешь собирать день — можешь вернуться в группу 👇",
        reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
    )


async def _finalize_day_tasks(message: types.Message, actor: types.User, state: FSMContext) -> None:
    data = await state.get_data()
    tasks = data.get("day_tasks", [])
    if not tasks:
        await message.answer("Не вижу задач на сегодня. Давай начнем заново позже.")
        await state.clear()
        return

    club_user = await database.ensure_club_user(
        telegram_id=actor.id,
        username=actor.username,
        first_name=actor.first_name,
        language_code=actor.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить твой профиль. Попробуй позже.")
        await state.clear()
        return

    today = _today()
    day_lock_key = cache.KeyManager.get_day_plan_lock_key(actor.id, today)
    if await cache.get_data(day_lock_key):
        await message.answer(
            "📌 На сегодня задачи уже зафиксированы.\n\n"
            "Можно смотреть их в личке и вечером сдавать отчет в группе.",
            reply_markup=private_hub_reply_keyboard(),
        )
        await state.clear()
        return

    goal_id = data.get("day_goal_id")
    for idx, task_text in enumerate(tasks, 1):
        await database.create_task(
            user_id=club_user["id"],
            task_text=task_text,
            task_date=today,
            task_type=f"day_{idx}",
            goal_id=goal_id,
        )

    await cache.set_data(day_lock_key, "1", ex=cache.seconds_until_midnight())
    await message.answer(_day_summary_text(tasks), reply_markup=private_hub_reply_keyboard())
    if CLUB_GROUP_URL:
        await message.answer(
            "Когда будешь готов к следующему шагу — возвращайся в группу 👇",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
    await state.clear()


async def _enter_report_flow(message: types.Message, state: FSMContext, actor: types.User | None = None) -> None:
    actor = actor or message.from_user
    logger.info("REPORT flow open | user=%s chat=%s", actor.id, message.chat.id)
    club_user = await database.ensure_club_user(
        telegram_id=actor.id,
        username=actor.username,
        first_name=actor.first_name,
        language_code=actor.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить твой профиль. Попробуй позже.")
        return

    today = _today()
    tasks = await database.get_today_tasks(club_user["id"], today)
    if not tasks:
        await message.answer(
            "Сначала собери день через кнопку `📅 Мой день (до 3х задач)`.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        return

    if datetime.now().hour >= 22:
        await message.answer(
            "⏰ Самое время сдать отчет.\n\n"
            "Сейчас нужен один кружочек, в котором ты коротко пройдешься по всем задачам за день."
        )

    existing_report = await database.get_daily_report(club_user["id"], today)
    if existing_report and existing_report.get("status") not in {"redo_requested", "rejected"}:
        await message.answer(
            "📤 За сегодня отчет уже был отправлен.\n\n"
            "Если админ попросит переделать, я отдельно дам тебе новый вход.",
            reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
        )
        return

    task_payload = [{"id": task["id"], "task_text": task["task_text"]} for task in tasks]
    await state.clear()
    await state.update_data(
        report_date=today,
        report_tasks=task_payload,
        report_entries=[],
    )
    await state.set_state(ReportStates.waiting_proof)
    await message.answer(report_service.report_intro_text([task["task_text"] for task in tasks]))
    await message.answer(
        "Запиши один кружочек до 1 минуты, где коротко расскажешь, что сделал по всем задачам 👇",
        reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
    )


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject | None = None) -> None:
    """Handle /start in private and group chats."""
    user_id = message.from_user.id

    try:
        start_arg = command.args.strip() if command and command.args else ""
        logger.info(
            "START received | user=%s chat=%s type=%s arg=%s",
            user_id,
            message.chat.id,
            message.chat.type,
            start_arg or "-",
        )

        if message.chat.type != "private":
            me = await message.bot.get_me()
            await message.answer(
                "Личные сценарии клуба открываются только в личке с ботом.",
                reply_markup=open_bot_private_keyboard(me.username),
            )
            return

        if await cache.get_data(_pending_quiz_key(user_id)):
            await _show_phone_request(message)
            return

        quiz_profile = await database.get_user(user_id)
        has_phone = await _user_has_phone(user_id)
        has_quiz = await database.has_completed_quiz(user_id)

        if (quiz_profile and not has_phone) or await _needs_phone_completion(message.from_user):
            await _show_phone_request(message)
            return

        if start_arg == "goal_setup":
            if not await _ensure_quiz_and_phone_message(message):
                return
            await _enter_goal_flow(message, state)
            return

        if start_arg == "day_setup":
            if not await _ensure_quiz_and_phone_message(message):
                return
            await _enter_day_launch(message, state)
            return

        if start_arg == "report_setup":
            if not await _ensure_quiz_and_phone_message(message):
                return
            await _enter_report_flow(message, state)
            return

        if has_quiz:
            if await _can_show_private_hub(message.from_user):
                await message.answer(
                    "Ты уже внутри LedoLab Business Club 🔥\n\n"
                    "Здесь я помогаю держать фокус, а основная движуха живет через группу и твой ежедневный ритм.",
                    reply_markup=private_hub_reply_keyboard(),
                )
                await message.answer(
                    "Вернуться в группу можно здесь 👇",
                    reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
                )
            else:
                await message.answer(
                    "LedoLab Business Club\n\n"
                    "Ты уже внутри клуба ✅\n\n"
                    "Следующий шаг — вернуться в группу и нажать `🎯 Моя цель (30 дней)`.\n"
                    "Именно с нее начинается твой рабочий маршрут.",
                    reply_markup=club_group_keyboard(CLUB_GROUP_URL),
                )
            return

        welcome_text = (
            "LedoLab Business Club\n\n"
            "Пройди квиз, чтобы мы открыли тебе доступ дальше."
        )
        await message.answer(welcome_text, reply_markup=quiz_reply_keyboard(WEB_APP_URL))
        logger.info("New user: %s", user_id)

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        await message.answer("Error. Try later.")


@router.message(GoalStates.waiting_goal_text)
async def private_goal_text(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await state.clear()
        return
    if not await _ensure_quiz_and_phone_message(message):
        await state.clear()
        return

    goal_text = (message.text or "").strip()
    if len(goal_text) < 5:
        await message.answer("Напиши цель чуть конкретнее, чтобы с ней реально можно было работать 👇")
        return

    await state.update_data(goal_text=goal_text)
    await state.set_state(GoalStates.confirming_goal)
    await message.answer(_goal_confirmation_text(goal_text), reply_markup=goal_text_confirm_keyboard())


@router.callback_query(GoalStates.confirming_goal, F.data == "goal_text_confirm")
async def confirm_goal_text(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return
    if not await _ensure_quiz_and_phone_query(query):
        await state.clear()
        return

    await state.update_data(week_plan=[""] * DAYS_IN_WEEKLY_SPRINT, current_day=1, edit_mode=False)
    await state.set_state(GoalStates.waiting_milestones)
    await query.message.answer(_week_intro_text(), reply_markup=goal_day_step_keyboard(1))
    await query.answer()


@router.callback_query(GoalStates.confirming_goal, F.data == "goal_text_edit")
async def edit_goal_text(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return
    await state.set_state(GoalStates.waiting_goal_text)
    await query.message.answer("Ок, переформулируй свою цель на 30 дней 👇")
    await query.answer()


@router.callback_query(GoalStates.waiting_milestones, lambda q: q.data and q.data.startswith("goal_day:"))
async def start_goal_day_input(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return
    if not await _ensure_quiz_and_phone_query(query):
        await state.clear()
        return

    requested_day = int(query.data.split(":", 1)[1])
    data = await state.get_data()
    current_day = data.get("current_day", 1)
    edit_mode = data.get("edit_mode", False)

    if not edit_mode and requested_day != current_day:
        await query.answer(f"Сейчас доступен только {current_day}-й день.", show_alert=True)
        return

    await state.update_data(active_day=requested_day)
    await state.set_state(GoalStates.waiting_day_text)
    await query.message.answer(_day_focus_prompt(requested_day))
    await query.answer()


@router.message(GoalStates.waiting_day_text)
async def save_goal_day_text(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await state.clear()
        return
    if not await _ensure_quiz_and_phone_message(message):
        await state.clear()
        return

    data = await state.get_data()
    active_day = data.get("active_day")
    if not active_day:
        await message.answer("Не понял, какой день сейчас редактируется. Давай нажмем кнопку дня еще раз.")
        await state.clear()
        return

    text = (message.text or "").strip()
    if len(text) < 3:
        await message.answer("Сделай формулировку чуть понятнее, чтобы по ней можно было реально двигаться 👇")
        return

    week_plan = list(data.get("week_plan", [""] * DAYS_IN_WEEKLY_SPRINT))
    week_plan[active_day - 1] = text
    await state.update_data(week_plan=week_plan, active_day=None)

    if data.get("edit_mode"):
        await state.update_data(edit_mode=False)
        await state.set_state(GoalStates.reviewing)
        await message.answer(_goal_review_text(data["goal_text"], week_plan), reply_markup=goal_review_keyboard())
        return

    if active_day < DAYS_IN_WEEKLY_SPRINT:
        next_day = active_day + 1
        await state.update_data(current_day=next_day)
        await state.set_state(GoalStates.waiting_milestones)
        await message.answer(
            f"✅ День {active_day} сохранен.\n\nТеперь зафиксируем следующий шаг.",
            reply_markup=goal_day_step_keyboard(next_day),
        )
        return

    await state.set_state(GoalStates.reviewing)
    await message.answer(_goal_review_text(data["goal_text"], week_plan), reply_markup=goal_review_keyboard())


@router.callback_query(GoalStates.reviewing, F.data == "goal_edit")
async def goal_edit_request(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    await state.set_state(GoalStates.editing)
    await query.message.answer(
        "Выбери день, который хочешь изменить 👇",
        reply_markup=goal_edit_days_keyboard(),
    )
    await query.answer()


@router.callback_query(GoalStates.editing, lambda q: q.data and q.data.startswith("goal_edit_day:"))
async def goal_edit_day_pick(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    day_number = int(query.data.split(":", 1)[1])
    await state.update_data(active_day=day_number, edit_mode=True)
    await state.set_state(GoalStates.waiting_day_text)
    await query.message.answer(f"Напиши обновленный фокус на день {day_number} 👇")
    await query.answer()


@router.callback_query(GoalStates.reviewing, F.data == "goal_confirm")
async def goal_confirm(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return
    if not await _ensure_quiz_and_phone_query(query):
        await state.clear()
        return

    if await cache.get_data(_goal_lock_key(query.from_user.id)):
        await query.message.answer(
            "🔒 Твоя цель уже зафиксирована на этот цикл. Новую добавим после окончания периода.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        await state.clear()
        await query.answer()
        return

    data = await state.get_data()
    goal_text = data.get("goal_text", "").strip()
    week_plan = data.get("week_plan", [])
    if not goal_text or len(week_plan) != DAYS_IN_WEEKLY_SPRINT or any(not item for item in week_plan):
        await query.message.answer("Сначала закончим маршрут целиком: цель + все 5 дней.")
        await query.answer()
        return

    club_user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not club_user:
        await query.message.answer("Не удалось сохранить план. Попробуй позже.")
        await state.clear()
        await query.answer()
        return

    goal = await database.set_active_goal(club_user["id"], goal_text, week_plan)
    if not goal:
        await query.message.answer("Не удалось сохранить план. Попробуй позже.")
        await state.clear()
        await query.answer()
        return

    await database.award_score(club_user["id"], GOAL_SCORE, "30-day goal set")
    await cache.set_data(_goal_lock_key(query.from_user.id), goal["id"], ex=GOAL_LOCK_TTL)
    weekly_lock_ttl = cache.seconds_until_next_sunday_21()
    for day_number, day_text in enumerate(week_plan, 1):
        await cache.set_data(_goal_day_lock_key(query.from_user.id, day_number), day_text, ex=weekly_lock_ttl)

    candidate_group_chat_ids: list[int] = []
    cached_group_chat_id = await cache.get_data(_last_group_chat_key(query.from_user.id))
    if cached_group_chat_id:
        try:
            candidate_group_chat_ids.append(int(cached_group_chat_id))
        except ValueError:
            pass
    if REPORTS_GROUP_ID and REPORTS_GROUP_ID not in candidate_group_chat_ids:
        candidate_group_chat_ids.append(REPORTS_GROUP_ID)

    if candidate_group_chat_ids:
        display_name = query.from_user.full_name or query.from_user.first_name or "Участник клуба"
        announced = False
        for target_group_chat_id in candidate_group_chat_ids:
            try:
                await query.bot.send_message(
                    target_group_chat_id,
                    _group_goal_announcement(display_name, goal_text, week_plan),
                )
                logger.info(
                    "GOAL announced to group | user=%s chat=%s goal_id=%s",
                    query.from_user.id,
                    target_group_chat_id,
                    goal["id"],
                )
                announced = True
                break
            except Exception as e:
                logger.warning(
                    "Failed to announce goal plan to group | user=%s chat=%s goal_id=%s error=%s",
                    query.from_user.id,
                    target_group_chat_id,
                    goal["id"],
                    e,
                )
        if not announced:
            await query.message.answer(
                "⚠️ План сохранился, но я не смог отправить его в группу.\n"
                "Это уже не твоя ошибка. Я записал это в лог.",
            )

    await state.set_state(GoalStates.ready_decision)
    await state.update_data(day_goal_id=goal["id"])
    await query.message.answer(_ready_after_plan_text(), reply_markup=goal_ready_keyboard())
    await query.answer()


@router.callback_query(GoalStates.ready_decision, F.data == "goal_ready_later")
async def goal_ready_later(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    await query.message.answer(
        "Ок.\n\n"
        "Пока можешь вернуться в группу, освоиться внутри клуба и посмотреть, как двигаются другие участники.\n\n"
        "Когда будешь готов — в группе есть кнопка `📅 Мой день (до 3х задач)`.\n"
        "С нее начинается ежедневная работа.",
        reply_markup=club_group_keyboard(CLUB_GROUP_URL),
    )
    await state.clear()
    await query.answer()


@router.callback_query(GoalStates.ready_decision, F.data == "goal_ready_now")
async def goal_ready_now(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    await state.set_state(GoalStates.day_launch)
    await query.message.answer(_start_today_text(), reply_markup=day_start_keyboard())
    await query.answer()


@router.callback_query(GoalStates.day_launch, F.data == "day_tomorrow")
async def postpone_day_setup(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    await query.message.answer(
        "Хорошо.\n\n"
        "Сегодня не насилуем себя фальшивой продуктивностью.\n"
        "Лучше зайти в работу честно завтра.\n\n"
        "Когда будешь готов — возвращайся через кнопку дня в группе 👇",
        reply_markup=club_group_keyboard(CLUB_GROUP_URL),
    )
    await state.clear()
    await query.answer()


@router.callback_query(GoalStates.day_launch, F.data == "day_go")
async def start_day_tasks(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    await state.update_data(day_tasks=[], expected_task_number=1)
    await state.set_state(TaskStates.collecting_day_tasks)
    await query.message.answer(_task_prompt(1))
    await query.answer()


@router.message(TaskStates.collecting_day_tasks)
async def collect_day_tasks(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await state.clear()
        return
    if not await _ensure_quiz_and_phone_message(message):
        await state.clear()
        return

    task_text = (message.text or "").strip()
    if len(task_text) < 3:
        await message.answer("Сделай задачу чуть конкретнее, чтобы вечером ее можно было честно проверить 👇")
        return

    data = await state.get_data()
    tasks = list(data.get("day_tasks", []))
    expected_task_number = data.get("expected_task_number", len(tasks) + 1)

    tasks.append(task_text)
    await state.update_data(day_tasks=tasks)

    if len(tasks) >= 3:
        await _finalize_day_tasks(message, message.from_user, state)
        return

    next_task_number = len(tasks) + 1
    await state.update_data(expected_task_number=next_task_number)
    await message.answer(
        _task_skip_reason_text() + "\n\n" + _task_prompt(next_task_number),
        reply_markup=day_task_next_keyboard(next_task_number),
    )


@router.callback_query(TaskStates.collecting_day_tasks, lambda q: q.data and q.data.startswith("day_task_next:"))
async def continue_day_tasks(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    next_task_number = int(query.data.split(":", 1)[1])
    await state.update_data(expected_task_number=next_task_number)
    await query.message.answer(_task_prompt(next_task_number))
    await query.answer()


@router.callback_query(TaskStates.collecting_day_tasks, F.data == "day_task_skip")
async def skip_remaining_day_tasks(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    await _finalize_day_tasks(query.message, query.from_user, state)
    await query.answer()


@router.message(ReportStates.waiting_proof, F.video_note)
async def capture_report_proof(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await state.clear()
        return
    if not await _ensure_quiz_and_phone_message(message):
        await state.clear()
        return

    data = await state.get_data()
    tasks = data.get("report_tasks", [])
    entries = [{
        "task_id": tasks[0]["id"] if tasks else None,
        "task_text": "Единый отчет за день",
        "task_lines": [task["task_text"] for task in tasks],
        "proof_type": "video_note",
        "file_id": message.video_note.file_id,
        "comment_text": "",
    }]
    await state.update_data(report_entries=entries)
    await state.set_state(ReportStates.reviewing)
    await message.answer(
        "Кружочек записан ✅\n\nЕсли все ок — подтверждай. Если хочешь переписать, жми заменить.",
        reply_markup=report_service.report_preview_keyboard(),
    )


@router.message(
    ReportStates.waiting_proof,
    F.text.regexp(r"^/menu(@[A-Za-z0-9_]+)?$"),
)
@router.message(
    ReportStates.waiting_task_comment,
    F.text.regexp(r"^/menu(@[A-Za-z0-9_]+)?$"),
)
async def exit_report_state_to_menu(message: types.Message, state: FSMContext) -> None:
    logger.info(
        "REPORT state interrupted by /menu | user=%s chat=%s type=%s",
        message.from_user.id,
        message.chat.id,
        message.chat.type,
    )
    await state.clear()
    await cmd_menu(message)


@router.message(ReportStates.waiting_proof)
async def reject_report_without_proof(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await state.clear()
        return
    await message.answer(
        "Нужен именно кружочек.\n"
        "И помни: в Telegram кружочек длится до 1 минуты."
    )


@router.callback_query(ReportStates.reviewing, F.data == "report_redo")
async def redo_report_preview(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return
    await state.update_data(report_entries=[])
    await state.set_state(ReportStates.waiting_proof)
    await query.message.answer(
        "Ок, переписываем отчет.\n\nЗапиши новый кружочек до 1 минуты 👇",
        reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
    )
    await query.answer()


@router.callback_query(ReportStates.reviewing, F.data == "report_send")
async def send_report_preview(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return
    if not await _ensure_quiz_and_phone_query(query):
        await state.clear()
        return

    club_user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not club_user:
        await query.message.answer("Не удалось сохранить отчет. Попробуй позже.")
        await state.clear()
        await query.answer()
        return

    if not REPORTS_GROUP_ID:
        await query.message.answer("Не настроена группа для публикации отчетов. Сначала пропиши REPORTS_GROUP_ID.")
        await query.answer()
        return

    data = await state.get_data()
    entries = data.get("report_entries", [])
    if not entries:
        await query.message.answer("В отчете пока нет ни одного доказательства. Сначала собери его.")
        await query.answer()
        return

    report = await report_service.save_daily_report(
        user_id=club_user["id"],
        username=query.from_user.username,
        report_date=data.get("report_date", _today()),
        entries=entries,
    )
    if not report:
        await query.message.answer("Не удалось сохранить отчет. Попробуй еще раз.")
        await state.clear()
        await query.answer()
        return

    logger.info(
        "REPORT submitted | user=%s report_id=%s date=%s",
        query.from_user.id,
        report["id"],
        data.get("report_date", _today()),
    )
    await database.update_tasks_status([entry["task_id"] for entry in entries], "reported")
    group_message = await query.bot.send_message(
        REPORTS_GROUP_ID,
        report["summary_text"],
        reply_markup=report_service.group_report_vote_keyboard(report["id"]),
    )
    first_entry = entries[0]
    if first_entry.get("proof_type") == "video_note" and first_entry.get("file_id"):
        media_message = await query.bot.send_video_note(
            REPORTS_GROUP_ID,
            first_entry["file_id"],
            reply_to_message_id=group_message.message_id,
        )
        await cache.set_data(_report_media_msg_key(report["id"]), str(media_message.message_id), ex=14 * 24 * 60 * 60)
        await cache.set_data(_report_media_reverse_key(REPORTS_GROUP_ID, media_message.message_id), report["id"], ex=14 * 24 * 60 * 60)
    await database.set_daily_report_group_post(report["id"], REPORTS_GROUP_ID, group_message.message_id)

    await query.message.answer(
        "🔥 Отчет отправлен.\n\n"
        "Баллы уже начислены: +30.\n"
        "Теперь отчет живет в группе. Если клуб сочтет его сомнительным, я сам подключу админа.",
        reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
    )
    await state.clear()
    await query.answer()


@router.callback_query(F.data.startswith("user_report:redo:"))
async def redo_report_after_admin_comment(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return
    if not await _ensure_quiz_and_phone_query(query):
        return

    await query.message.answer(
        "Ок, переделываем отчет с нуля.\n\n"
        "Я снова проведу тебя по задачам по одной, чтобы ничего не потерялось."
    )
    await _enter_report_flow(query.message, state, query.from_user)
    await query.answer()


@router.callback_query(F.data.startswith("user_report:drop:"))
async def drop_report_after_admin_comment(query: types.CallbackQuery) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    report_id = query.data.split(":", 2)[2]
    await database.set_daily_report_status(report_id, "dropped")
    await query.message.answer(
        "Принял.\n\n"
        "Сегодня этот отчет закрыт без пересдачи.\n"
        "Завтра будет новый день и новый шанс показать нормальную дисциплину.\n\n"
        "Важно: такие истории копятся и могут закончиться вылетом из клуба.",
        reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
    )
    await query.answer()


@router.message(F.text == "🎯 Моя цель 30 дней")
async def show_30_day_goal(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_quiz_and_phone_message(message):
        return

    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось получить твою цель. Попробуй позже.")
        return

    active_goal = await database.get_active_goal(club_user["id"])
    if not active_goal:
        await _enter_goal_flow(message, state)
        return

    await message.answer(
        f"🎯 Твоя цель на 30 дней:\n\n{escape(str(active_goal['goal_text']))}",
        reply_markup=private_hub_reply_keyboard(),
    )
    await message.answer(
        "Если хочешь продолжить работу в клубе — возвращайся в группу 👇",
        reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
    )


@router.message(F.text == "📅 Мой план на 5 дней")
async def show_5_day_goal(message: types.Message) -> None:
    if not await _ensure_quiz_and_phone_message(message):
        return

    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось получить твой план. Попробуй позже.")
        return

    week_plan = await database.get_week_plan_for_user(club_user["id"])
    if not week_plan:
        await message.answer("Пока план на 5 дней не задан. Сначала собери цель на 30 дней.")
        return

    lines = ["📅 Твой план на 5 дней:\n"]
    for idx, item in enumerate(week_plan, 1):
        lines.append(f"{idx}. {escape(str(item))}")
    await message.answer("\n".join(lines), reply_markup=private_hub_reply_keyboard())
    await message.answer(
        "Готов двигаться дальше? Возвращайся в группу 👇",
        reply_markup=return_to_group_keyboard(CLUB_GROUP_URL),
    )


@router.message(F.text == "📌 Мой день (до 3х задач)")
async def show_day_hint(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_quiz_and_phone_message(message):
        return
    await _enter_day_launch(message, state)


@router.message(Command("menu"))
async def cmd_menu(message: types.Message) -> None:
    """Show inline working menu in the group only."""
    try:
        logger.info(
            "MENU command | user=%s chat=%s type=%s text=%s",
            message.from_user.id,
            message.chat.id,
            message.chat.type,
            (message.text or "").strip(),
        )
        if message.chat.type == "private":
            if await database.has_completed_quiz(message.from_user.id):
                await message.answer(
                    "Рабочие кнопки доступны только в группе LedoLab Business Club.",
                    reply_markup=club_group_keyboard(CLUB_GROUP_URL),
                )
            else:
                await message.answer(
                    "🧭 Сначала пройди квиз в личке, а потом уже переходи к рабочим кнопкам клуба 👇",
                    reply_markup=quiz_reply_keyboard(WEB_APP_URL),
                )
            return

        if not await database.has_completed_quiz(message.from_user.id):
            await message.answer(
                "🧭 Сначала пройди квиз в личке бота.\n\n"
                "Пока квиз не пройден, рабочее меню клуба закрыто 👇",
                reply_markup=open_bot_private_keyboard((await message.bot.get_me()).username),
            )
            return

        await cache.set_data(_last_group_chat_key(message.from_user.id), str(message.chat.id), ex=7 * 24 * 60 * 60)
        me = await message.bot.get_me()
        from app.keyboards.inline.start import club_main_menu  # local import to avoid cycle in type checkers

        await message.answer(
            "LedoLab Business Club — клуб сильнейших\n\nРабочее меню:",
            reply_markup=club_main_menu(me.username),
        )
    except Exception as e:
        logger.error("Error in /menu: %s", e, exc_info=True)
        await message.answer("Error. Try later.")


@router.message(F.text.regexp(r"^/menu(@[A-Za-z0-9_]+)?$"))
async def cmd_menu_fallback(message: types.Message) -> None:
    logger.info(
        "MENU fallback | user=%s chat=%s type=%s text=%s",
        message.from_user.id,
        message.chat.id,
        message.chat.type,
        (message.text or "").strip(),
    )
    await cmd_menu(message)


@router.message(Command("reset"))
async def admin_reset_user(message: types.Message) -> None:
    """Admin-only full reset for a user by telegram id or @username."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда только для админа.")
        return
    await _delete_command_message_safely(message)

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "Используй так:\n"
            "/reset @username\n"
            "/reset 123456789"
        )
        return

    target_telegram_id = await database.resolve_telegram_id_by_handle_or_id(parts[1])
    if not target_telegram_id:
        await message.answer("Не смог найти такого пользователя по username или id.")
        return

    db_stats = await database.reset_user_data(target_telegram_id)
    redis_deleted = await cache.delete_keys_by_patterns([
        f"pending_quiz:{target_telegram_id}",
        f"goal_lock:{target_telegram_id}",
        f"goal_day_lock:{target_telegram_id}:*",
        f"day_plan_lock:{target_telegram_id}:*",
        f"user:{target_telegram_id}*",
        f"task:{target_telegram_id}:*",
        f"report:{target_telegram_id}:*",
        f"fsm:{target_telegram_id}*",
        f"lock:{target_telegram_id}:*",
        f"streak:{target_telegram_id}",
        f"score:{target_telegram_id}",
        f"leda_fsm*{target_telegram_id}*",
    ])

    await message.answer(
        "🧹 Сброс выполнен.\n\n"
        f"Telegram ID: <code>{target_telegram_id}</code>\n"
        f"Удалено из quiz_data: {db_stats['quiz_data']}\n"
        f"Удалено из goals: {db_stats['goals']}\n"
        f"Удалено из daily_tasks: {db_stats['daily_tasks']}\n"
        f"Удалено из reports: {db_stats['reports']}\n"
        f"Удалено из daily_reports: {db_stats['daily_reports']}\n"
        f"Удалено из daily_report_votes: {db_stats['daily_report_votes']}\n"
        f"Удалено из scores: {db_stats['scores']}\n"
        f"Удалено из daily_statuses: {db_stats['daily_statuses']}\n"
        f"Удалено из users: {db_stats['users']}\n"
        f"Удалено Redis-ключей: {redis_deleted}"
    )


@router.message(Command("reject"))
async def admin_reject_report(message: types.Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда только для админа.")
        return
    await _delete_command_message_safely(message)

    parts = (message.text or "").split()
    report = None
    report_id = ""
    if len(parts) >= 2:
        report_id = parts[1].strip()
        report = await database.get_daily_report_by_id(report_id)
    elif message.reply_to_message:
        replied = message.reply_to_message
        report = await database.get_daily_report_by_group_message(replied.chat.id, replied.message_id)
        if not report:
            reverse_key = _report_media_reverse_key(replied.chat.id, replied.message_id)
            reverse_report_id = await cache.get_data(reverse_key)
            if reverse_report_id:
                report = await database.get_daily_report_by_id(reverse_report_id)
        if report:
            report_id = report["id"]

    if not report:
        await message.answer("Не нашел такой отчет. Используй /reject REPORT_ID или ответь /reject на сообщение отчета.")
        return

    report_user = await database.get_club_user_by_id(report["user_id"])
    if not report_user:
        await message.answer("Не нашел владельца отчета.")
        return

    task_rows = await database.get_today_tasks(report["user_id"], report["report_date"])
    await database.update_tasks_status([task["id"] for task in task_rows], "waiting_report")

    score_awarded = int(report.get("score_awarded") or 0)
    if score_awarded:
        await database.award_score(report["user_id"], -score_awarded, "Admin rejected daily report")

    warnings = await database.increment_user_warnings(report["user_id"], 1)
    await database.delete_daily_report(report_id)

    if report.get("group_chat_id") and report.get("group_message_id"):
        try:
            await message.bot.delete_message(int(report["group_chat_id"]), int(report["group_message_id"]))
        except Exception as e:
            logger.warning("Failed to delete report summary message %s: %s", report_id, e)

        media_message_id = await cache.get_data(_report_media_msg_key(report_id))
    if media_message_id and report.get("group_chat_id"):
        try:
            await message.bot.delete_message(int(report["group_chat_id"]), int(media_message_id))
        except Exception as e:
            logger.warning("Failed to delete report media message %s: %s", report_id, e)
        await cache.delete_data(_report_media_msg_key(report_id))
        await cache.delete_data(_report_media_reverse_key(int(report["group_chat_id"]), int(media_message_id)))

    try:
        await message.bot.send_message(
            int(report_user["telegram_id"]),
            "⚠️ Твой отчет был отклонен админом.\n\n"
            "Я записал тебе warning и открыл возможность сдать отчет еще раз сегодня.\n"
            "Пожалуйста, пересобери его нормально и без мусора.",
            reply_markup=open_private_flow_keyboard((await message.bot.get_me()).username, "report_setup", "ПЕРЕСДАТЬ ОТЧЕТ"),
        )
    except Exception as e:
        logger.warning("Failed to notify user about rejected report %s: %s", report_id, e)

    await message.answer(
        "⚠️ Отчет отклонен.\n\n"
        f"Report ID: <code>{report_id}</code>\n"
        f"User TG ID: <code>{report_user['telegram_id']}</code>\n"
        f"Warnings now: {int((warnings or {}).get('warnings_count') or 0)}"
    )


@router.message(Command("admin"))
async def admin_commands(message: types.Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда только для админа.")
        return
    await _delete_command_message_safely(message)

    await message.answer(
        "🛠 Админ-команды\n\n"
        "/admin — список всех админских команд\n"
        "/reset @username — снести юзера под ноль\n"
        "/reset 123456789 — снести юзера по Telegram ID\n"
        "/reject REPORT_ID — отклонить конкретный отчет, выдать warning и открыть пересдачу\n"
        "reply /reject — отклонить отчет ответом на его сообщение в группе"
    )
