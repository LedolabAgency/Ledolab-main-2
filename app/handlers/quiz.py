"""
Quiz handler - processes quiz completion from WebApp.
"""

import logging
import json
from aiogram import Router, types, F
from app import database, cache
from app.config import CLUB_GROUP_URL
from app.keyboards.inline.start import contact_reply_keyboard, club_group_keyboard, private_hub_reply_keyboard
from app.services import quiz_service

logger = logging.getLogger(__name__)
router = Router()


def _pending_quiz_key(user_id: int) -> str:
    return f"pending_quiz:{user_id}"


@router.message(F.web_app_data)
async def handle_quiz_completion(message: types.Message) -> None:
    """
    Handle WebApp quiz data.
    Creates user profile after quiz completion.
    """
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
        
        # Cache quiz answers until the user shares a phone number.
        await cache.set_data(
            _pending_quiz_key(user_id),
            json.dumps(quiz_data, ensure_ascii=False),
            ex=3600,
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
        await message.answer(
            profile_text,
        )
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
    if not cached_quiz_data:
        await message.answer(
            "Не нашли твой последний квиз. Пожалуйста, пройди квиз заново.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return

    quiz_data = json.loads(cached_quiz_data)
    saved = await database.save_onboarding_submission(
        telegram_id=message.from_user.id,
        quiz_data=quiz_data,
        phone_number=contact.phone_number,
    )
    if not saved:
        await message.answer("Не удалось сохранить анкету. Попробуй еще раз позже.")
        return

    await cache.delete_data(_pending_quiz_key(message.from_user.id))

    await message.answer(
        "Спасибо! Анкету и номер телефона сохранили.",
        reply_markup=private_hub_reply_keyboard(),
    )
    await message.answer(
        "LedoLab Business Club\n\nКвиз пройден ✅\n"
        "Кнопку квиза я больше не показываю — она тебе уже не нужна.\n\n"
        "Внизу у тебя теперь постоянные кнопки:\n"
        "• цель на 30 дней\n"
        "• план на 7 дней\n"
        "• мой день\n\n"
        "Все рабочие действия и отчеты доступны через группу.",
        reply_markup=club_group_keyboard(CLUB_GROUP_URL),
    )
