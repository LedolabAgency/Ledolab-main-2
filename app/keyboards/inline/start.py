"""
Bot keyboards for LedoLab Business Club.
"""

from aiogram import types


def quiz_reply_keyboard(web_app_url: str) -> types.ReplyKeyboardMarkup:
    """Persistent reply keyboard with the quiz entry point."""
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(
                    text="ПРОЙТИ КВИЗ",
                    web_app=types.WebAppInfo(url=web_app_url),
                )
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Нажми кнопку ниже",
    )


def contact_reply_keyboard() -> types.ReplyKeyboardMarkup:
    """Reply keyboard that requests the user's phone number."""
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(
                    text="ПОДЕЛИТЬСЯ НОМЕРОМ ТЕЛЕФОНА",
                    request_contact=True,
                )
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Поделись номером телефона",
    )


def private_hub_reply_keyboard() -> types.ReplyKeyboardMarkup:
    """Persistent private keyboard after the quiz is completed."""
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🎯 Моя цель 30 дней")],
            [types.KeyboardButton(text="📅 Мой план на 5 дней")],
            [types.KeyboardButton(text="📌 Мой день (до 3х задач)")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выбери действие ниже 👇",
    )


def club_group_keyboard(group_url: str | None) -> types.InlineKeyboardMarkup | None:
    """Single CTA that sends the user to the working group."""
    if not group_url:
        return None

    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="ПЕРЕЙТИ В ГРУППУ LedoLab Business Club", url=group_url)],
        ]
    )


def open_bot_private_keyboard(bot_username: str) -> types.InlineKeyboardMarkup:
    """CTA that opens the bot in a private chat."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="ОТКРЫТЬ БОТА В ЛИЧКЕ",
                    url=f"https://t.me/{bot_username}?start=onboarding",
                )
            ],
        ]
    )


def open_private_flow_keyboard(bot_username: str, start_param: str, button_text: str) -> types.InlineKeyboardMarkup:
    """CTA that opens a specific private flow via deep link."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=button_text,
                    url=f"https://t.me/{bot_username}?start={start_param}",
                )
            ],
        ]
    )


def goal_day_step_keyboard(day_number: int) -> types.InlineKeyboardMarkup:
    """Single wide button for the next day step."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=f"{day_number}-Й ДЕНЬ", callback_data=f"goal_day:{day_number}")],
        ]
    )


def goal_review_keyboard() -> types.InlineKeyboardMarkup:
    """Actions after the full 7-day plan is prepared."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="УТВЕРДИТЬ ЦЕЛИ", callback_data="goal_confirm")],
            [types.InlineKeyboardButton(text="ИЗМЕНИТЬ ЦЕЛИ", callback_data="goal_edit")],
        ]
    )


def goal_edit_days_keyboard() -> types.InlineKeyboardMarkup:
    """Pick which day to edit before final confirmation."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="1-Й ДЕНЬ", callback_data="goal_edit_day:1")],
            [types.InlineKeyboardButton(text="2-Й ДЕНЬ", callback_data="goal_edit_day:2")],
            [types.InlineKeyboardButton(text="3-Й ДЕНЬ", callback_data="goal_edit_day:3")],
            [types.InlineKeyboardButton(text="4-Й ДЕНЬ", callback_data="goal_edit_day:4")],
            [types.InlineKeyboardButton(text="5-Й ДЕНЬ", callback_data="goal_edit_day:5")],
        ]
    )


def club_main_menu(bot_username: str | None = None) -> types.InlineKeyboardMarkup:
    """Main working menu. In groups all buttons open the private bot."""
    goal_button: types.InlineKeyboardButton
    day_button: types.InlineKeyboardButton
    report_button: types.InlineKeyboardButton
    rating_button: types.InlineKeyboardButton
    rules_button: types.InlineKeyboardButton
    if bot_username:
        goal_button = types.InlineKeyboardButton(
            text="🎯 Моя цель (30 дней)",
            url=f"https://t.me/{bot_username}?start=goal_setup",
        )
        day_button = types.InlineKeyboardButton(
            text="📅 Мой день (до 3х задач)",
            url=f"https://t.me/{bot_username}?start=day_setup",
        )
        report_button = types.InlineKeyboardButton(
            text="📤 Сдать отчет",
            url=f"https://t.me/{bot_username}?start=report_setup",
        )
        rating_button = types.InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating_view")
        rules_button = types.InlineKeyboardButton(text="📘 Как работает клуб", callback_data="rules_view")
    else:
        goal_button = types.InlineKeyboardButton(text="🎯 Моя цель (30 дней)", callback_data="goal_view")
        day_button = types.InlineKeyboardButton(text="📅 Мой день (до 3х задач)", callback_data="day_view")
        report_button = types.InlineKeyboardButton(text="📤 Сдать отчет", callback_data="report_submit")
        rating_button = types.InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating_view")
        rules_button = types.InlineKeyboardButton(text="📘 Как работает клуб", callback_data="rules_view")

    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [goal_button],
            [day_button],
            [report_button],
            [rating_button],
            [rules_button],
        ]
    )


def report_count_keyboard() -> types.InlineKeyboardMarkup:
    """Choose how many tasks were completed today."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="0/3", callback_data="report_count:0"),
                types.InlineKeyboardButton(text="1/3", callback_data="report_count:1"),
                types.InlineKeyboardButton(text="2/3", callback_data="report_count:2"),
                types.InlineKeyboardButton(text="3/3", callback_data="report_count:3"),
            ]
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
