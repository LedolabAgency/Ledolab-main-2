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
from app.config import CLUB_GROUP_URL, CLUB_MENU_URL, GROUP_ENTRY_URL, REPORTS_GROUP_ID, WEB_APP_URL
from app.keyboards.inline.start import (
    after_goal_confirm_keyboard,
    back_to_group_keyboard,
    club_main_menu,
    day_start_keyboard,
    day_task_next_keyboard,
    day_task_review_keyboard,
    goal_day_back_keyboard,
    goal_day_step_keyboard,
    goal_edit_days_keyboard,
    goal_intro_keyboard,
    goal_review_keyboard,
    goal_split_keyboard,
    goal_text_confirm_keyboard,
    next_route_keyboard,
    open_private_flow_keyboard,
    quiz_reply_keyboard,
    return_to_group_keyboard,
)
from app.states.quiz import GoalStates, ReportStates, TaskStates

logger = logging.getLogger(__name__)
router = Router()
RETURN_GROUP_URL = GROUP_ENTRY_URL or CLUB_GROUP_URL
KYIV_TZ = ZoneInfo("Europe/Kiev")
QUIZ_INTRO_IMAGE = Path(__file__).resolve().parents[2] / "assets" / "quiz_intro.png"
GOAL_ROUTE_IMAGE = Path(__file__).resolve().parents[2] / "assets" / "goal_30_days_flow.png"
REFERRAL_CARD_PHOTO_ID = "AgACAgIAAxkBAAIKdWowbaW6cU3zHGChGVTZ4Bp8Y0CZAAKUHmsbhDCBSYZ-9klgXBR2AQADAgADeAADPAQ"


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
        "Отчет за этот день уже сдан, LedoScore зафиксирован.\n"
        "На сегодня всё — выдохни, сохрани темп и возвращайся завтра за новым сильным днём 🚀",
        inline_markup=return_to_group_keyboard(RETURN_GROUP_URL),
        single_message=True,
    )


async def _show_saved_day_message(
    target: types.Message | types.CallbackQuery,
    tasks_text: str,
    deadline_text: str,
) -> None:
    await _answer_private_with_actions(
        target,
        "📌 <b>Твой день уже зафиксирован:</b>\n\n"
        f"{tasks_text}\n\n"
        f"До {deadline_text.replace('до ', '')} сдай отчет за этот день.\n"
        "Кнопка <b>Сдать Отчет</b> находится в группе в закреплённом сообщении.\n\n"
        "За отчет ты получишь LedoScore и поднимешься в рейтинге 💪",
        inline_markup=return_to_group_keyboard(RETURN_GROUP_URL),
        single_message=True,
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
        "Теперь твоя задача — разложить этот день на конкретные действия.\n\n"
        "Важно:\n"
        f"задачи на этот день действуют {deadline_text}.\n"
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
        1: "Напиши задачу №1 на этот день.\n\nОдна задача = одно конкретное действие, которое можно либо сделать, либо не сделать.",
        2: "Теперь напиши задачу №2.\n\nЕсли одной сильной задачи на день достаточно — потом сможешь нажать «Пропустить».",
        3: "Теперь напиши задачу №3.\n\nЛучший темп и максимальный LedoScore обычно собираются, когда день честно разложен на 3 понятные задачи.",
    }
    await _answer_private_with_actions(
        target,
        prompts.get(task_number, "Напиши следующую задачу 👇"),
    )


async def _show_day_review(target: types.Message | types.CallbackQuery, tasks: list[str]) -> None:
    tasks_text = "\n".join(f"{idx}. {escape(str(task))}" for idx, task in enumerate(tasks, 1))
    await _answer_private_with_actions(
        target,
        "🧠 <b>Проверь задачи на сегодня:</b>\n\n"
        f"{tasks_text}\n\n"
        "Если всё ок — подтверждай.\nЕсли хочешь собрать день заново — жми изменить.",
        inline_markup=day_task_review_keyboard(),
        inline_text="Выбери, что делать дальше 👇",
        single_message=True,
    )


