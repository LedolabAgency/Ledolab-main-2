"""Start handler and private deep-link flows for LedoLab Business Club."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext

from app import cache, database
from app.services import referral_service, report_service, mention_service
from app.config import CLUB_GROUP_URL, GROUP_ENTRY_URL, REPORTS_GROUP_ID, WEB_APP_URL
from app.keyboards.inline.start import (
    after_goal_confirm_keyboard,
    back_to_group_keyboard,
    club_main_menu,
    day_start_keyboard,
    day_task_next_keyboard,
    day_task_review_keyboard,
    goal_day_step_keyboard,
    goal_edit_days_keyboard,
    goal_review_keyboard,
    next_route_keyboard,
    open_private_flow_keyboard,
    private_hub_reply_keyboard,
    quiz_reply_keyboard,
)
from app.states.quiz import GoalStates, ReportStates, TaskStates

logger = logging.getLogger(__name__)
router = Router()
RETURN_GROUP_URL = GROUP_ENTRY_URL or CLUB_GROUP_URL
KYIV_TZ = ZoneInfo("Europe/Kiev")
QUIZ_INTRO_IMAGE = Path(__file__).resolve().parents[2] / "assets" / "quiz_intro.png"
GOAL_ROUTE_IMAGE = Path(__file__).resolve().parents[2] / "assets" / "goal_30_days_flow.png"


def _club_now() -> datetime:
    return datetime.now(KYIV_TZ)


def _club_day_date(now: datetime | None = None) -> str:
    current = now or _club_now()
    if current.hour >= 22:
        current = current + timedelta(days=1)
    return current.date().isoformat()


def _club_day_deadline_text(now: datetime | None = None) -> str:
    current = now or _club_now()
    if current.hour >= 22:
        return "до 22:00 завтрашнего дня"
    return "до 22:00 сегодняшнего дня"


def _parse_goal_created_at(goal: dict) -> datetime | None:
    try:
        created_raw = str(goal.get("created_at") or "")
        if not created_raw:
            return None
        return datetime.fromisoformat(created_raw.replace("Z", "+00:00")).astimezone(KYIV_TZ)
    except Exception:
        return None


def _goal_is_inside_30_days(goal: dict) -> bool:
    created_at = _parse_goal_created_at(goal)
    if not created_at:
        return True
    return _club_now() < created_at + timedelta(days=30)


async def _next_path_day_number(telegram_id: int, operational_date: str) -> int:
    """Return which 5-day route focus should be used for the next day setup."""
    current_streak = int((await cache.get_data(cache.KeyManager.get_streak_key(telegram_id))) or 0)
    last_report_date = await cache.get_data(cache.KeyManager.get_last_report_date_key(telegram_id))
    if not last_report_date:
        return 1

    try:
        days_after_last_report = (
            date.fromisoformat(operational_date) - date.fromisoformat(str(last_report_date))
        ).days
    except Exception:
        return 1

    if days_after_last_report == 1:
        return 1 if current_streak >= 5 else max(1, min(current_streak + 1, 5))
    if days_after_last_report == 0:
        return max(1, min(current_streak, 5))
    return 1


async def _show_day_closed_message(target: types.Message | types.CallbackQuery) -> None:
    await _answer_private_with_actions(
        target,
        "🔥 <b>День закрыт.</b>\n\n"
        "Отчет за этот day уже сдан, LedoScore зафиксирован.\n"
        "На сегодня все — выдохни, сохрани темп и возвращайся завтра за новым сильным днем 🚀",
    )


async def _show_saved_day_message(
    target: types.Message | types.CallbackQuery,
    tasks_text: str,
    deadline_text: str,
) -> None:
    await _answer_private_with_actions(
        target,
        "📌 <b>Твой day уже зафиксирован:</b>\n\n"
        f"{tasks_text}\n\n"
        f"До {deadline_text.replace('до ', '')} сдай отчет за этот day.\n"
        "За отчет ты получишь LedoScore и поднимешься в рейтинге 👇",
    )


async def _show_day_intro(
    target: types.Message | types.CallbackQuery,
    week_hint: str,
    deadline_text: str,
    path_day_number: int | None = None,
) -> None:
    path_line = f"День пути: <b>{path_day_number}/5</b>\n" if path_day_number else ""
    await _answer_private_with_actions(
        target,
        "Отлично 🔥\n\n"
        "Теперь твоя задача — разложить этот day на конкретные действия.\n\n"
        "Важно:\n"
        f"задачи на этот day действуют {deadline_text}.\n"
        "Именно по ним вечером ты будешь сдавать отчет.\n\n"
        f"{path_line}"
        f"Сегодняшний фокус из твоего 5-дневного маршрута:\n📍 <i>{escape(week_hint)}</i>\n\n"
        "Если готов — жми кнопку ниже 👇",
        inline_markup=day_start_keyboard(),
        single_message=True,
    )


async def _show_task_prompt(
    target: types.Message | types.CallbackQuery,
    task_number: int,
) -> None:
    prompts = {
        1: "Напиши задачу №1 на этот day.\n\nОдна задача = одно конкретное действие, которое можно либо сделать, либо не сделать.",
        2: "Теперь напиши задачу №2.\n\nЕсли одной сильной задачи на day достаточно — потом сможешь нажать «Пропустить».",
        3: "Теперь напиши задачу №3.\n\nЛучший темп и максимальный LedoScore обычно собираются, когда day честно разложен на 3 понятные задачи.",
    }
    await _answer_private_with_actions(
        target,
        prompts.get(task_number, "Напиши следующую задачу 👇"),
    )


async def _show_day_review(target: types.Message | types.CallbackQuery, tasks: list[str]) -> None:
    tasks_text = "\n".join(f"{idx}. {escape(str(task))}" for idx, task in enumerate(tasks, 1))
    await _answer_private_with_actions(
        target,
        "🧠 <b>Проверь задачи на day:</b>\n\n"
        f"{tasks_text}\n\n"
        "Если все ок — подтверждай.\nЕсли хочешь собрать day заново — жми изменить.",
        inline_markup=day_task_review_keyboard(),
        inline_text="Выбери, что делать дальше 👇",
    )


async def _show_goal_day_prompt(
    target: types.Message | types.CallbackQuery,
    state: FSMContext,
    day_number: int,
) -> None:
    data = await state.get_data()
    milestones = data.get("milestones", [])
    is_editing = len(milestones) >= day_number

    await state.update_data(editing_day=day_number)
    await state.set_state(GoalStates.editing_day if is_editing else GoalStates.waiting_day_text)

    prompts = {
        1: "📍 <b>День 1</b>\n\nНапиши главный фокус на первый day.\nЭто не список из 10 дел, а один сильный вектор, который реально запускает движение.",
        2: "📍 <b>День 2</b>\n\nОтлично, первый шаг есть.\nТеперь напиши фокус на второй day — что должно быть сделано, чтобы движение продолжилось?",
        3: "📍 <b>День 3</b>\n\nХорошо идем 🔥\nСейчас нужен главный фокус на третий day.",
        4: "📍 <b>День 4</b>\n\nУже появляется настоящий маршрут, а не просто желание.\nНапиши цель на четвертый day 👇",
        5: "📍 <b>День 5</b>\n\nСупер. Чем яснее маршрут, тем легче реально дойти до результата.\nНапиши фокус на пятый day.",
    }

    await _answer_private_with_actions(
        target,
        prompts.get(day_number, "Напиши фокус дня 👇"),
    )


async def _delete_private_message_safely(message: types.Message) -> None:
    if message.chat.type != "private":
        return
    try:
        await message.delete()
    except Exception as e:
        logger.debug("Failed to delete private message %s: %s", message.message_id, e)


async def _send_quiz_intro(message: types.Message) -> None:
    caption = (
        "🚀 <b>LedoLab Business Club</b>\n\n"
        "Это не чат мотивации и не очередная папка с советами.\n"
        "Это среда, где предприниматели каждый day показывают реальное действие.\n\n"
        "Сначала пройди короткий квиз.\n"
        "Он поможет нам понять твой уровень и точнее провести тебя дальше 👇"
    )
    if QUIZ_INTRO_IMAGE.exists():
        try:
            await message.answer_photo(
                photo=types.FSInputFile(str(QUIZ_INTRO_IMAGE)),
                caption=caption,
                reply_markup=quiz_reply_keyboard(WEB_APP_URL),
            )
            return
        except Exception as exc:
            logger.warning("Failed to send quiz intro image: %s", exc)

    await message.answer(caption, reply_markup=quiz_reply_keyboard(WEB_APP_URL))


async def _send_goal_route_intro(target: types.Message | types.CallbackQuery, goal_text: str) -> None:
    caption = (
        "🎯 <b>Твой маршрут на 5 дней</b>\n\n"
        "Большая цель остается прежней, а теперь мы соберем ближайшие шаги так, чтобы day было легко закрывать.\n\n"
        f"🎯 <i>{escape(goal_text)}</i>\n\n"
        "Нажми кнопку ниже и начнем с первого дня 👇"
    )

    if isinstance(target, types.CallbackQuery):
        sender = target.message
    else:
        sender = target

    if GOAL_ROUTE_IMAGE.exists():
        try:
            await sender.answer_photo(
                photo=types.FSInputFile(str(GOAL_ROUTE_IMAGE)),
                caption=caption,
                reply_markup=goal_day_step_keyboard(1),
            )
            return
        except Exception as exc:
            logger.warning("Failed to send goal route image: %s", exc)

    await sender.answer(caption, reply_markup=goal_day_step_keyboard(1))


async def _answer_private_with_actions(
    target: types.Message | types.CallbackQuery,
    text: str,
    *,
    inline_markup: types.InlineKeyboardMarkup | None = None,
    inline_text: str = "Выбери действие ниже 👇",
    single_message: bool = False,
) -> None:
    if isinstance(target, types.CallbackQuery):
        chat = target.message.chat
        sender = target.message
    else:
        chat = target.chat
        sender = target

    if inline_markup and single_message:
        await sender.answer(text, reply_markup=inline_markup)
        return

    sent = await sender.answer(
        text,
        reply_markup=private_hub_reply_keyboard() if chat.type == "private" else None,
    )
    if inline_markup:
        await sent.answer(inline_text, reply_markup=inline_markup)


def _build_goal_review(goal_text: str, milestones: list[str]) -> str:
    lines = [
        "🧠 Проверь свой маршрут перед подтверждением\n",
        "🎯 <b>Твоя большая цель на 30 дней:</b>",
        escape(goal_text),
        "",
        "📅 <b>Фокус на ближайшие 5 дней:</b>",
    ]
    for idx, milestone in enumerate(milestones, 1):
        lines.append(f"{idx}. {escape(str(milestone))}")
    lines.extend(
        [
            "",
            "Если все выглядит правильно — жми <b>УТВЕРДИТЬ ЦЕЛИ</b> ✅",
            "Если хочешь поправить конкретный day — жми <b>ИЗМЕНИТЬ ЦЕЛИ</b> ✏️",
        ]
    )
    return "\n".join(lines)


async def _show_goal_review(target: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    goal_text = data.get("goal_text", "")
    milestones = data.get("milestones", [])
    review_text = _build_goal_review(goal_text, milestones)

    await _answer_private_with_actions(
        target,
        review_text,
        inline_markup=goal_review_keyboard(),
        inline_text="Проверь все и выбери, что делать дальше 👇",
    )


async def _start_goal_flow(message: types.Message, state: FSMContext) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз, чтобы я понял, на каком ты этапе и как тебя правильно вести дальше.\n\n"
            "После квиза откроются цель на 30 дней, plan на 5 дней и дневные задачи 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        return

    goal_lock = await cache.get_data(cache.KeyManager.get_goal_lock_key(message.from_user.id))
    if goal_lock:
        me = await message.bot.get_me()
        await _answer_private_with_actions(
            message,
            "🔒 <b>Твоя цель на 30 дней уже зафиксирована.</b>\n\n"
            "Это не ошибка, а часть дисциплины клуба.\n"
            "Мы специально не даем менять большую цель каждый day, чтобы ты не сбивал себе фокус.\n\n"
            "Если готов приступить уже сегодня — жми кнопку ниже 👇",
            inline_markup=after_goal_confirm_keyboard(me.username, CLUB_GROUP_URL),
            inline_text="Если хочешь — можете сразу перейти к сборке дня или вернуться в группу 👇",
        )
        return

    await state.clear()
    await state.set_state(GoalStates.waiting_goal_text)
    await _answer_private_with_actions(
        message,
        "🎯 <b>LedoLab Business Club</b>\n\n"
        "Сейчас мы спокойно соберем твой маршрут на ближайшие <b>30 дней</b>.\n\n"
        "Как это работает:\n"
        "1. Ты ставишь <b>1 главную цель</b> на месяц\n"
        "2. Потом разбиваешь ее на <b>5 ближайших дней</b>\n"
        "3. А уже после этого превращаешь каждый day в <b>до 3 конкретных задач</b>\n\n"
        "Не усложняй и не пиши все сразу.\n"
        "Сейчас нужен только один понятный ориентир, к которому ты реально хочешь прийти 🔥\n\n"
        "Напиши свою <b>цель на 30 дней</b> 👇",
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Если хочешь вернуться в группу — вот быстрый переход 👇",
    )


async def _start_day_flow(message: types.Message, state: FSMContext) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Пока что дневной план закрыт.\n\n"
            "Сначала пройди квиз — после него я открою тебе цель, недельный маршрут и кнопку дня 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        return

    user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not user:
        await message.answer("❌ Не удалось подготовить твой профиль. Попробуй еще раз чуть позже.")
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await message.answer(
            "🎯 Сначала зафиксируй большую цель на 30 дней.\n\n"
            "Без нее мы не сможем собрать сильный day, который реально двигает тебя вперед."
        )
        return

    current_streak = int((await cache.get_data(cache.KeyManager.get_streak_key(message.from_user.id))) or 0)
    if current_streak >= 5 and _goal_is_inside_30_days(active_goal):
        await _answer_private_with_actions(
            message,
            "🏆 <b>Предыдущий путь на 5 дней уже закрыт.</b>\n\n"
            "Чтобы не крутиться по старому кругу, сначала собери новый 5-дневный маршрут к своей 30-дневной цели.",
            inline_markup=next_route_keyboard(RETURN_GROUP_URL),
            single_message=True,
        )
        return

    if current_streak >= 5 and not _goal_is_inside_30_days(active_goal):
        await state.clear()
        await state.set_state(GoalStates.waiting_goal_text)
        await _answer_private_with_actions(
            message,
            "🏁 30-дневный цикл уже закрыт.\n\n"
            "Старый маршрут больше не тянем. Напиши новую цель на 30 дней 👇",
            inline_markup=back_to_group_keyboard(RETURN_GROUP_URL) if RETURN_GROUP_URL else None,
            single_message=True,
        )
        return

    today = _club_day_date()
    deadline_text = _club_day_deadline_text()
    today_lock = await cache.get_data(cache.KeyManager.get_day_plan_lock_key(message.from_user.id, today))
    today_tasks = await database.get_today_tasks(user["id"], today)
    existing_report = await database.get_daily_report(user["id"], today)

    if existing_report and str(existing_report.get("status") or "").lower() not in {"redo_requested", "rejected"}:
        await _show_day_closed_message(message)
        return

    if today_tasks or today_lock:
        tasks_text = "\n".join(
            f"{idx}. {escape(str(task.get('task_text', '')))}" for idx, task in enumerate(today_tasks[:3], 1)
        ) or "Пока задачи не найдены в базе, но дневной слот уже зафиксирован."
        await _show_saved_day_message(message, tasks_text, deadline_text)
        return

    milestones = active_goal.get("milestones") or []
    path_day_number = await _next_path_day_number(message.from_user.id, today)
    milestone_index = max(0, min(path_day_number - 1, len(milestones) - 1))
    week_hint = (
        milestones[milestone_index]
        if milestones
        else "выбери 3 действия, которые реально двигают тебя к месячной цели"
    )

    await state.clear()
    await state.set_state(TaskStates.waiting_task_text)
    await state.update_data(
        day_goal_id=active_goal["id"],
        day_tasks=[],
        day_task_step=0,
        day_operational_date=today,
        day_week_hint=week_hint,
        day_path_number=path_day_number,
    )
    await _show_day_intro(message, week_hint, deadline_text, path_day_number)


async def _start_report_flow(message: types.Message, state: FSMContext) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз — после него откроется сдача отчетов 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        return

    user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not user:
        await message.answer("❌ Не удалось подготовить твой профиль. Попробуй еще раз чуть позже.")
        return

    today = _club_day_date()
    existing_report = await database.get_daily_report(user["id"], today)
    if existing_report and str(existing_report.get("status") or "").lower() not in {"redo_requested", "rejected"}:
        await _show_day_closed_message(message)
        return

    today_tasks = await database.get_today_tasks(user["id"], today)
    task_texts = [
        str(task.get("task_text", "")).strip()
        for task in today_tasks
        if str(task.get("task_text", "")).strip()
    ]
    if not task_texts and existing_report:
        task_texts = [
            str(task).strip()
            for task in list(existing_report.get("tasks_snapshot") or [])
            if str(task).strip()
        ]

    if not task_texts:
        me = await message.bot.get_me()
        await _answer_private_with_actions(
            message,
            "📌 <b>Сначала собери day.</b>\n\n"
            "Чтобы сдать отчет, нужны задачи на сегодня.\n"
            "Открой «Мой день» и зафиксируй до 3 задач — потом возвращайся сюда 👇",
            inline_markup=open_private_flow_keyboard(me.username, "day_setup", "ОТКРЫТЬ МОЙ ДЕНЬ"),
            inline_text="Перейти к сборке дня 👇",
        )
        return

    await state.clear()
    await state.set_state(ReportStates.waiting_proof)
    await state.update_data(
        report_user_id=user["id"],
        report_date=today,
        report_tasks=task_texts,
        report_file_id=None,
    )
    await _answer_private_with_actions(
        message,
        report_service.report_intro_text(task_texts),
        single_message=True,
    )


async def _show_referral_invite(message: types.Message) -> None:
    """Генерация и отображение реферального инвайта для пользователя."""
    text, share_url = await referral_service.build_referral_invite(message.bot, message.from_user)
    
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="📢 Поделиться рефералкой", url=share_url)]
        ]
    )
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(
    message: types.Message,
    command: CommandObject | None = None,
    state: FSMContext | None = None,
) -> None:
    """Handle /start in both private chats and groups."""
    user_id = message.from_user.id

    try:
        args = (command.args or "").strip() if command else ""
        if message.chat.type != "private":
            me = await message.bot.get_me()
            await message.answer(
                "👋 Это <b>LedoLab Business Club</b>.\n\n"
                "В группе ты работаешь с меню и отчетами.\n"
                "А личка нужна для настройки цели и спокойной сборки дня.\n\n"
                "Если нужно — открой личку бота кнопкой ниже 👇",
                reply_markup=open_private_flow_keyboard(me.username, "start", "🤖 ОТКРЫТЬ БОТА В ЛИЧКЕ"),
            )
            return

        await _delete_private_message_safely(message)

        if args == "goal_setup" and state:
            await _start_goal_flow(message, state)
            return

        if args == "day_setup" and state:
            await _start_day_flow(message, state)
            return

        if args == "report_setup" and state:
            await _start_report_flow(message, state)
            return

        has_quiz = await database.has_completed_quiz(user_id)
        if has_quiz:
            me = await message.bot.get_me()
            await _answer_private_with_actions(
                message,
                "🔥 <b>Ты уже внутри LedoLab Business Club.</b>\n\n"
                "Если готов продолжать движение — открывай меню и работай по шагам.\n"
                "Если нужен большой маршрут — начни с цели на 30 дней.\n"
                "Если нужен конкретный фокус на сегодня — переходи в день.",
                inline_markup=club_main_menu(me.username, group_url="https://t.me/ledolab"),
                inline_text="Ниже у тебя теперь есть быстрые кнопки-напоминания.\nА если нужен старый inline-вариант меню — он тоже под рукой 👇",
            )
            return

        await _send_quiz_intro(message)
        logger.info(f"New user: {user_id}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.answer("❌ Что-то пошло не так. Попробуй еще раз чуть позже.")


@router.message(F.text == "🎯 Моя цель 30 дней")
async def show_30_day_goal(message: types.Message) -> None:
    """Show the saved 30-day goal as a reminder."""
    await _delete_private_message_safely(message)
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз. После него я смогу показать тебе цель и весь маршрут 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        return

    user = await database.get_club_user(message.from_user.id)
    if not user:
        await message.answer("Сначала пройди стартовый путь в боте, чтобы мы могли сохранить твою цель.")
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await message.answer("Пока цели на 30 дней нет. Нажми `🎯 Моя цель (30 дней)` и мы соберем ее вместе.")
        return

    await _answer_private_with_actions(
        message,
        "🎯 <b>Твоя цель на 30 дней</b>\n\n"
        f"{active_goal.get('goal_text', '')}\n\n"
        "Держи ее перед глазами и не распыляйся. Большой результат всегда начинается с ясного фокуса 🔥",
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Вернуться в группу можно здесь 👇",
    )


@router.message(F.text == "📅 Мой plan на 5 дней")
@router.message(F.text == "📅 Мой план на 5 дней")
async def show_7_day_plan(message: types.Message) -> None:
    """Show the saved weekly plan as a reminder."""
    await _delete_private_message_safely(message)
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз. Потом я покажу тебе и большую цель, и план на 5 дней 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        return

    user = await database.get_club_user(message.from_user.id)
    if not user:
        await message.answer("Сначала пройди стартовый путь в боте, чтобы мы могли сохранить твою траекторию.")
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await message.answer("Пока 5-дневный план не собран. Начни с `🎯 Моя цель (30 дней)`.")
        return

    milestones = active_goal.get("milestones") or []
    if not milestones:
        await message.answer("Пока не вижу сохраненного плана на 5 дней. Давай соберем его заново через цель.")
        return

    lines = ["📅 <b>Твой план на 5 дней</b>\n"]
    for idx, milestone in enumerate(milestones, 1):
        lines.append(f"{idx}. {escape(str(milestone))}")
    lines.extend(
        [
            "",
            "Вот твой ближайший маршрут.\nНе надо помнить все в голове — просто возвращайся сюда и сверяй направление 💡",
        ]
    )
    await _answer_private_with_actions(
        message,
        "\n".join(lines),
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Вернуться в группу можно здесь 👇",
    )


@router.message(F.text == "📌 Мой день (до 3х задач)")
async def show_or_start_day(message: types.Message, state: FSMContext) -> None:
    """Entry point from reply keyboard to today's 3-task flow."""
    await _delete_private_message_safely(message)
    await _start_day_flow(message, state)


