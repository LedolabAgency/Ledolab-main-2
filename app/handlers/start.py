"""
Start handler - initial bot greeting and quiz link.
"""

import logging
from datetime import datetime, time, timedelta
from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from app.config import WEB_APP_URL, CLUB_GROUP_URL, GOAL_SCORE, ADMIN_IDS
from app.keyboards.inline.start import (
    quiz_reply_keyboard,
    club_group_keyboard,
    open_bot_private_keyboard,
    club_main_menu,
    goal_day_step_keyboard,
    goal_review_keyboard,
    goal_edit_days_keyboard,
    private_hub_reply_keyboard,
    report_count_keyboard,
    contact_reply_keyboard,
)
from app import database, cache
from app.services import rating_service, report_service, task_service
from app.states.quiz import GoalStates, TaskStates, ReportStates

logger = logging.getLogger(__name__)
router = Router()

GOAL_LOCK_TTL = 30 * 24 * 60 * 60
DAYS_IN_WEEKLY_SPRINT = 5


def _goal_lock_key(user_id: int) -> str:
    return f"goal_lock:{user_id}"


def _goal_day_lock_key(user_id: int, day_number: int) -> str:
    return f"goal_day_lock:{user_id}:{day_number}"


def _goal_review_text(goal_text: str, week_plan: list[str]) -> str:
    lines = [
        "Проверь, пожалуйста, свои цели:",
        "",
        f"🎯 Цель на 30 дней: {goal_text}",
        "",
    ]
    for index, day_text in enumerate(week_plan, 1):
        lines.append(f"День {index} — {day_text}")
    return "\n".join(lines)


def _today() -> str:
    return datetime.now().date().isoformat()


def _pending_quiz_key(user_id: int) -> str:
    return f"pending_quiz:{user_id}"


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


async def _ensure_private_quiz_gate(message: types.Message) -> bool:
    if await database.has_completed_quiz(message.from_user.id):
        return True
    await message.answer(
        "🧭 Сначала пройди квиз, чтобы я понял твой контекст и открыл рабочие сценарии 👇",
        reply_markup=quiz_reply_keyboard(WEB_APP_URL),
    )
    return False