async def _show_goal_day_prompt(
    target: types.Message | types.CallbackQuery,
    state: FSMContext,
    day_number: int,
    prefix: str = "",
) -> None:
    data = await state.get_data()
    milestones = data.get("milestones", [])
    is_editing = len(milestones) >= day_number

    await state.update_data(editing_day=day_number)
    await state.set_state(GoalStates.editing_day if is_editing else GoalStates.waiting_day_text)

    prompts = {
        1: "📍 <b>День 1</b>\n\nНапиши главный фокус на первый день.\nЭто не список из 10 дел, а один сильный вектор, который реально запускает движение.",
        2: "📍 <b>День 2</b>\n\nОтлично, первый шаг есть.\nТеперь напиши фокус на второй день — что должно быть сделано, чтобы движение продолжилось?",
        3: "📍 <b>День 3</b>\n\nХорошо идём 🔥\nСейчас нужен главный фокус на третий день.",
        4: "📍 <b>День 4</b>\n\nУже появляется настоящий маршрут, а не просто желание.\nНапиши цель на четвёртый день 👇",
        5: "📍 <b>День 5</b>\n\nСупер. Чем яснее маршрут, тем легче реально дойти до результата.\nНапиши фокус на пятый день.",
    }

    await _answer_private_with_actions(
        target,
        prefix + prompts.get(day_number, "Напиши фокус дня 👇"),
        inline_markup=goal_day_back_keyboard(day_number),
        single_message=True,
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
        "Это среда, где предприниматели каждый день показывают реальное действие.\n\n"
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
        "Большая цель остается прежней, а теперь мы соберём ближайшие шаги так, чтобы каждый день было легко закрывать.\n\n"
        f"🎯 <i>{escape(goal_text)}</i>\n\n"
        "Нажми кнопку ниже и начнем с первого дня 👇"
    )

    if isinstance(target, types.CallbackQuery):
        sender = target.message
    else:
        sender = target

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

    sent = await sender.answer(text)
    if inline_markup:
        await sent.answer(inline_text, reply_markup=inline_markup)


def _build_goal_preview(goal_text: str) -> str:
    """Beautiful single-goal preview shown before user confirms the 30-day goal."""
    return (
        "🎯 <b>Твоя цель на 30 дней:</b>\n\n"
        f"<blockquote>{escape(goal_text)}</blockquote>\n\n"
        "Это то, к чему ты придёшь через месяц.\n"
        "Не список дел, не размытое желание — конкретный результат.\n\n"
        "Всё верно? Подтверди, и мы начнём строить маршрут 👇"
    )


def _build_5day_review(goal_text: str, milestones: list[str]) -> str:
    """Beautiful 5-day plan preview shown before user confirms milestones."""
    day_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = [
        "🗓 <b>Твой маршрут на 5 дней:</b>\n",
    ]
    for idx, milestone in enumerate(milestones, 1):
        emoji = day_emojis[idx - 1] if idx <= 5 else f"{idx}."
        lines.append(f"{emoji} {escape(str(milestone))}")
    lines.extend([
        "",
        f"<i>Цель: {escape(goal_text)}</i>\n",
        "Выглядит сильно? Если всё ок — подтверждай.\n"
        "Хочешь поправить — жми Изменить 👇",
    ])
    return "\n".join(lines)


def _build_goal_review(goal_text: str, milestones: list[str]) -> str:
    return _build_5day_review(goal_text, milestones)