@router.message(Command("ref"))
async def show_referral_from_command(message: types.Message) -> None:
    await _delete_private_message_safely(message)
    await _show_referral_invite(message)


@router.message(F.text == "🚀 Рефералка")
async def show_referral_from_reply(message: types.Message) -> None:
    await _delete_private_message_safely(message)
    await _show_referral_invite(message)


@router.callback_query(F.data.startswith("user_report:redo:"))
async def restart_report_after_admin_comment(query: types.CallbackQuery, state: FSMContext) -> None:
    report_id = query.data.split(":", 2)[2]
    report = await database.get_daily_report_by_id(report_id)
    if not report:
        await query.answer("Отчет не найден.", show_alert=True)
        return

    club_user = await database.get_club_user(query.from_user.id)
    if not club_user or club_user.get("id") != report.get("user_id"):
        await query.answer("Это не твой отчет.", show_alert=True)
        return

    task_texts = [str(task).strip() for task in list(report.get("tasks_snapshot") or []) if str(task).strip()]
    if not task_texts:
        payload = report.get("report_payload") or []
        if payload and payload[0].get("task_lines"):
            task_texts = [str(task).strip() for task in payload[0]["task_lines"] if str(task).strip()]

    if not task_texts:
        await query.answer("Не удалось восстановить задачи для отчета.", show_alert=True)
        return

    await state.clear()
    await state.set_state(ReportStates.waiting_proof)
    await state.update_data(
        report_user_id=report["user_id"],
        report_date=str(report["report_date"]),
        report_tasks=task_texts,
        report_file_id=None,
        redo_report_id=report_id,
    )
    await _answer_private_with_actions(
        query,
        report_service.report_intro_text(task_texts),
        single_message=True,
    )
    await query.answer()


