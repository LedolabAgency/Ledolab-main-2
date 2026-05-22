"""
Start handler - initial bot greeting and quiz link.
"""

import logging
from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from app.config import WEB_APP_URL, CLUB_GROUP_URL, GOAL_SCORE
from app.keyboards.inline.start import (
    quiz_reply_keyboard,
    club_group_keyboard,
    open_bot_private_keyboard,
    club_main_menu,
)
from app import database
from app.states.quiz import GoalStates

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    """
    /start command handler.
    Shows welcome message and quiz link.
    """
    user_id = message.from_user.id
    
    try:
        start_arg = ""
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                start_arg = parts[1].strip()

        if message.chat.type != "private":
            me = await message.bot.get_me()
            await message.answer(
                "Квиз доступен только в личке с ботом.\n\n"
                "Открой LedoLab Business Club в личных сообщениях и пройди onboarding там.",
                reply_markup=open_bot_private_keyboard(me.username),
            )
            return

        if start_arg == "goal_setup":
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

    await state.update_data(goal_text=message.text.strip())
    await state.set_state(GoalStates.waiting_milestones)
    await message.answer("Ок.\n\nТеперь разбей цель на 7 шагов по дням. Отправь их через новую строку.")


@router.message(GoalStates.waiting_milestones)
async def private_goal_week_plan(message: types.Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer("План на 7 дней заполняется только в личке с ботом.")
        await state.clear()
        return

    week_plan = [item.strip("-• \t") for item in message.text.splitlines() if item.strip()]
    if len(week_plan) != 7:
        await message.answer("Нужно ровно 7 строк: День 1 ... День 7. Попробуй еще раз.")
        return

    data = await state.get_data()
    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось сохранить цель. Попробуй позже.")
        await state.clear()
        return

    goal = await database.set_active_goal(club_user["id"], data["goal_text"], week_plan)
    if not goal:
        await message.answer("Не удалось сохранить цель. Попробуй позже.")
        await state.clear()
        return

    await database.award_score(club_user["id"], GOAL_SCORE, "30-day goal set")
    await message.answer(
        "🚀 Цель зафиксирована.\n\nТеперь возвращайся в группу и открывай /menu -> 📅 Мой день (3 задачи).",
        reply_markup=club_group_keyboard(CLUB_GROUP_URL),
    )
    await state.clear()


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

        await message.answer(
            "LedoLab Business Club\n\nРабочее меню:",
            reply_markup=club_main_menu(),
        )
    except Exception as e:
        logger.error(f"Error in /menu: {e}", exc_info=True)
        await message.answer("Error. Try later.")