async def _show_goal_review(target: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    goal_text = data.get("goal_text", "")
    milestones = data.get("milestones", [])
    review_text = _build_goal_review(goal_text, milestones)

    await _answer_private_with_actions(
        target,
        review_text,
        inline_markup=goal_review_keyboard(),
        single_message=True,
    )


async def _schedule_goal_thinking_reminder(bot: types.Bot, user_id: int, delay_seconds: int = 7200) -> None:
    """Send a gentle reminder after thinking time expires."""
    import asyncio
    async def _worker() -> None:
        try:
            await asyncio.sleep(delay_seconds)
            # Only send if user still hasn't started goal (thinking key expired = no reminder needed)
            thinking_key = cache.KeyManager.get_goal_thinking_key(user_id)
            still_thinking = await cache.get_data(thinking_key)
            if not still_thinking:
                return
            goal_lock = await cache.get_data(cache.KeyManager.get_goal_lock_key(user_id))
            if goal_lock:
                return
            await bot.send_message(
                user_id,
                "💭 Придумал цель?\n\n"
                "Возвращайся — готов записать её прямо сейчас.\n"
                "Зайди в группу и нажми 🎯 <b>Моя цель (30 дней)</b> 👇",
                parse_mode="HTML",
                reply_markup=return_to_group_keyboard(RETURN_GROUP_URL),
            )
        except Exception as e:
            logger.debug("Goal thinking reminder failed for %s: %s", user_id, e)

    import asyncio as _asyncio
    _asyncio.create_task(_worker(), name=f"goal_reminder:{user_id}")


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
        club_user = await database.ensure_club_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            language_code=message.from_user.language_code or "ru",
        )
        active_goal = await database.get_active_goal(club_user["id"]) if club_user else None

        if not active_goal:
            # Stale Redis lock — DB was reset but key survived. Clear and let user set goal.
            await cache.delete_data(cache.KeyManager.get_goal_lock_key(message.from_user.id))
        else:
            goal_text_display = str(active_goal.get("goal_text") or "").strip()
            locked_text = "🔒 <b>Твоя цель на 30 дней уже зафиксирована.</b>\n\n"
            if goal_text_display:
                locked_text += f"<blockquote>{escape(goal_text_display)}</blockquote>\n\n"
            locked_text += "Цель нельзя менять — это часть дисциплины клуба. Держи фокус и двигайся вперёд 👇"
            await message.answer(
                locked_text,
                reply_markup=return_to_group_keyboard(RETURN_GROUP_URL),
                parse_mode="HTML",
            )
            return

    # Thinking time: show intro + set 2h Redis key + schedule reminder
    # If user already has the key (came back within 2h) — they already saw the intro, proceed to FSM
    thinking_key = cache.KeyManager.get_goal_thinking_key(message.from_user.id)
    already_thinking = await cache.get_data(thinking_key)

    if not already_thinking:
        # First time opening — show intro, give time to think
        await cache.set_data(thinking_key, "1", ex=2 * 60 * 60)  # 2 hours
        await _schedule_goal_thinking_reminder(message.bot, message.from_user.id)
        await message.answer(
            "🎯 <b>Цель на 30 дней — твой главный ориентир в клубе.</b>\n\n"
            "Это не просто текст в боте. Это то, к чему ты будешь двигаться каждый день "
            "через конкретные задачи, отчёты и рост в рейтинге.\n\n"
            "Как работает система:\n"
            "1️⃣ Ты ставишь <b>1 главную цель</b> на 30 дней\n"
            "2️⃣ Разбиваешь её на <b>5-дневные маршруты</b>\n"
            "3️⃣ Каждый день — <b>до 3 конкретных задач</b> + вечерний отчёт\n\n"
            "Не спеши. Подумай — какой результат через 30 дней изменит твою реальность?\n\n"
            "Когда готов — жми <b>Поставить цель</b> 👇",
            reply_markup=goal_intro_keyboard(RETURN_GROUP_URL),
            parse_mode="HTML",
        )
        return

    # User came back (within 2h window) — enter goal FSM directly
    await _enter_goal_text_state(message, state)


async def _enter_goal_text_state(message: types.Message, state: FSMContext) -> None:
    """Start the actual goal-writing FSM after thinking time."""
    await state.clear()
    await state.set_state(GoalStates.waiting_goal_text)
    await message.answer(
        "💪 Отлично — начнём.\n\n"
        "Напиши свою <b>главную цель на 30 дней</b>.\n\n"
        "Одно чёткое предложение. Конкретный результат, который ты хочешь получить через месяц.\n\n"
        "Эта цель потом разобьётся на 5-дневные маршруты — "
        "но сначала зафиксируем главный ориентир 👇",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "goal_start_now")
async def handle_goal_start_now(query: types.CallbackQuery, state: FSMContext) -> None:
    """User clicked 'Поставить цель' from the thinking-time intro screen."""
    try:
        await query.answer()
        await _enter_goal_text_state(query.message, state)
    except Exception as e:
        logger.error("Error in goal_start_now: %s", e, exc_info=True)
        await query.answer("Ошибка. Попробуй ещё раз.")