async def _ensure_private_quiz_gate_query(query: types.CallbackQuery) -> bool:
    if await database.has_completed_quiz(query.from_user.id):
        return True
    await query.message.answer(
        "🧭 Сначала пройди квиз, чтобы я понял твой контекст и открыл рабочие сценарии 👇",
        reply_markup=quiz_reply_keyboard(WEB_APP_URL),
    )
    await query.answer()
    return False


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject | None = None) -> None:
    """
    /start command handler.
    Shows welcome message and quiz link.
    """
    user_id = message.from_user.id
    
    try:
        start_arg = command.args.strip() if command and command.args else ""

        if message.chat.type != "private":
            me = await message.bot.get_me()
            await message.answer(
                "Квиз доступен только в личке с ботом.\n\n"
                "Открой LedoLab Business Club в личных сообщениях и пройди onboarding там.",
                reply_markup=open_bot_private_keyboard(me.username),
            )
            return

        if await cache.get_data(_pending_quiz_key(user_id)):
            await message.answer(
                "📱 Почти готово.\n\nПоследнее действие — поделиться номером телефона, чтобы мы завершили вход в клуб 👇",
                reply_markup=contact_reply_keyboard(),
            )
            return

        if start_arg == "goal_setup":
            if not await _ensure_private_quiz_gate(message):
                return

            if await cache.get_data(_goal_lock_key(user_id)):
                await message.answer(
                    "Цель на 30 дней уже зафиксирована. Пока срок не закончится, новую добавить нельзя.",
                    reply_markup=private_hub_reply_keyboard(),
                )
                return

            await state.clear()
            await state.set_state(GoalStates.waiting_goal_text)
            await message.answer("Какая твоя цель на 30 дней?")
            return

        if start_arg == "day_setup":
            if not await _ensure_private_quiz_gate(message):
                return

            club_user = await database.ensure_club_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                language_code=message.from_user.language_code or "ru",
            )
            if not club_user:
                await message.answer("Не удалось подготовить твой профиль. Попробуй позже.")
                return

            week_plan = await database.get_week_plan_for_user(club_user["id"])
            if not week_plan:
                await message.answer("Сначала задай цель на 30 дней, а потом перейдем к дню.")
                return

            today = _today()
            tasks = await database.get_today_tasks(club_user["id"], today)
            if tasks:
                lines = ["📅 Твои задачи на сегодня:\n"]
                for idx, task in enumerate(tasks, 1):
                    lines.append(f"{idx}. {task['task_text']}")
                await message.answer("\n".join(lines), reply_markup=private_hub_reply_keyboard())
                return

            club_day_index = _current_club_day_index()
            if club_day_index is None:
                await message.answer(
                    "😌 Сейчас окно отдыха внутри недельного цикла.\n\n"
                    "Новый рабочий спринт открыт с воскресенья 21:00 до следующего воскресенья 21:00."
                )
                return

            await state.set_state(TaskStates.waiting_day_tasks)
            day_focus = week_plan[club_day_index - 1] if len(week_plan) >= club_day_index else week_plan[0]
            active_goal = await database.get_active_goal(club_user["id"])
            await state.update_data(day_focus=day_focus, day_goal_id=active_goal["id"] if active_goal else None)
            await message.answer(
                "📅 Мой день (до 3х задач)\n\n"
                f"Фокус дня:\n{day_focus}\n\n"
                "Отправь до 3 задач на сегодня. Каждую задачу с новой строки 👇",
                reply_markup=private_hub_reply_keyboard(),
            )
            return

        if start_arg == "report_setup":
            if not await _ensure_private_quiz_gate(message):
                return

            club_user = await database.ensure_club_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                language_code=message.from_user.language_code or "ru",
            )
            if not club_user:
                await message.answer("Не удалось подготовить твой профиль. Попробуй позже.")
                return

            tasks = await database.get_today_tasks(club_user["id"], _today())
            if not tasks:
                await message.answer(
                    "Сначала собери день через кнопку `📅 Мой день (до 3х задач)`.",
                    reply_markup=private_hub_reply_keyboard(),
                )
                return

            lines = ["📤 Что ты сделал сегодня?\n"]
            for idx, task in enumerate(tasks, 1):
                lines.append(f"{idx}. {task['task_text']}")
            await state.set_state(ReportStates.waiting_completed_count)
            await state.update_data(
                task_ids=[task["id"] for task in tasks],
                task_texts=[task["task_text"] for task in tasks],
            )
            await message.answer("\n".join(lines), reply_markup=report_count_keyboard())
            return

        if start_arg == "rating_setup":
            if not await _ensure_private_quiz_gate(message):
                return
            users = await rating_service.get_rating_leaderboard()
            text = await rating_service.format_rating_text(users)
            await message.answer(text, reply_markup=private_hub_reply_keyboard())
            return

        if start_arg == "rules_setup":
            if not await _ensure_private_quiz_gate(message):
                return
            await message.answer(
                "📘 Как работает LedoLab Business Club\n\n"
                "1. Ставишь 1 цель на 30 дней.\n"
                "2. Разбиваешь ее на 5 рабочих дней недели.\n"
                "3. Каждый день фиксируешь до 3 задач.\n"
                "4. Вечером сдаешь отчет и получаешь баллы.\n"
                "5. Лучшие участники поднимаются в рейтинге и получают доступ к призам.",
                reply_markup=private_hub_reply_keyboard(),
            )
            return

        has_quiz = await database.has_completed_quiz(user_id)
        if has_quiz:
            await message.answer(
                f"Привет, {message.from_user.first_name}! Ты уже в LedoLab Business Club 🔥",
                reply_markup=private_hub_reply_keyboard(),
            )
            await message.answer("Рабочие действия доступны в группе, а личка помогает быстро вспомнить цель и план.")
            return
        
        # New user - show welcome
        welcome_text = (
            "LedoLab Business Club\n\n"
            "Пройди квиз, чтобы мы открыли тебе доступ дальше."
        )
        
        await message.answer(welcome_text, reply_markup=quiz_reply_keyboard(WEB_APP_URL))
        logger.info(f"New user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.answer("Error. Try later.")


@router.message(GoalStates.waiting_goal_text)
async def private_goal_text(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer("Цель на 30 дней задается только в личке с ботом.")
        await state.clear()
        return

    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз, а потом уже собирай большую цель 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        await state.clear()
        return

    if await cache.get_data(_goal_lock_key(message.from_user.id)):
        await message.answer(
            "Цель на 30 дней уже зафиксирована. Изменить ее можно только после окончания текущего периода.",
            reply_markup=private_hub_reply_keyboard(),
        )
        await state.clear()
        return

    await state.update_data(goal_text=message.text.strip())
    await state.set_state(GoalStates.waiting_milestones)
    await state.update_data(week_plan=[""] * DAYS_IN_WEEKLY_SPRINT, current_day=1, edit_mode=False)
    await message.answer(
        "Ок.\n\nТеперь разобьем цель на 5 рабочих дней недели.",
        reply_markup=goal_day_step_keyboard(1),
    )


@router.message(TaskStates.waiting_day_tasks)
async def private_save_day_tasks(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    if not await _ensure_private_quiz_gate(message):
        await state.clear()
        return

    raw_tasks = [line.strip("-• \t") for line in message.text.splitlines() if line.strip()]
    if not raw_tasks or len(raw_tasks) > 3:
        await message.answer("Отправь от 1 до 3 задач, каждую с новой строки.")
        return

    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить твой профиль. Попробуй позже.")
        await state.clear()
        return

    today = _today()
    day_lock_key = cache.KeyManager.get_day_plan_lock_key(message.from_user.id, today)
    if await cache.get_data(day_lock_key):
        await message.answer("На сегодня задачи уже зафиксированы. Можно смотреть их и вечером сдавать отчет.")
        await state.clear()
        return

    state_data = await state.get_data()
    goal_id = state_data.get("day_goal_id")
    for idx, task_text in enumerate(raw_tasks, 1):
        await task_service.set_daily_task(
            user_id=club_user["id"],
            task_text=task_text,
            today=today,
            task_type=f"day_{idx}",
            goal_id=goal_id,
        )
    await cache.set_data(day_lock_key, "1", ex=cache.seconds_until_midnight())
    await message.answer(
        "📅 День зафиксирован.\n\nТвои задачи сохранены. Вечером жми `📤 Сдать отчет`.",
        reply_markup=private_hub_reply_keyboard(),
    )
    await state.clear()


@router.callback_query(ReportStates.waiting_completed_count, F.data.startswith("report_count:"))
async def private_capture_report_count(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        return
    if not await _ensure_private_quiz_gate_query(query):
        return

    completed_count = int(query.data.split(":", 1)[1])
    await state.update_data(completed_count=completed_count)
    await state.set_state(ReportStates.waiting_report_text)
    await query.message.answer(
        "📤 Отправь короткий отчет:\n— что сделал\n— какой результат\n— что дальше",
        reply_markup=private_hub_reply_keyboard(),
    )
    await query.answer()


@router.message(ReportStates.waiting_report_text)
async def private_save_report_text(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    if not await _ensure_private_quiz_gate(message):
        await state.clear()
        return

    await state.update_data(report_text=message.text.strip())
    await state.set_state(ReportStates.waiting_proof)
    await message.answer(
        "Теперь отправь подтверждение.\n\nМожно прислать кружок, видео или короткий текст-пруф.",
        reply_markup=private_hub_reply_keyboard(),
    )


@router.message(ReportStates.waiting_proof, F.video | F.video_note | F.text)
async def private_finish_report_flow(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    if not await _ensure_private_quiz_gate(message):
        await state.clear()
        return

    data = await state.get_data()
    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить твой профиль. Попробуй позже.")
        await state.clear()
        return

    proof_type = "text"
    file_id = None
    if message.video_note:
        proof_type = "video"
        file_id = message.video_note.file_id
    elif message.video:
        proof_type = "video"
        file_id = message.video.file_id

    proof_text = data.get("report_text", "")
    if message.text and message.text != proof_text:
        proof_text = f"{proof_text}\n\nProof: {message.text}".strip()

    task_ids = data.get("task_ids", [])
    report = await report_service.submit_report(
        user_id=club_user["id"],
        task_id=task_ids[0],
        report_text=proof_text,
        completed_tasks=data.get("completed_count", 0),
        proof_type=proof_type,
        file_id=file_id,
    )
    if not report:
        await message.answer("Не удалось сохранить отчет. Попробуй еще раз.")
        await state.clear()
        return

    await database.update_tasks_status(task_ids, "reported")

    score = report["score_awarded"]
    mood = "🔥 Сильный день" if score >= 40 else "🔥 Хороший день" if score >= 20 else "🔥 Движение есть"

    await message.answer(
        f"Отчет принят.\n\nБаллы начислены: +{score}\n{mood}",
        reply_markup=private_hub_reply_keyboard(),
    )
    await state.clear()


@router.callback_query(GoalStates.waiting_milestones, lambda q: q.data and q.data.startswith("goal_day:"))
async def start_goal_day_input(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    requested_day = int(query.data.split(":", 1)[1])
    data = await state.get_data()
    current_day = data.get("current_day", 1)
    edit_mode = data.get("edit_mode", False)

    if not edit_mode and requested_day != current_day:
        await query.answer(f"Сейчас доступен только {current_day}-й день.", show_alert=True)
        return

    if await cache.get_data(_goal_day_lock_key(query.from_user.id, requested_day)):
        await query.answer(f"{requested_day}-й день уже зафиксирован и заблокирован.", show_alert=True)
        return

    await state.update_data(active_day=requested_day)
    await state.set_state(GoalStates.waiting_day_text)
    await query.message.answer(f"Напиши цель на {requested_day}-й день.")
    await query.answer()


@router.message(GoalStates.waiting_day_text)
async def save_goal_day_text(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer("План на 5 дней заполняется только в личке с ботом.")
        await state.clear()
        return

    data = await state.get_data()
    active_day = data.get("active_day")
    if not active_day:
        await message.answer("Не удалось определить день. Нажми кнопку дня еще раз.")
        await state.clear()
        return

    week_plan = list(data.get("week_plan", [""] * DAYS_IN_WEEKLY_SPRINT))
    week_plan[active_day - 1] = message.text.strip()
    await state.update_data(week_plan=week_plan)

    edit_mode = data.get("edit_mode", False)
    if edit_mode:
        await state.update_data(edit_mode=False, active_day=None)
        await state.set_state(GoalStates.reviewing)
        await message.answer(
            _goal_review_text(data["goal_text"], week_plan),
            reply_markup=goal_review_keyboard(),
        )
        return

    if active_day < DAYS_IN_WEEKLY_SPRINT:
        next_day = active_day + 1
        await state.update_data(current_day=next_day, active_day=None)
        await state.set_state(GoalStates.waiting_milestones)
        await message.answer(
            f"{active_day}-й день сохранен.",
            reply_markup=goal_day_step_keyboard(next_day),
        )
        return

    await state.update_data(current_day=DAYS_IN_WEEKLY_SPRINT, active_day=None)
    await state.set_state(GoalStates.reviewing)
    await message.answer(
        _goal_review_text(data["goal_text"], week_plan),
        reply_markup=goal_review_keyboard(),
    )


@router.callback_query(GoalStates.reviewing, F.data == "goal_edit")
async def goal_edit_request(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    await state.set_state(GoalStates.editing)
    await query.message.answer(
        "Выбери день, который хочешь изменить.",
        reply_markup=goal_edit_days_keyboard(),
    )
    await query.answer()


@router.callback_query(GoalStates.editing, lambda q: q.data and q.data.startswith("goal_edit_day:"))
async def goal_edit_day_pick(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    day_number = int(query.data.split(":", 1)[1])
    if await cache.get_data(_goal_day_lock_key(query.from_user.id, day_number)):
        await query.answer(f"{day_number}-й день уже заблокирован Redis-ключом.", show_alert=True)
        return

    await state.update_data(active_day=day_number, edit_mode=True)
    await state.set_state(GoalStates.waiting_day_text)
    await query.message.answer(f"Напиши обновленную цель на {day_number}-й день.")
    await query.answer()


@router.callback_query(GoalStates.reviewing, F.data == "goal_confirm")
async def goal_confirm(query: types.CallbackQuery, state: FSMContext) -> None:
    if query.message.chat.type != "private":
        await query.answer("Этот шаг доступен только в личке.", show_alert=True)
        return

    if await cache.get_data(_goal_lock_key(query.from_user.id)):
        await query.message.answer(
            "Цель уже зафиксирована и заблокирована на 30 дней.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        await state.clear()
        await query.answer()
        return

    data = await state.get_data()
    week_plan = data.get("week_plan", [])
    if len(week_plan) != DAYS_IN_WEEKLY_SPRINT or any(not item for item in week_plan):
        await query.message.answer("Сначала заполни все 5 дней.")
        await query.answer()
        return

    club_user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not club_user:
        await query.message.answer("Не удалось сохранить цель. Попробуй позже.")
        await query.answer()
        await state.clear()
        return

    goal = await database.set_active_goal(club_user["id"], data["goal_text"], week_plan)
    if not goal:
        await query.message.answer("Не удалось сохранить цель. Попробуй позже.")
        await query.answer()
        await state.clear()
        return

    await database.award_score(club_user["id"], GOAL_SCORE, "30-day goal set")
    await cache.set_data(_goal_lock_key(query.from_user.id), goal["id"], ex=GOAL_LOCK_TTL)
    weekly_lock_ttl = cache.seconds_until_next_sunday_21()
    for day_number, day_text in enumerate(week_plan, 1):
        await cache.set_data(_goal_day_lock_key(query.from_user.id, day_number), day_text, ex=weekly_lock_ttl)

    await query.message.answer(
        "🚀 Цели утверждены и сохранены.\n\nТеперь возвращайся в группу и открывай /menu -> 📅 Мой день (до 3х задач).",
        reply_markup=private_hub_reply_keyboard(),
    )
    if CLUB_GROUP_URL:
        await query.message.answer(
            "Если хочешь вернуться в группу прямо сейчас — вот кнопка ниже 👇",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
    await state.clear()
    await query.answer()


@router.message(F.text == "🎯 Моя цель 30 дней")
async def show_30_day_goal(message: types.Message) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз, чтобы я мог открыть тебе цель и маршрут 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
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
        await message.answer("Пока цель не задана. Нажми кнопку цели и мы соберем ее вместе.")
        return

    await message.answer(
        f"🎯 Твоя цель на 30 дней:\n\n{active_goal['goal_text']}",
        reply_markup=private_hub_reply_keyboard(),
    )


@router.message(F.text == "📅 Мой план на 5 дней")
async def show_5_day_goal(message: types.Message) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз, а потом я покажу тебе план на 5 дней 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
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
        lines.append(f"{idx}. {item}")
    await message.answer("\n".join(lines), reply_markup=private_hub_reply_keyboard())


@router.message(F.text == "📌 Мой день (до 3х задач)")
async def show_day_hint(message: types.Message) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз, а потом уже собирай свой день 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        return

    await message.answer(
        "📌 День собирается прямо здесь, в боте.\n\n"
        "Если сегодня задачи еще не собраны, открой инлайн-кнопку из группы или используй deep-link на день.",
        reply_markup=private_hub_reply_keyboard(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: types.Message) -> None:
    """
    /menu command handler.
    Shows working inline buttons in the group only.
    """
    try:
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

        me = await message.bot.get_me()
        await message.answer(
            "LedoLab Business Club\n\nРабочее меню:",
            reply_markup=club_main_menu(me.username),
        )
    except Exception as e:
        logger.error(f"Error in /menu: {e}", exc_info=True)
        await message.answer("Error. Try later.")


@router.message(Command("reset"))
async def admin_reset_user(message: types.Message) -> None:
    """Admin-only full reset for a user by telegram id or @username."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда только для админа.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Используй так: /reset @username или /reset 123456789")
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
        f"Удалено из users: {db_stats['users']}\n"
        f"Удалено Redis-ключей: {redis_deleted}"
    )
