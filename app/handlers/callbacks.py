"""
Callback handlers for menu navigation.
"""

import logging
from aiogram import Router, types, F
from app.config import CLUB_GROUP_URL
from app.keyboards.inline.start import club_group_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "club_enter")
async def enter_club(query: types.CallbackQuery) -> None:
    """
    Enter LedoLab main menu.
    """
    try:
        await query.message.edit_text(
            "LedoLab Business Club\n\nВсе рабочие действия доступны только в группе.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.answer("Error")


@router.callback_query(F.data == "menu_back")
async def back_to_menu(query: types.CallbackQuery) -> None:
    """
    Return to main menu.
    """
    try:
        await query.message.edit_text(
            "LedoLab Business Club\n\nПереходи в группу, чтобы работать с ботом дальше.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.answer("Error")
