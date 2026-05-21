"""
Start handler - initial bot greeting and quiz link.
"""

import logging
from aiogram import Router, types
from aiogram.filters import CommandStart
from app.config import WEB_APP_URL
from app.keyboards.inline.start import start_keyboard
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
                f"Привет, {message.from_user.first_name}! Ты уже в клубе.",
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text="Menu", callback_data="club_enter")]
                    ]
                ),
            )
            return
        
        # New user - show welcome
        welcome_text = (
            "Leda.lab Business Club\n\n"
            "Пройди диагностику."
        )
        
        await message.answer(welcome_text, reply_markup=start_keyboard(WEB_APP_URL))
        logger.info(f"New user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.answer("Error. Try later.")
