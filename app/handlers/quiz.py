"""
Quiz handler - processes quiz completion from WebApp.
"""

import logging
import json
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from app import database, cache
from app.config import CLUB_GROUP_URL, GROUP_ENTRY_URL
from app.keyboards.inline.start import contact_reply_keyboard, club_group_keyboard, return_to_group_keyboard
from app.services import community_service, quiz_service, referral_service

logger = logging.getLogger(__name__)
router = Router()


def _pending_quiz_key(user_id: int) -> str:
    return f"pending_quiz:{user_id}"


@router.message(F.web_app_data)
async def handle_quiz_completion(message: types.Message, state: FSMContext) -> None:
    """
    Handle WebApp quiz data.
    Creates user profile after quiz completion.
    """
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    try:
        # Parse quiz data
        quiz_data = json.loads(message.web_app_data.data)
        
        # Validate quiz data
        if not quiz_service.validate_quiz(quiz_data):
            await message.answer("Error in quiz data.")
            logger.warning(f"Invalid quiz data from {user_id}")
            return
        
        progress_msg = await message.answer("Processing...")
        
        # Create user in database
        user = await database.create_user(
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            language_code=message.from_user.language_code or "ru",
        )
        
        if not user:
            await progress_msg.edit_text("Error. Try later.")
            return

        await database.ensure_club_user(
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            language_code=message.from_user.language_code or "ru",
        )
        await referral_service.bind_pending_referral(user_id)

        # Save quiz answers immediately so the user can resume even if Redis expires.
        await database.save_quiz_answers(user_id, quiz_data)

        # Cache quiz answers until the user shares a phone number.
        await cache.set_data(
            _pending_quiz_key(user_id),
            json.dumps(quiz_data, ensure_ascii=False),
            ex=30 * 24 * 60 * 60,
        )
        
        # Calculate business profile
        profile = quiz_service.calculate_business_profile(quiz_data)
        
        # Update user profile
        await database.update_user_profile(
            user_id=user_id,
            business_level=profile["business_level"],
            focus_zone=profile["focus_zone"],
            discipline_potential=profile["discipline_potential"],
        )
        
        # Generate profile text
        profile_text = quiz_service.generate_profile_text(
            business_level=profile["business_level"],
            focus_zone=profile["focus_zone"],
            discipline_potential=profile["discipline_potential"],
        )
        
        # Delete progress message
        await progress_msg.delete()
        
        # Ask for the final action after quiz completion
        await message.answer(profile_text)
        await message.answer(
            "Последнее действие — поделиться номером телефона.",
            reply_markup=contact_reply_keyboard(),
        )
        
        logger.info(f"Quiz completed: {user_id}")
        
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {user_id}")
        await message.answer("Error processing data.")
    except Exception as e:
        logger.error(f"Error in quiz handler: {e}", exc_info=True)
        await message.answer("Critical error. Try later.")


@router.message(F.contact)
async def handle_contact_share(message: types.Message) -> None:
    """Handle phone number sharing after quiz completion."""
    contact = message.contact
    if not contact:
        await message.answer("Не удалось получить номер телефона.")
        return
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer("Поделись, пожалуйста, именно своим номером телефона.")
        return

    logger.info(
        "Contact shared by user %s: %s",
        message.from_user.id,
        contact.phone_number,
    )
    cached_quiz_data = await cache.get_data(_pending_quiz_key(message.from_user.id))
    if cached_quiz_data:
        quiz_data = json.loads(cached_quiz_data)
        saved = await database.save_onboarding_submission(
            telegram_id=message.from_user.id,
            quiz_data=quiz_data,
            phone_number=contact.phone_number,
        )
        if not saved:
            await message.answer("Не удалось сохранить анкету. Попробуй еще раз позже.")
            return
    else:
        saved = await database.save_phone_number(
            telegram_id=message.from_user.id,
            phone_number=contact.phone_number,
        )
        if not saved:
            await message.answer("Не удалось сохранить номер телефона. Попробуй еще раз позже.")
            return

    await cache.delete_data(_pending_quiz_key(message.from_user.id))
    await referral_service.bind_pending_referral(message.from_user.id)

    try:
        remove_msg = await message.answer("​", reply_markup=types.ReplyKeyboardRemove())
        await remove_msg.delete()
    except Exception as e:
        logger.warning("Failed to remove reply keyboard: %s", e)

    try:
        await message.answer_video_note(video_note="DQACAgIAAxkBAAIJAAFqLsz794WUmlRDtogPNDxFyHhzNAACjp8AAksxeEmZvGQ5Iw-gZTwE")
    except Exception as e:
        logger.warning("Failed to send welcome video note: %s", e)
    group_url = GROUP_ENTRY_URL or CLUB_GROUP_URL
    await message.answer(
        "✅ <b>Готово — ты внутри LedoLab Business Club.</b>\n\n"
        "Это не чат мотивации. Это среда, где предприниматели каждый день "
        "показывают реальное действие, держат фокус и растут в рейтинге.\n\n"
        "Как это работает:\n"
        "1️⃣ Ставишь цель на 30 дней\n"
        "2️⃣ Разбиваешь на 5-дневные маршруты\n"
        "3️⃣ Каждый день — до 3 задач + вечерний отчет\n"
        "4️⃣ Получаешь LedoScore и растёшь в рейтинге\n\n"
        "Заходи в группу — там закреплено рабочее меню клуба 👇",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="Зайти в группу", url=group_url)]]
        ) if group_url else None,
        parse_mode="HTML",
    )
    try:
        await community_service.announce_member_joined(
            message.bot,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
    except Exception as e:
        logger.warning("Failed to announce member %s in group: %s", message.from_user.id, e)
