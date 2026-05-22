"""
Start handler - initial bot greeting and quiz link.
"""

import logging
from aiogram import Router, types
from aiogram.filters import CommandStart
from app.config import WEB_APP_URL, CLUB_GROUP_URL
from app.keyboards.inline.start import quiz_reply_keyboard, club_group_keyboard
from app import database

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    """
    /start command handler.
    Shows welcome message and quiz link.
    """
    user_id = message.from_user.id
    
    try:
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
