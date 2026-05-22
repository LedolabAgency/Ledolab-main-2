"""
Callback handlers for menu navigation.
"""

import logging
from aiogram import Router, types, F
from app import database
from app.config import WEB_APP_URL
from app.keyboards.inline.start import club_main_menu, quiz_reply_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "club_enter")
async def enter_club(query: types.CallbackQuery) -> None:
    """
    Enter LedoLab main menu.
    """
    try:
        if not await database.has_completed_quiz(query.from_user.id):
            await query.message.edit_text(
                "🧭 Сначала пройди квиз, чтобы открыть рабочие кнопки клуба 👇",
            )
            await query.message.answer(reply_markup=quiz_reply_keyboard(WEB_APP_URL), text="ПРОЙДИ КВИЗ")
            await query.answer()
            return
        me = await query.bot.get_me()
        await query.message.edit_text(
            "LedoLab Business Club\n\nРабочее меню:",
            reply_markup=club_main_menu(me.username),
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
        if not await database.has_completed_quiz(query.from_user.id):
            await query.message.edit_text(
                "🧭 Сначала пройди квиз, чтобы открыть рабочие кнопки клуба 👇",
            )
            await query.message.answer(reply_markup=quiz_reply_keyboard(WEB_APP_URL), text="ПРОЙДИ КВИЗ")
            await query.answer()
            return
        me = await query.bot.get_me()
        await query.message.edit_text(
            "LedoLab Business Club\n\nРабочее меню:",
            reply_markup=club_main_menu(me.username),
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.answer("Error")