@router.callback_query(F.data.startswith("user_report:drop:"))
async def drop_report_redo(query: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.answer("Ок, отчет на сегодня не пересдаем. Завтра начнешь новый day 👇")
    await query.answer()


@router.message(F.video_note, ReportStates.waiting_proof)
async def save_report_video_note(message: types.Message, state: FSMContext) -> None:
    await state.update_data(report_file_id=message.video_note.file_id)
    await state.set_state(ReportStates.reviewing)
    await _answer_private_with_actions(
        message,
        "Кружочек записан ✅\n\nЕсли все ок — подтверждай. Если хочешь переписать, жми заменить.",
        inline_markup=report_service.report_preview_keyboard(),
        inline_text="Выбери, что делать дальше 👇",
    )


@router.message(ReportStates.waiting_proof)
async def reject_non_video_report(message: types.Message) -> None:
    await message.answer(
        "Нужен именно кружочек.\nИ помни: в Telegram кружочек длится до 1 минуты."
    )


@router.callback_query(ReportStates.reviewing, F.data == "report_redo")
async def redo_report_video_note(query: types.CallbackQuery, state: FSMContext) -> None:
    await state.update_data(report_file_id=None)
    await state.set_state(ReportStates.waiting_proof)
    await _answer_private_with_actions(
        query,
        "Запиши один кружочек до 1 минуты, где коротко расскажешь, что сделал по всем задачам 👇",
        inline_markup=back_to_group_keyboard(RETURN_GROUP_URL) if RETURN_GROUP_URL else None,
        single_message=True,
    )
    await query.answer()


@router.callback_query(ReportStates.reviewing, F.data == "report_send")
async def send_daily_report(query: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    report_user_id = data.get("report_user_id")
    report_date = str(data.get("report_date") or _club_day_date())
    task_texts = [str(task) for task in list(data.get("report_tasks") or []) if str(task).strip()]
    report_file_id = data.get("report_file_id")

    if not report_user_id or not task_texts or not report_file_id:
        await query.answer("Не хватает данных для отправки отчета.", show_alert=True)
        return

    club_user = await database.get_club_user(query.from_user.id)
    if not club_user:
        await query.answer("Не удалось найти твой профиль.", show_alert=True)
        return

    entries = [{
        "task_text": "Общий отчет за day",
        "task_lines": task_texts,
        "proof_type": "video_note",
        "file_id": report_file_id,
        "comment_text": "",
    }]
    report = await report_service.save_daily_report(
        user_id=report_user_id,
        telegram_id=query.from_user.id,
        username=club_user.get("username"),
        report_date=report_date,
        entries=entries,
    )
    if not report:
        await query.answer("Не удалось сохранить отчет.", show_alert=True)
        return

    target_group_id = REPORTS_GROUP_ID
    if not target_group_id:
        last_group_chat = await cache.get_data(f"last_group_chat:{query.from_user.id}")
        target_group_id = int(last_group_chat) if last_group_chat else None

    if target_group_id:
        summary_message = await query.bot.send_message(
            chat_id=target_group_id,
            text=report["summary_text"],
            reply_markup=report_service.group_report_vote_keyboard(report["id"]),
        )
        await database.set_daily_report_group_post(report["id"], target_group_id, summary_message.message_id)
        try:
            await query.bot.send_video_note(
                chat_id=target_group_id,
                video_note=report_file_id,
                reply_to_message_id=summary_message.message_id,
            )
        except Exception as exc:
            logger.warning("Failed to send report video note to group | user=%s error=%s", query.from_user.id, exc)

    await referral_service.process_referral_after_report(
        bot=query.bot,
        newbie_user_id=report_user_id,
        newbie_telegram_id=query.from_user.id,
    )

    await state.clear()
    bonus_awarded = int(report.get("bonus_awarded") or 0)
    streak_day = int(report.get("current_streak") or 0)
    weekly_ledoscore = int(report.get("weekly_ledoscore") or 0)
    route_completed = streak_day > 0 and streak_day % 5 == 0
    active_goal = await database.get_active_goal(report_user_id) if route_completed else None
    bonus_line = (
        f"+{bonus_awarded} LedoBonus за day {streak_day} из 5.\n"
        if bonus_awarded > 0 and streak_day > 0
        else ""
    )
    closing_line = ""
    result_markup = back_to_group_keyboard(RETURN_GROUP_URL) if RETURN_GROUP_URL else None
    if route_completed and active_goal and _goal_is_inside_30_days(active_goal):
        closing_line = (
            "\n\n🏆 Ты закрыл путь на 5 дней.\n"
            "Большая 30-дневная цель остается. Давай соберем следующий маршрут?"
        )
        result_markup = next_route_keyboard(RETURN_GROUP_URL)
    elif route_completed:
        closing_line = (
            "\n\n🏁 Путь на 5 дней закрыт.\n"
            "Если 30-дневный цикл уже закончился — дальше ставим новую большую цель."
        )
    route_day_number = ((streak_day - 1) % 5) + 1 if streak_day > 0 else 1
    await _answer_private_with_actions(
        query,
        "🔥 Отчет отправлен.\n\n"
        "+30 LedoScore за отчет.\n"
        f"{bonus_line}"
        f"День пути: {route_day_number}/5.\n"
        f"LedoScore за неделю: {weekly_ledoscore}."
        f"{closing_line}",
        inline_markup=result_markup,
        single_message=True,
    )
    await query.answer("Отчет отправлен ✅")


@router.callback_query(F.data == "goal_route_refresh")
async def start_next_route_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await database.has_completed_quiz(query.from_user.id):
        await query.answer("Сначала пройди квиз.", show_alert=True)
        return

    user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not user:
        await query.answer("Не удалось подготовить профиль.", show_alert=True)
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await state.clear()
        await state.set_state(GoalStates.waiting_goal_text)
        await _answer_private_with_actions(
            query,
            "🎯 Активной 30-дневной цели уже нет.\n\n"
            "Значит, начинаем новый цикл. Напиши новую цель на 30 дней 👇",
            inline_markup=back_to_group_keyboard(RETURN_GROUP_URL) if RETURN_GROUP_URL else None,
            single_message=True,
        )
        await query.answer()
        return

    if not _goal_is_inside_30_days(active_goal):
        await state.clear()
        await state.set_state(GoalStates.waiting_goal_text)
        await _answer_private_with_actions(
            query,
            "🏁 30-дневный цикл уже подошел к финалу.\n\n"
            "Не растягиваем старое. Напиши новую большую цель на следующие 30 дней 👇",
            inline_markup=back_to_group_keyboard(RETURN_GROUP_URL) if RETURN_GROUP_URL else None,
            single_message=True,
        )
        await query.answer()
        return

    goal_text = str(active_goal.get("goal_text") or "").strip()
    await state.clear()
    await state.set_state(GoalStates.waiting_day_text)
    await state.update_data(
        goal_text=goal_text,
        milestones=[],
        editing_day=None,
        refresh_route=True,
    )
    await _send_goal_route_intro(query, goal_text)
    await query.answer("Собираем новый маршрут 🚀")


@router.callback_query(TaskStates.waiting_task_text, F.data == "day_go")
async def start_day_task_collection(query: types.CallbackQuery, state: FSMContext) -> None:
    await state.update_data(day_task_step=1, day_tasks=[])
    await state.set_state(TaskStates.collecting_day_tasks)
    await _show_task_prompt(query, 1)
    await query.answer()


@router.callback_query(TaskStates.waiting_task_text, F.data == "day_tomorrow")
async def postpone_day_to_tomorrow(query: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _answer_private_with_actions(
        query,
        "Хорошо.\n\n"
        "Сегодня не насилуем себя фальшивой продуктивностью.\n"
        "Отдохни, а завтра вернись и собери новый day с ясной головой ✨",
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Вернуться в группу можно здесь 👇",
    )
    await query.answer()


@router.message(TaskStates.collecting_day_tasks)
async def collect_day_task_text(message: types.Message, state: FSMContext) -> None:
    task_text = (message.text or "").strip()
    if len(task_text) < 3:
        await message.answer("🤏 Напиши задачу чуть конкретнее, чтобы вечером было честно понятно: сделал или нет.")
        return

    data = await state.get_data()
    current_step = int(data.get("day_task_step") or 1)
    tasks = list(data.get("day_tasks") or [])

    while len(tasks) < current_step - 1:
        tasks.append("")
    if len(tasks) >= current_step:
        tasks[current_step - 1] = task_text
    else:
        tasks.append(task_text)

    await state.update_data(day_tasks=tasks)

    if current_step >= 3:
        await state.set_state(TaskStates.reviewing_day_tasks)
        await _show_day_review(message, tasks)
        return

    await _answer_private_with_actions(
        message,
        "⚠️ <b>Важно:</b>\n\n"
        "Здесь решает не количество задач, а дисциплина.\n"
        "📅 Каждый day у тебя есть до 3 задач — это твой фокус\n"
        "🎯 Но баллы ты получаешь не за задачи, а за отчёт\n\n"
        "📤 Сдал отчёт → получил баллы\n"
        "🚫 Не сдал → day не засчитан\n\n"
        "❌ Не выдумывай задачи ради галочки\n"
        "✔️ Делай реальные вещи и честно отчитывайся\n\n"
        "📈 Важно только одно: ты идёшь к своей цели или нет\n\n"
        f"Теперь задача №{current_step + 1}",
        inline_markup=day_task_next_keyboard(current_step + 1),
    )


@router.callback_query(TaskStates.collecting_day_tasks, F.data.startswith("day_task_next:"))
async def open_next_day_task(query: types.CallbackQuery, state: FSMContext) -> None:
    next_task_number = int(query.data.split(":")[1])
    await state.update_data(day_task_step=next_task_number)
    await _show_task_prompt(query, next_task_number)
    await query.answer()


@router.callback_query(TaskStates.collecting_day_tasks, F.data == "day_task_skip")
async def skip_remaining_day_tasks(query: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tasks = [task for task in list(data.get("day_tasks") or []) if task]
    await state.set_state(TaskStates.reviewing_day_tasks)
    await _show_day_review(query, tasks)
    await query.answer()


@router.callback_query(TaskStates.reviewing_day_tasks, F.data == "day_tasks_edit")
async def restart_day_task_collection(query: types.CallbackQuery, state: FSMContext) -> None:
    await state.update_data(day_tasks=[], day_task_step=1)
    await state.set_state(TaskStates.collecting_day_tasks)
    await _show_task_prompt(query, 1)
    await query.answer()


@router.callback_query(TaskStates.reviewing_day_tasks, F.data == "day_tasks_confirm")
async def confirm_day_tasks(query: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tasks = [task for task in list(data.get("day_tasks") or []) if task]
    if not tasks:
        await query.answer("Сначала собери хотя бы одну задачу.", show_alert=True)
        return

    club_user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not club_user:
        await query.answer("Не удалось подготовить профиль участника.", show_alert=True)
        return

    operational_date = str(data.get("day_operational_date") or _club_day_date())
    goal_id = data.get("day_goal_id")
    for idx, task_text in enumerate(tasks, 1):
        await database.create_task(
            club_user["id"],
            task_text,
            operational_date,
            task_type=f"day_{idx}",
            goal_id=goal_id,
        )

    await cache.set_data(
        cache.KeyManager.get_day_plan_lock_key(query.from_user.id, operational_date),
        "1",
        ex=cache.seconds_until_next_22(),
    )

    await state.clear()
    await _show_saved_day_message(
        query,
        "\n".join(f"{idx}. {escape(str(task))}" for idx, task in enumerate(tasks, 1)),
        _club_day_deadline_text(),
    )
    await query.answer("Задачи на day зафиксированы ✅")


@router.callback_query(TaskStates.waiting_task_text, F.data == "flow_back")
@router.callback_query(TaskStates.collecting_day_tasks, F.data == "flow_back")
@router.callback_query(TaskStates.reviewing_day_tasks, F.data == "flow_back")
async def handle_day_flow_back(query: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    current_state = await state.get_state()
    tasks = list(data.get("day_tasks") or [])
    week_hint = str(data.get("day_week_hint") or "собери сильный day без перегруза")
    path_day_number = int(data.get("day_path_number") or 1)

    if current_state == TaskStates.waiting_task_text.state:
        await _show_day_intro(query, week_hint, _club_day_deadline_text(), path_day_number)
        await query.answer("↩️ Шаг назад")
        return

    if current_state == GoalStates.waiting_day_text.state:
        data = await state.get_data()
        milestones = list(data.get("milestones") or [])
        if not milestones:
            await _show_day_intro(query, week_hint, _club_day_deadline_text(), path_day_number)
        else:
            await _show_goal_day_prompt(query, state, len(milestones))
        await query.answer("↩️ Шаг назад")
        return

    if current_state == TaskStates.collecting_day_tasks.state:
        if tasks:
            tasks.pop()
        next_step = max(len(tasks) + 1, 1)
        await state.update_data(day_tasks=tasks, day_task_step=next_step)
        await _show_task_prompt(query, next_step)
        await query.answer("↩️ Шаг назад")
        return

    if current_state == TaskStates.reviewing_day_tasks.state:
        if tasks:
            tasks.pop()
        next_step = max(len(tasks) + 1, 1)
        await state.update_data(day_tasks=tasks, day_task_step=next_step)
        await state.set_state(TaskStates.collecting_day_tasks)
        await _show_task_prompt(query, next_step)
        await query.answer("↩️ Шаг назад")
        return

    await query.answer("↩️ Шаг назад")


@router.message(GoalStates.waiting_goal_text)
async def handle_goal_text(message: types.Message, state: FSMContext) -> None:
    """Save the main 30-day goal in FSM only until user confirms it."""
    goal_text = (message.text or "").strip()
    if len(goal_text) < 5:
        await message.answer("🤏 Напиши цель чуть конкретнее, чтобы было понятно, к чему ты идешь.")
        return

    await state.update_data(goal_text=goal_text, milestones=[], editing_day=None)
    await state.set_state(GoalStates.waiting_day_text)
    await _answer_private_with_actions(
        message,
        "🔥 <b>Отлично. Большую цель зафиксировали.</b>\n\n"
        "Теперь не пытаемся расписать весь месяц сразу.\n"
        "Сейчас собираем <b>5 ближайших дней</b> — это не мелкие таски, а понятные дневные фокусы.\n\n"
        "Нажми кнопку ниже, и мы спокойно начнем с первого дня 👇",
        inline_markup=goal_day_step_keyboard(1),
    )


@router.callback_query(GoalStates.waiting_day_text, F.data.startswith("goal_day:"))
@router.callback_query(GoalStates.reviewing, F.data.startswith("goal_day:"))
async def open_goal_day_step(query: types.CallbackQuery, state: FSMContext) -> None:
    """Open a specific 5-day milestone step."""
    day_number = int(query.data.split(":")[1])
    await _show_goal_day_prompt(query, state, day_number)
    await query.answer("↩️ Шаг назад")


@router.message(GoalStates.waiting_day_text)
@router.message(GoalStates.editing_day)
async def save_goal_day_text(message: types.Message, state: FSMContext) -> None:
    """Save or edit one of the five day focuses."""
    day_text = (message.text or "").strip()
    if len(day_text) < 3:
        await message.answer("🤏 Напиши чуть подробнее, чтобы фокус дня был понятным и конкретным.")
        return

    data = await state.get_data()
    day_number = int(data.get("editing_day") or 1)
    milestones = list(data.get("milestones", []))

    while len(milestones) < day_number:
        milestones.append("")
    milestones[day_number - 1] = day_text

    await state.update_data(milestones=milestones)

    if day_number < 5 and all(milestones[:day_number]):
        await state.update_data(editing_day=None)
        await state.set_state(GoalStates.waiting_day_text)
        await _answer_private_with_actions(
            message,
            f"✅ <b>{day_number}-й day сохранен.</b>\n\n"
            "Идем дальше спокойно, шаг за шагом 👇",
            inline_markup=goal_day_step_keyboard(day_number + 1),
        )
        return

    if all(milestones[:5]) and len(milestones) >= 5:
        await state.update_data(editing_day=None)
        await state.set_state(GoalStates.reviewing)
        await _show_goal_review(message, state)
        return

    next_missing = next((idx for idx, value in enumerate(milestones, 1) if not value), day_number + 1)
    await state.update_data(editing_day=None)
    await state.set_state(GoalStates.waiting_day_text)
    await _answer_private_with_actions(
        message,
        "✅ День сохранен. Продолжаем 👇",
        inline_markup=goal_day_step_keyboard(next_missing),
    )


@router.callback_query(GoalStates.reviewing, F.data == "goal_edit")
async def edit_goal_days(query: types.CallbackQuery, state: FSMContext) -> None:
    """Open selective editing for one of the 5 days."""
    await _answer_private_with_actions(
        query,
        "✏️ Выбери day, который хочешь поправить.\n\n"
        "Тебе не нужно переписывать все заново — можно изменить только то, что реально хочется улучшить 👇",
        inline_markup=goal_edit_days_keyboard(),
    )
    await query.answer()


@router.callback_query(GoalStates.reviewing, F.data == "goal_confirm")
async def confirm_goal_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    """Persist the goal and post the plan to the group after final confirmation."""
    data = await state.get_data()
    goal_text = data.get("goal_text", "").strip()
    milestones = [item.strip() for item in data.get("milestones", []) if item.strip()]
    refresh_route = bool(data.get("refresh_route"))
    if not goal_text or len(milestones) < 5:
        await query.answer("Не хватает данных для сохранения.", show_alert=True)
        return

    user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not user:
        await query.answer("Не удалось сохранить цель.", show_alert=True)
        return

    if refresh_route:
        saved_goal = await database.update_active_goal_milestones(user["id"], milestones)
        if not saved_goal:
            await query.answer("Не удалось обновить маршрут в базе.", show_alert=True)
            return

        for day_number, milestone in enumerate(milestones, 1):
            await cache.set_data(
                cache.KeyManager.get_goal_day_lock_key(query.from_user.id, day_number),
                milestone,
                ex=cache.seconds_until_next_sunday_21(),
            )
        await cache.set_data(
            cache.KeyManager.get_streak_key(query.from_user.id),
            "0",
            ex=30 * 24 * 60 * 60,
        )

        if REPORTS_GROUP_ID:
            user_label = mention_service.build_user_mention(
                telegram_id=query.from_user.id,
                username=user.get("username"),
                first_name=user.get("first_name") or query.from_user.first_name,
                fallback="Участник",
            )
            group_text_lines = [
                "🚀 <b>Новый 5-дневный маршрут собран</b>\n",
                f"{user_label} продолжает движение к своей 30-дневной цели.",
                "",
                "🎯 <b>Цель:</b>",
                escape(goal_text),
                "",
                "📅 <b>Новый маршрут на 5 дней:</b>",
            ]
            for idx, milestone in enumerate(milestones, 1):
                group_text_lines.append(f"{idx}. {escape(milestone)}")
            group_text_lines.append("\nСледующий круг начинается. Поддержите темп 🔥")
            try:
                await query.bot.send_message(REPORTS_GROUP_ID, "\n".join(group_text_lines))
            except Exception as exc:
                logger.error("Failed to post refreshed route to group: %s", exc, exc_info=True)

        me = await query.bot.get_me()
        await _answer_private_with_actions(
            query,
            "✅ <b>Новый 5-дневный маршрут зафиксирован.</b>\n\n"
            "30-дневная цель остается прежней, но ближайшие 5 дней теперь свежие и понятные.\n\n"
            "Когда будешь готов собрать сегодняшний day — жми кнопку ниже.",
            inline_markup=after_goal_confirm_keyboard(me.username, RETURN_GROUP_URL),
            single_message=True,
        )
        await state.clear()
        await query.answer("Маршрут обновлен ✅")
        return

    saved_goal = await database.set_active_goal(user["id"], goal_text, milestones)
    if not saved_goal:
        await query.answer("Не удалось сохранить цель в базе.", show_alert=True)
        return

    await cache.set_data(cache.KeyManager.get_goal_lock_key(query.from_user.id), goal_text, ex=30 * 24 * 60 * 60)
    for day_number, milestone in enumerate(milestones, 1):
        await cache.set_data(
            cache.KeyManager.get_goal_day_lock_key(query.from_user.id, day_number),
            milestone,
            ex=5 * 24 * 60 * 60,
        )

    if REPORTS_GROUP_ID:
        user_label = mention_service.build_user_mention(
            telegram_id=query.from_user.id,
            username=user.get("username"),
            first_name=user.get("first_name") or query.from_user.first_name,
            fallback="Участник",
        )
        group_text_lines = [
            "🔥 <b>Новый предприниматель зашел в игру всерьез</b>\n",
            f"{user_label} только что собрал свой маршрут в <b>LedoLab Business Club</b>.",
            "",
            "🎯 <b>Цель на 30 дней:</b>",
            escape(goal_text),
            "",
            "📅 <b>Фокус на ближайшие 5 дней:</b>",
        ]
        for idx, milestone in enumerate(milestones, 1):
            group_text_lines.append(f"{idx}. {escape(milestone)}")
        group_text_lines.extend(
            [
                "",
                "Вот это уже не просто «хочу».\nВот это — маршрут к результату 💪",
                "",
                "Поддержите его огнем в комментариях и реакциях 🔥",
            ]
        )
        try:
            await query.bot.send_message(REPORTS_GROUP_ID, "\n".join(group_text_lines))
        except Exception as exc:
            logger.error("Failed to post goal to group: %s", exc, exc_info=True)

    me = await query.bot.get_me()
    await _answer_private_with_actions(
        query,
        "🚀 <b>Готово. Твоя большая цель и 5-дневный маршрут зафиксированы.</b>\n\n"
        "Now у тебя есть не просто желание, а понятный план движения.\n\n"
        "Если готов уже <b>сегодня</b> начать выполнять поставленные цели — нажимай кнопку\n"
        "<b>📅 Мой day (до 3х задач)</b>.\n\n"
        "Если пока не готов — просто вернись в группу и продолжишь позже.",
        inline_markup=after_goal_confirm_keyboard(me.username, CLUB_GROUP_URL),
    )
    await state.clear()
    await query.answer("Цели подтверждены ✅")
