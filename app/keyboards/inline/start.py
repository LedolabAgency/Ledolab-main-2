"""
Bot keyboards for LedoLab.
"""

from aiogram import types


def quiz_reply_keyboard(web_app_url: str) -> types.ReplyKeyboardMarkup:
    """Persistent reply keyboard with the quiz entry point."""
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(
                    text="ПРОЙТИ КВІЗ",
                    web_app=types.WebAppInfo(url=web_app_url),
                )
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Натисни кнопку нижче",
    )


def contact_reply_keyboard() -> types.ReplyKeyboardMarkup:
    """Reply keyboard that requests the user's phone number."""
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(
                    text="ПОДІЛИТИСЯ НОМЕРОМ ТЕЛЕФОНУ",
                    request_contact=True,
                )
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Поділись номером телефону",
    )


def club_main_menu() -> types.InlineKeyboardMarkup:
    """
    Main LedoLab menu.
    
    🎯 Поставить задачу
    ✅ Сдать отчет
    🚀 Моя цель
    🏆 Рейтинг
    💤 День без фокуса
    ❌ Слил день
    """
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🎯 Поставить задачу", callback_data="task_set")],
            [types.InlineKeyboardButton(text="✅ Сдать отчет", callback_data="report_submit")],
            [types.InlineKeyboardButton(text="🚀 Моя цель", callback_data="goal_view")],
            [types.InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating_view")],
            [types.InlineKeyboardButton(text="💤 День без фокуса", callback_data="day_skip")],
            [types.InlineKeyboardButton(text="❌ Слил день", callback_data="day_fail")],
        ]
    )


def confirm_task() -> types.InlineKeyboardMarkup:
    """Confirm task setting."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Подтвердить", callback_data="task_confirm")],
            [types.InlineKeyboardButton(text="◈ Переделать", callback_data="task_redo")],
        ]
    )


def confirm_report() -> types.InlineKeyboardMarkup:
    """Confirm report submission."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Отправить отчет", callback_data="report_send")],
            [types.InlineKeyboardButton(text="◈ Переделать", callback_data="report_redo")],
        ]
    )


def confirm_goal() -> types.InlineKeyboardMarkup:
    """Confirm goal and milestones."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Подтвердить цель", callback_data="goal_confirm")],
            [types.InlineKeyboardButton(text="◈ Изменить", callback_data="goal_redo")],
        ]
    )


def rating_actions() -> types.InlineKeyboardMarkup:
    """Rating view actions."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🔄 Обновить", callback_data="rating_refresh")],
            [types.InlineKeyboardButton(text="◈ В меню", callback_data="menu_back")],
        ]
    )


def admin_panel() -> types.InlineKeyboardMarkup:
    """Admin panel main menu."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="👥 Участники", callback_data="admin_users")],
            [types.InlineKeyboardButton(text="🏆 Рейтинг", callback_data="admin_rating")],
            [types.InlineKeyboardButton(text="🎯 Цели", callback_data="admin_goals")],
            [types.InlineKeyboardButton(text="✅ Отчеты", callback_data="admin_reports")],
            [types.InlineKeyboardButton(text="⭐ Оценить проект", callback_data="admin_score")],
            [types.InlineKeyboardButton(text="🚫 Бан", callback_data="admin_ban")],
        ]
    )


def back_button() -> types.InlineKeyboardMarkup:
    """Simple back button."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="◈ Назад", callback_data="menu_back")]
        ]
    )
