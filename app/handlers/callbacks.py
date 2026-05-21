"""
Callback handlers for menu navigation.
"""

import logging
from aiogram import Router, types, F
from app.keyboards.inline.start import club_main_menu

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "club_enter")
async def enter_club(query: types.CallbackQuery) -> None:
    """
    Enter Business To-Do Club main menu.
    """
    try:
        await query.message.edit_text(
            "Business To-Do Club\n\nSelect action:",
            reply_markup=club_main_menu(),
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
            "Business To-Do Club",
            reply_markup=club_main_menu(),
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.answer("Error")
