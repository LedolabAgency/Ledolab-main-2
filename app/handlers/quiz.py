"""
Quiz handler - processes quiz completion from WebApp.
"""

import logging
import json
from aiogram import Router, types, F
from app import database
from app.keyboards.inline.start import contact_reply_keyboard, club_main_menu
from app.services import quiz_service

logger = logging.getLogger(__name__)
router = Router()


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
        
        # Save quiz answers
        await database.save_quiz_answers(user["id"], quiz_data)
        
        # Calculate business profile
        profile = quiz_service.calculate_business_profile(quiz_data)
        
        # Update user profile
        await database.update_user_profile(
            user_id=user["id"],
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
            "Остання твоя дія — поділитися номером телефону.",
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
        await message.answer("Не вдалося отримати номер телефону.")
        return
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer("Поділись, будь ласка, саме своїм номером телефону.")
        return

    logger.info(
        "Contact shared by user %s: %s",
        message.from_user.id,
        contact.phone_number,
    )
    await database.save_phone_number(
        telegram_id=message.from_user.id,
        phone_number=contact.phone_number,
    )

    await message.answer(
        "Дякую! Номер телефону отримали. Тепер можеш перейти в меню LedoLab.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await message.answer(
        "LedoLab\n\nОбери наступну дію:",
        reply_markup=club_main_menu(),
    )