@router.callback_query(F.data == "goal_text_postpone")
async def handle_goal_text_postpone(query: types.CallbackQuery, state: FSMContext) -> None:
    """User postponed goal confirmation — clear FSM, encourage to return."""
    try:
        await state.clear()
        await query.answer()
        await query.message.answer(
            "⏳ Хорошо — не торопись.\n\n"
            "Сильная цель требует ясности. Подумай ещё раз и возвращайся, "
            "когда будешь готов зафиксировать её.\n\n"
            "Мы тебя ждём 💪",
            reply_markup=return_to_group_keyboard(RETURN_GROUP_URL),
        )
    except Exception as e:
        logger.error("Error in goal_text_postpone: %s", e, exc_info=True)
        await query.answer("Ошибка. Попробуй ещё раз.")


async def _route_already_set(user_id: int) -> bool:
    """True if the user already has a confirmed 5-day route saved in DB."""
    club_user = await database.get_club_user(user_id)
    if not club_user:
        return False
    active_goal = await database.get_active_goal(club_user["id"])
    if not active_goal:
        return False
    milestones = [m for m in (active_goal.get("milestones") or []) if m]
    return len(milestones) >= 5


@router.callback_query(F.data == "goal_split_days")
async def handle_goal_split_days(query: types.CallbackQuery, state: FSMContext) -> None:
    """User chose to split the 30-day goal into 5-day milestones right now."""
    try:
        # Guard: route already confirmed — this is a stale button, don't restart the flow.
        if await _route_already_set(query.from_user.id):
            await query.answer("✅ Маршрут на 5 дней уже собран. Цели менять нельзя.", show_alert=True)
            return
        await query.answer()
        data = await state.get_data()
        goal_text = data.get("goal_text", "")
        await state.set_state(GoalStates.waiting_day_text)
        await state.update_data(milestones=[], editing_day=None)
        await _send_goal_route_intro(query, goal_text)
    except Exception as e:
        logger.error("Error in goal_split_days: %s", e, exc_info=True)
        await query.answer("Ошибка. Попробуй ещё раз.")


