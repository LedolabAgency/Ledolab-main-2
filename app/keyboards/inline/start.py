"""
Inline keyboards for Leda.lab Business Club.
Premium UI with InlineKeyboardMarkup only.
"""

from aiogram import types


def start_keyboard(web_app_url: str) -> types.InlineKeyboardMarkup:
    """
    Main start screen with quiz button.
    
    ◈ Leda.lab Business Club
    Закрытая среда для предпринимателей...
    """
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="◈ Начать диагностику",
                    web_app=types.WebAppInfo(url=web_app_url),
                )
            ]
        ]
    )


def club_main_menu() -> types.InlineKeyboardMarkup:
    """
    Main Business To-Do Club menu.
    
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
