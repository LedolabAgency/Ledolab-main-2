"""
Start handler - initial bot greeting and quiz link.
"""

import logging
from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from app.config import WEB_APP_URL, CLUB_GROUP_URL, GOAL_SCORE
from app.keyboards.inline.start import (
    quiz_reply_keyboard,
    club_group_keyboard,
    open_bot_private_keyboard,
    club_main_menu,
    goal_day_step_keyboard,
    goal_review_keyboard,
    goal_edit_days_keyboard,
)
from app import database, cache
from app.states.quiz import GoalStates

logger = logging.getLogger(__name__)
router = Router()

GOAL_LOCK_TTL = 30 * 24 * 60 * 60
WEEK_PLAN_LOCK_TTL = 7 * 24 * 60 * 60


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

        if start_arg == "goal_setup":
            if await cache.get_data(_goal_lock_key(user_id)):
                await message.answer(
                    "Цель на 30 дней уже зафиксирована. Пока срок не закончится, новую добавить нельзя.",
                    reply_markup=club_group_keyboard(CLUB_GROUP_URL),
                )
                return

            await state.clear()
            await state.set_state(GoalStates.waiting_goal_text)
            await message.answer("Какая твоя цель на 30 дней?")
            return

        # Check if user already registered
        existing_user = await database.get_user(user_id)
        
        if existing_user:
            await message.answer(
                f"Привет, {message.from_user.first_name}! Ты уже в LedoLab Business Club.",
                reply_markup=club_group_keyboard(CLUB_GROUP_URL),
            )
            await message.answer("Все рабочие действия доступны только в группе LedoLab Business Club.")
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

    if await cache.get_data(_goal_lock_key(message.from_user.id)):
        await message.answer(
            "Цель на 30 дней уже зафиксирована. Изменить ее можно только после окончания текущего периода.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        await state.clear()
        return

    await state.update_data(goal_text=message.text.strip())
    await state.set_state(GoalStates.waiting_milestones)
    await state.update_data(week_plan=[""] * 7, current_day=1, edit_mode=False)
    await message.answer(
        "Ок.\n\nТеперь разобьем цель на 7 шагов по дням.",
        reply_markup=goal_day_step_keyboard(1),
    )


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
        await message.answer("План на 7 дней заполняется только в личке с ботом.")
        await state.clear()
        return

    data = await state.get_data()
    active_day = data.get("active_day")
    if not active_day:
        await message.answer("Не удалось определить день. Нажми кнопку дня еще раз.")
        await state.clear()
        return

    week_plan = list(data.get("week_plan", [""] * 7))
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

    if active_day < 7:
        next_day = active_day + 1
        await state.update_data(current_day=next_day, active_day=None)
        await state.set_state(GoalStates.waiting_milestones)
        await message.answer(
            f"{active_day}-й день сохранен.",
            reply_markup=goal_day_step_keyboard(next_day),
        )
        return

    await state.update_data(current_day=7, active_day=None)
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
    if len(week_plan) != 7 or any(not item for item in week_plan):
        await query.message.answer("Сначала заполни все 7 дней.")
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
    for day_number, day_text in enumerate(week_plan, 1):
        await cache.set_data(_goal_day_lock_key(query.from_user.id, day_number), day_text, ex=WEEK_PLAN_LOCK_TTL)

    await query.message.answer(
        "🚀 Цели утверждены и сохранены.\n\nТеперь возвращайся в группу и открывай /menu -> 📅 Мой день (3 задачи).",
        reply_markup=club_group_keyboard(CLUB_GROUP_URL),
    )
    await state.clear()
    await query.answer()


@router.message(Command("menu"))
async def cmd_menu(message: types.Message) -> None:
    """
    /menu command handler.
    Shows working inline buttons in the group only.
    """
    try:
        if message.chat.type == "private":
            await message.answer(
                "Рабочие кнопки доступны только в группе LedoLab Business Club.",
                reply_markup=club_group_keyboard(CLUB_GROUP_URL),
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