@router.callback_query(F.data == "goal_split_later")
async def handle_goal_split_later(query: types.CallbackQuery, state: FSMContext) -> None:
    """User chose to split into 5 days later."""
    try:
        await state.clear()
        await query.answer()
        await query.message.answer(
            "👍 Окей — цель зафиксирована.\n\n"
            "Когда будешь готов разбить её на 5-дневные маршруты — "
            "возвращайся в группу и нажми <b>📅 Моя цель на 5 дней</b>.",
            reply_markup=return_to_group_keyboard(RETURN_GROUP_URL),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Error in goal_split_later: %s", e, exc_info=True)
        await query.answer("Ошибка. Попробуй ещё раз.")


async def _start_route_flow(message: types.Message, state: FSMContext) -> None:
    """Handle deep link ?start=route_setup — 'Моя цель на 5 дней' button from group."""
    user_id = message.from_user.id

    if not await database.has_completed_quiz(user_id):
        await message.answer(
            "🧭 Сначала пройди квиз — после него откроются цель на 30 дней и 5-дневный маршрут 👇",
            reply_markup=quiz_reply_keyboard(WEB_APP_URL),
        )
        return

    user = await database.ensure_club_user(
        telegram_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not user:
        await message.answer("❌ Не удалось подготовить твой профиль. Попробуй ещё раз чуть позже.")
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await message.answer(
            "🎯 <b>Сначала поставь большую цель на 30 дней.</b>\n\n"
            "5-дневный маршрут строится поверх неё — без цели строить некуда.\n\n"
            "Вернись в группу и нажми <b>🎯 Моя цель (30 дней)</b> 👇",
            reply_markup=return_to_group_keyboard(RETURN_GROUP_URL),
            parse_mode="HTML",
        )
        return

    goal_text = str(active_goal.get("goal_text") or "").strip()
    milestones = [m for m in (active_goal.get("milestones") or []) if m]

    # No milestones yet — user confirmed goal but hasn't built the 5-day route
    if not milestones:
        await state.clear()
        await state.set_state(GoalStates.waiting_day_text)
        await state.update_data(goal_text=goal_text, milestones=[], editing_day=None)
        await _send_goal_route_intro(message, goal_text)
        return

    # Milestones exist — check if current 5-day route is done (streak >= 5)
    current_streak = int((await cache.get_data(cache.KeyManager.get_streak_key(user_id))) or 0)

    if current_streak >= 5 and _goal_is_inside_30_days(active_goal):
        # Route completed — offer to build a new one
        await _answer_private_with_actions(
            message,
            "🏆 <b>Предыдущий 5-дневный маршрут закрыт — отлично!</b>\n\n"
            "30-дневная цель остается в силе. Давай соберем следующий маршрут на 5 дней?\n\n"
            f"🎯 <i>{escape(goal_text)}</i>",
            inline_markup=next_route_keyboard(RETURN_GROUP_URL),
            single_message=True,
        )
        return

    if current_streak >= 5 and not _goal_is_inside_30_days(active_goal):
        # 30-day cycle finished — new big goal needed
        await state.clear()
        await state.set_state(GoalStates.waiting_goal_text)
        await _answer_private_with_actions(
            message,
            "🏁 <b>30-дневный цикл завершён.</b>\n\n"
            "Старый маршрут больше не тянем. Напиши новую большую цель на следующие 30 дней 👇",
            inline_markup=back_to_group_keyboard(RETURN_GROUP_URL) if RETURN_GROUP_URL else None,
            single_message=True,
        )
        return

    # Route is in progress — show current 5-day plan as reminder
    lines = [
        f"📅 <b>Твой текущий маршрут на 5 дней:</b>\n",
        f"<i>Цель: {escape(goal_text)}</i>\n",
    ]
    day_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    for idx, milestone in enumerate(milestones[:5], 1):
        emoji = day_emojis[idx - 1]
        lines.append(f"{emoji} {escape(str(milestone))}")

    route_day = ((current_streak) % 5) + 1 if current_streak > 0 else 1
    lines.extend([
        "",
        f"📍 Сейчас ты на дне <b>{min(route_day, 5)}/5</b> этого маршрута.\n",
        "Держи фокус и продолжай двигаться по шагам 💪",
    ])

    await _answer_private_with_actions(
        message,
        "\n".join(lines),
        inline_markup=back_to_group_keyboard(RETURN_GROUP_URL) if RETURN_GROUP_URL else None,
        inline_text="Вернуться в группу 👇",
        single_message=True,
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
        no_goal_text = (
            "🎯 Сначала зафиксируй большую цель на 30 дней.\n\n"
            "Без неё мы не сможем собрать сильный день, который реально двигает тебя вперёд."
        )
        if CLUB_MENU_URL:
            no_goal_text += f"\n\n📌 <a href=\"{CLUB_MENU_URL}\">Меню клуба</a>"
        await message.answer(no_goal_text, parse_mode="HTML")
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
            "📌 <b>Сначала собери день.</b>\n\n"
            "Чтобы сдать отчет, нужны задачи на сегодня.\n"
            "Открой «Мой день» и зафиксируй до 3 задач — потом возвращайся сюда 👇",
            inline_markup=open_private_flow_keyboard(me.username, "day_setup", "ОТКРЫТЬ МОЙ ДЕНЬ"),
            inline_text="Перейти к сборке дня 👇",
            single_message=True,
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


REFERRAL_GROUP_INVITE_URL = "https://t.me/+WzcCVTajwSozNzYy"
REFERRAL_THROTTLE_SECONDS = 10 * 60


async def _show_referral_invite(message: types.Message) -> None:
    """Генерация и отображение реферального инвайта для пользователя."""
    if not await cache.acquire_lock(f"referral_throttle:{message.from_user.id}", ex=REFERRAL_THROTTLE_SECONDS):
        await message.answer(
            "⏳ Ты уже получал реферальную ссылку. Она выше в этом чате ⬆️\n"
            "Новую можно запросить через 10 минут."
        )
        return

    text, share_url = await referral_service.build_referral_invite(message.bot, message.from_user)

    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🔗 Получить реферальную ссылку", url=share_url)],
            [types.InlineKeyboardButton(text="↩️ Вернуться в группу", url=REFERRAL_GROUP_INVITE_URL)],
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

        if args.startswith("ref_") and args != "ref_setup":
            await referral_service.capture_referral_start(user_id, args)

        has_quiz = await database.has_completed_quiz(user_id)

        if not has_quiz:
            # Новый юзер мог зайти через любую кнопку диплинка (цель/маршрут/
            # день/отчет/рефералка из закрепа группы) — для всех них показываем
            # один и тот же интро-экран с квизом, а не урезанные напоминания
            # внутри отдельных флоу.
            await _send_quiz_intro(message)
            logger.info(f"New user: {user_id}")
            return

        if args == "ref_setup":
            await _show_referral_invite(message)
            return

        if args == "goal_setup" and state:
            await _start_goal_flow(message, state)
            return

        if args == "day_setup" and state:
            await _start_day_flow(message, state)
            return

        if args == "report_setup" and state:
            await _start_report_flow(message, state)
            return

        if args == "route_setup" and state:
            await _start_route_flow(message, state)
            return

        await message.answer(
            "✅ <b>Ты уже в LedoLab Business Club.</b>\n\n"
            "Переходи в группу — там закреплено всё рабочее меню 👇",
            reply_markup=return_to_group_keyboard(RETURN_GROUP_URL),
            parse_mode="HTML",
        )

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
        single_message=True,
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
        single_message=True,
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
    await query.message.answer("Ок, отчет на сегодня не пересдаём. Завтра начнёшь новый день 👇")
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
        single_message=True,
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
        "task_text": "Общий отчет за день",
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
        video_message = None
        try:
            video_message = await query.bot.send_video_note(
                chat_id=target_group_id,
                video_note=report_file_id,
            )
        except Exception as exc:
            logger.warning("Failed to send report video note to group | user=%s error=%s", query.from_user.id, exc)

        summary_message = await query.bot.send_message(
            chat_id=target_group_id,
            text=report["summary_text"],
            reply_markup=report_service.group_report_vote_keyboard(report["id"]),
            reply_to_message_id=video_message.message_id if video_message else None,
        )
        await database.set_daily_report_group_post(report["id"], target_group_id, summary_message.message_id)

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
        f"+{bonus_awarded} LedoBonus за день {streak_day} из 5.\n"
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
        "Отдохни, а завтра вернись и собери новый день с ясной головой ✨",
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Вернуться в группу можно здесь 👇",
        single_message=True,
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
        "📅 Каждый день у тебя есть до 3 задач — это твой фокус\n"
        "🎯 Но баллы ты получаешь не за задачи, а за отчёт\n\n"
        "📤 Сдал отчёт → получил баллы\n"
        "🚫 Не сдал → день не засчитан\n\n"
        "❌ Не выдумывай задачи ради галочки\n"
        "✔️ Делай реальные вещи и честно отчитывайся\n\n"
        "📈 Важно только одно: ты идёшь к своей цели или нет\n\n"
        f"Теперь задача №{current_step + 1}",
        inline_markup=day_task_next_keyboard(current_step + 1),
        single_message=True,
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

    if REPORTS_GROUP_ID:
        user_label = mention_service.build_user_mention(
            telegram_id=query.from_user.id,
            username=club_user.get("username"),
            first_name=club_user.get("first_name") or query.from_user.first_name,
            fallback="Участник",
        )
        group_text_lines = [
            f"📌 {user_label} собрал свой день\n",
            "🎯 <b>Задачи на сегодня:</b>",
        ]
        for idx, task_text in enumerate(tasks, 1):
            group_text_lines.append(f"{idx}. {escape(str(task_text))}")
        group_text_lines.extend([
            "",
            f"⏰ Дедлайн: {_club_day_deadline_text()}",
            "📤 Отчет сдаётся кнопкой из закреплённого сообщения 👆",
            "Погнали 🔥",
        ])
        try:
            await query.bot.send_message(REPORTS_GROUP_ID, "\n".join(group_text_lines))
        except Exception as exc:
            logger.error("Failed to post daily tasks to group: %s", exc, exc_info=True)

    await state.clear()
    await _show_saved_day_message(
        query,
        "\n".join(f"{idx}. {escape(str(task))}" for idx, task in enumerate(tasks, 1)),
        _club_day_deadline_text(),
    )
    await query.answer("Задачи на день зафиксированы ✅")


@router.callback_query(TaskStates.waiting_task_text, F.data == "flow_back")
@router.callback_query(TaskStates.collecting_day_tasks, F.data == "flow_back")
@router.callback_query(TaskStates.reviewing_day_tasks, F.data == "flow_back")
async def handle_day_flow_back(query: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    current_state = await state.get_state()
    tasks = list(data.get("day_tasks") or [])
    week_hint = str(data.get("day_week_hint") or "собери сильный день без перегруза")
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
    """Save the main 30-day goal in FSM and show confirmation preview."""
    goal_text = (message.text or "").strip()
    if len(goal_text) < 5:
        await message.answer("🤏 Напиши цель чуть конкретнее, чтобы было понятно, к чему ты идёшь.")
        return

    await state.update_data(goal_text=goal_text, milestones=[], editing_day=None)
    await state.set_state(GoalStates.confirming_goal)
    await message.answer(
        _build_goal_preview(goal_text),
        reply_markup=goal_text_confirm_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(GoalStates.confirming_goal, F.data == "goal_text_confirm")
async def handle_goal_text_confirmed(query: types.CallbackQuery, state: FSMContext) -> None:
    """User confirmed their 30-day goal — save to DB and offer to split into 5 days."""
    try:
        await query.answer()
        data = await state.get_data()
        goal_text = data.get("goal_text", "")

        user = await database.ensure_club_user(
            telegram_id=query.from_user.id,
            username=query.from_user.username,
            first_name=query.from_user.first_name,
            language_code=query.from_user.language_code or "ru",
        )
        if not user:
            await query.message.answer("❌ Не удалось сохранить цель. Попробуй ещё раз чуть позже.")
            return

        await database.set_active_goal(user["id"], goal_text, [])
        await cache.set_data(cache.KeyManager.get_goal_lock_key(query.from_user.id), "1")
        await cache.delete_data(cache.KeyManager.get_goal_thinking_key(query.from_user.id))

        try:
            await query.message.answer_video_note(
                video_note="DQACAgIAAxkBAAIJ2WovIRV-D8EaM36b9EkcM3QmV5VKAAKZnwACSzGASRFzE7wUgPYzPAQ"
            )
        except Exception as exc:
            logger.warning("Failed to send goal confirmed video note: %s", exc)

        await query.message.answer(
            "🔥 <b>Цель зафиксирована!</b>\n\n"
            f"<blockquote>{escape(goal_text)}</blockquote>\n\n"
            "Теперь нужно разбить её на <b>5-дневный маршрут</b> — "
            "конкретные фокусы на каждый день, чтобы двигаться по шагам, а не в туман.\n\n"
            "Готов сделать это прямо сейчас? 👇",
            reply_markup=goal_split_keyboard(RETURN_GROUP_URL),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Error confirming goal text: %s", e, exc_info=True)
        await query.answer("Ошибка. Попробуй ещё раз.")


@router.callback_query(GoalStates.confirming_goal, F.data == "goal_text_edit")
async def handle_goal_text_edit(query: types.CallbackQuery, state: FSMContext) -> None:
    """User wants to rewrite the 30-day goal."""
    try:
        await query.answer()
        await state.set_state(GoalStates.waiting_goal_text)
        await query.message.answer(
            "✏️ Окей — напиши цель заново.\n\n"
            "Одно чёткое предложение. Конкретный результат через 30 дней 👇",
        )
    except Exception as e:
        logger.error("Error in goal_text_edit: %s", e, exc_info=True)
        await query.answer("Ошибка. Попробуй ещё раз.")


@router.callback_query(GoalStates.waiting_day_text, F.data.startswith("goal_day:"))
@router.callback_query(GoalStates.editing_day, F.data.startswith("goal_day:"))
@router.callback_query(GoalStates.reviewing, F.data.startswith("goal_day:"))
async def open_goal_day_step(query: types.CallbackQuery, state: FSMContext) -> None:
    """Open a specific 5-day milestone step."""
    day_number = int(query.data.split(":")[1])
    await _show_goal_day_prompt(query, state, day_number)
    await query.answer("↩️ Шаг назад")


@router.callback_query(GoalStates.waiting_day_text, F.data == "goal_route_back")
@router.callback_query(GoalStates.editing_day, F.data == "goal_route_back")
async def goal_route_back_to_intro(query: types.CallbackQuery, state: FSMContext) -> None:
    """Step back from day 1 to the 5-day route intro screen."""
    data = await state.get_data()
    goal_text = data.get("goal_text", "")
    await _send_goal_route_intro(query, goal_text)
    await query.answer("↩️ Шаг назад")


@router.callback_query(GoalStates.reviewing, F.data == "goal_review_back")
async def goal_review_back_to_day(query: types.CallbackQuery, state: FSMContext) -> None:
    """Step back from the 5-day review screen to the last day input."""
    await _show_goal_day_prompt(query, state, 5)
    await query.answer("↩️ Шаг назад")


@router.callback_query(GoalStates.reviewing, F.data == "goal_edit_back")
async def goal_edit_back_to_review(query: types.CallbackQuery, state: FSMContext) -> None:
    """Step back from the day-picker to the 5-day review screen."""
    await _show_goal_review(query, state)
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
        await _show_goal_day_prompt(
            message,
            state,
            day_number + 1,
            prefix=f"✅ <b>{day_number}-й день сохранён.</b>\n\n",
        )
        return

    if all(milestones[:5]) and len(milestones) >= 5:
        await state.update_data(editing_day=None)
        await state.set_state(GoalStates.reviewing)
        await _show_goal_review(message, state)
        return

    next_missing = next((idx for idx, value in enumerate(milestones, 1) if not value), day_number + 1)
    await _show_goal_day_prompt(
        message,
        state,
        next_missing,
        prefix="✅ <b>День сохранён.</b>\n\n",
    )


@router.callback_query(GoalStates.reviewing, F.data == "goal_edit")
async def edit_goal_days(query: types.CallbackQuery, state: FSMContext) -> None:
    """Open selective editing for one of the 5 days."""
    await _answer_private_with_actions(
        query,
        "✏️ Выбери день, который хочешь поправить.\n\n"
        "Тебе не нужно переписывать все заново — можно изменить только то, что реально хочется улучшить 👇",
        inline_markup=goal_edit_days_keyboard(),
        single_message=True,
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
            "Когда будешь готов собрать сегодняшний день — жми кнопку ниже.",
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
        if CLUB_MENU_URL:
            group_text_lines.extend(["", "👇 Продолжай ставить цели и собирать дни здесь:"])
        try:
            await query.bot.send_message(
                REPORTS_GROUP_ID,
                "\n".join(group_text_lines),
                reply_markup=(
                    types.InlineKeyboardMarkup(
                        inline_keyboard=[[types.InlineKeyboardButton(text="📌 Меню клуба", url=CLUB_MENU_URL)]]
                    )
                    if CLUB_MENU_URL
                    else None
                ),
            )
        except Exception as exc:
            logger.error("Failed to post goal to group: %s", exc, exc_info=True)

    me = await query.bot.get_me()
    try:
        await query.message.answer_video_note(
            video_note="DQACAgIAAxkBAAIJ3GovIl7y-TqRnzydfAABRSzrDtx23AACqJ8AAksxgElxbENHNxKwRTwE"
        )
    except Exception as exc:
        logger.warning("Failed to send route confirmed video note: %s", exc)
    await _answer_private_with_actions(
        query,
        "🚀 <b>Готово. Твоя большая цель и 5-дневный маршрут зафиксированы.</b>\n\n"
        "Теперь у тебя есть не просто желание, а понятный план движения.\n\n"
        "Если готов уже <b>сегодня</b> начать — нажимай кнопку\n"
        "<b>📌 Мой день (до 3х задач)</b>.\n\n"
        "Если пока не готов — просто вернись в группу и продолжишь позже.",
        inline_markup=after_goal_confirm_keyboard(me.username, CLUB_GROUP_URL),
        single_message=True,
    )
    await state.clear()
    await query.answer("Цели подтверждены ✅")


# --- Stale goal-flow buttons (no FSM state) -------------------------------
# Registered AFTER all state-specific goal handlers, so they only catch clicks
# on OUTDATED messages whose flow was already finished (state cleared).
@router.callback_query(
    F.data.startswith("goal_day:")
    | F.data.in_({"goal_route_back", "goal_review_back", "goal_edit_back", "goal_confirm", "goal_edit"})
)
async def handle_stale_goal_buttons(query: types.CallbackQuery) -> None:
    """Catch clicks on outdated goal-flow buttons after the route is confirmed."""
    if await _route_already_set(query.from_user.id):
        await query.answer("✅ Цели уже поставлены. Менять нельзя.", show_alert=True)
    else:
        await query.answer(
            "⚠️ Это меню устарело. Открой 📅 Моя цель на 5 дней заново.",
            show_alert=True,
        )


# --- TEMP: file_id extractor (remove after use) ---------------------------
@router.message(F.from_user.id == 516684869, F.video_note, F.chat.type == "private")
async def temp_get_video_note_file_id(message: types.Message) -> None:
    await message.answer(f"file_id:\n<code>{message.video_note.file_id}</code>", parse_mode="HTML")


