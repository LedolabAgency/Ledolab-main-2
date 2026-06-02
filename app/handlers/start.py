"""Start handler and private deep-link flows for LedoLab Business Club."""

from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext

from app import cache, database
from app.config import CLUB_GROUP_URL, REPORTS_GROUP_ID, WEB_APP_URL
from app.keyboards.inline.start import (
    after_goal_confirm_keyboard,
    back_to_group_keyboard,
    club_main_menu,
    goal_day_step_keyboard,
    goal_edit_days_keyboard,
    goal_review_keyboard,
    open_bot_keyboard,
    private_hub_reply_keyboard,
    start_keyboard,
)
from app.states.quiz import GoalStates, TaskStates

logger = logging.getLogger(__name__)
router = Router()


async def _delete_private_message_safely(message: types.Message) -> None:
    if message.chat.type != "private":
        return
    try:
        await message.delete()
    except Exception as e:
        logger.debug("Failed to delete private message %s: %s", message.message_id, e)


async def _answer_private_with_actions(
    target: types.Message | types.CallbackQuery,
    text: str,
    *,
    inline_markup: types.InlineKeyboardMarkup | None = None,
    inline_text: str = "Выбери действие ниже 👇",
) -> None:
    if isinstance(target, types.CallbackQuery):
        chat = target.message.chat
        sender = target.message
    else:
        chat = target.chat
        sender = target

    sent = await sender.answer(
        text,
        reply_markup=private_hub_reply_keyboard() if chat.type == "private" else None,
    )
    if inline_markup:
        await sent.answer(inline_text, reply_markup=inline_markup)


def _build_goal_review(goal_text: str, milestones: list[str]) -> str:
    lines = [
        "🧠 Проверь свой маршрут перед подтверждением\n",
        "🎯 <b>Твоя большая цель на 30 дней:</b>",
        goal_text,
        "",
        "📅 <b>Фокус на ближайшие 7 дней:</b>",
    ]
    for idx, milestone in enumerate(milestones, 1):
        lines.append(f"{idx}. {milestone}")
    lines.extend(
        [
            "",
            "Если все выглядит правильно — жми <b>УТВЕРДИТЬ ЦЕЛИ</b> ✅",
            "Если хочешь поправить конкретный день — жми <b>ИЗМЕНИТЬ ЦЕЛИ</b> ✏️",
        ]
    )
    return "\n".join(lines)


async def _show_goal_review(target: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    goal_text = data.get("goal_text", "")
    milestones = data.get("milestones", [])
    review_text = _build_goal_review(goal_text, milestones)

    await _answer_private_with_actions(
        target,
        review_text,
        inline_markup=goal_review_keyboard(),
        inline_text="Проверь все и выбери, что делать дальше 👇",
    )


async def _start_goal_flow(message: types.Message, state: FSMContext) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз, чтобы я понял, на каком ты этапе и как тебя правильно вести дальше.\n\n"
            "После квиза откроются цель на 30 дней, план на 7 дней и дневные задачи 👇",
            reply_markup=start_keyboard(WEB_APP_URL),
        )
        return

    goal_lock = await cache.get_data(cache.KeyManager.get_goal_lock_key(message.from_user.id))
    if goal_lock:
        me = await message.bot.get_me()
        await _answer_private_with_actions(
            message,
            "🔒 <b>Твоя цель на 30 дней уже зафиксирована.</b>\n\n"
            "Это не ошибка, а часть дисциплины клуба.\n"
            "Мы специально не даем менять большую цель каждый день, чтобы ты не сбивал себе фокус.\n\n"
            "Если готов приступить уже сегодня — жми кнопку ниже 👇",
            inline_markup=after_goal_confirm_keyboard(me.username, CLUB_GROUP_URL),
            inline_text="Если хочешь — можешь сразу перейти к сборке дня или вернуться в группу 👇",
        )
        return

    await state.clear()
    await state.set_state(GoalStates.waiting_goal_text)
    await _answer_private_with_actions(
        message,
        "🎯 <b>LedoLab Business Club</b>\n\n"
        "Сейчас мы спокойно соберем твой маршрут на ближайшие <b>30 дней</b>.\n\n"
        "Как это работает:\n"
        "1. Ты ставишь <b>1 главную цель</b> на месяц\n"
        "2. Потом разбиваешь ее на <b>7 ближайших дней</b>\n"
        "3. А уже после этого превращаешь каждый день в <b>до 3 конкретных задач</b>\n\n"
        "Не усложняй и не пиши все сразу.\n"
        "Сейчас нужен только один понятный ориентир, к которому ты реально хочешь прийти 🔥\n\n"
        "Напиши свою <b>цель на 30 дней</b> 👇",
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Если хочешь вернуться в группу — вот быстрый переход 👇",
    )


async def _start_day_flow(message: types.Message, state: FSMContext) -> None:
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Пока что дневной план закрыт.\n\n"
            "Сначала пройди квиз — после него я открою тебе цель, недельный маршрут и кнопку дня 👇",
            reply_markup=start_keyboard(WEB_APP_URL),
        )
        return

    user = await database.ensure_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not user:
        await message.answer("❌ Не удалось подготовить твой профиль. Попробуй еще раз чуть позже.")
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await message.answer(
            "🎯 Сначала зафиксируй большую цель на 30 дней.\n\n"
            "Без нее мы не сможем собрать сильный день, который реально двигает тебя вперед."
        )
        return

    today = datetime.now().date().isoformat()
    today_lock = await cache.get_data(cache.KeyManager.get_day_plan_lock_key(message.from_user.id, today))
    today_tasks = await database.get_today_tasks(user["id"], today)

    if today_tasks or today_lock:
        tasks_text = "\n".join(
            f"{idx}. {task.get('task_text', '')}" for idx, task in enumerate(today_tasks[:3], 1)
        ) or "Пока задачи не найдены в базе, но дневной слот уже зафиксирован."
        await message.answer(
            "📅 <b>Твой день уже собран.</b>\n\n"
            "На сегодня у тебя зафиксированы такие задачи:\n"
            f"{tasks_text}\n\n"
            "Сейчас не нужно перепридумывать день заново.\n"
            "Когда будешь готов — вернись и сдай отчет 📤",
            reply_markup=private_hub_reply_keyboard(),
        )
        if CLUB_GROUP_URL:
            await message.answer(
                "Если хочешь продолжить уже в группе, вот быстрый переход 👇",
                reply_markup=back_to_group_keyboard(CLUB_GROUP_URL),
            )
        return

    milestones = active_goal.get("milestones") or []
    week_hint = milestones[0] if milestones else "выбери 3 действия, которые реально двигают тебя к месячной цели"

    await state.clear()
    await state.set_state(TaskStates.waiting_day_tasks)
    await state.update_data(day_goal_id=active_goal["id"])
    await _answer_private_with_actions(
        message,
        "📅 <b>Мой день (до 3х задач)</b>\n\n"
        "Теперь превращаем большую цель в действия на сегодня.\n\n"
        "Что важно:\n"
        "• максимум <b>3 задачи</b>\n"
        "• каждая задача — отдельной строкой\n"
        "• задачи должны быть конкретными, чтобы вечером ты честно понял, сделал или нет\n\n"
        f"Подсказка по твоему недельному фокусу:\n<i>{week_hint}</i>\n\n"
        "Отправь <b>3 задачи</b> одним сообщением, каждую с новой строки 👇",
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Если пока не хочешь собирать день — можешь вернуться в группу 👇",
    )


@router.message(CommandStart())
async def cmd_start(
    message: types.Message,
    command: CommandObject | None = None,
    state: FSMContext | None = None,
) -> None:
    """Handle /start in both private chats and groups."""
    user_id = message.from_user.id

    try:
        args = (command.args or "").strip() if command else ""
        if message.chat.type != "private":
            me = await message.bot.get_me()
            await message.answer(
                "👋 Это <b>LedoLab Business Club</b>.\n\n"
                "В группе ты работаешь с меню и отчетами.\n"
                "А личка нужна для настройки цели и спокойной сборки дня.\n\n"
                "Если нужно — открой личку бота кнопкой ниже 👇",
                reply_markup=open_bot_keyboard(me.username, "start", "🤖 ОТКРЫТЬ БОТА В ЛИЧКЕ"),
            )
            return

        await _delete_private_message_safely(message)

        if args == "goal_setup" and state:
            await _start_goal_flow(message, state)
            return

        if args == "day_setup" and state:
            await _start_day_flow(message, state)
            return

        has_quiz = await database.has_completed_quiz(user_id)
        if has_quiz:
            me = await message.bot.get_me()
            await message.answer(
                "🔥 <b>Ты уже внутри LedoLab Business Club.</b>\n\n"
                "Если готов продолжать движение — открывай меню и работай по шагам.\n"
                "Если нужен большой маршрут — начни с цели на 30 дней.\n"
                "Если нужен конкретный фокус на сегодня — переходи в день.",
                reply_markup=private_hub_reply_keyboard(),
            )
            await message.answer(
                "Ниже у тебя теперь есть быстрые кнопки-напоминания.\n"
                "А если нужен старый inline-вариант меню — он тоже под рукой 👇",
                reply_markup=club_main_menu(me.username, is_private=True),
            )
            return

        welcome_text = (
            "🚀 <b>LedoLab Business Club</b>\n\n"
            "Это не чат мотивации и не очередная папка с советами.\n"
            "Это среда, где предприниматели каждый день показывают реальное действие.\n\n"
            "Сначала пройди короткий квиз.\n"
            "Он поможет нам понять твой уровень и точнее провести тебя дальше 👇"
        )
        await message.answer(welcome_text, reply_markup=start_keyboard(WEB_APP_URL))
        logger.info(f"New user: {user_id}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.answer("❌ Что-то пошло не так. Попробуй еще раз чуть позже.")


@router.message(F.text == "🎯 Моя цель 30 дней")
async def show_30_day_goal(message: types.Message) -> None:
    """Show the saved 30-day goal as a reminder."""
    await _delete_private_message_safely(message)
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз. После него я смогу показать тебе цель и весь маршрут 👇",
            reply_markup=start_keyboard(WEB_APP_URL),
        )
        return

    user = await database.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала пройди стартовый путь в боте, чтобы мы могли сохранить твою цель.")
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await message.answer("Пока цели на 30 дней нет. Нажми `🎯 Моя цель (30 дней)` и мы соберем ее вместе.")
        return

    await message.answer(
        "🎯 <b>Твоя цель на 30 дней</b>\n\n"
        f"{active_goal.get('goal_text', '')}\n\n"
        "Держи ее перед глазами и не распыляйся. Большой результат всегда начинается с ясного фокуса 🔥",
        reply_markup=private_hub_reply_keyboard(),
    )


@router.message(F.text == "📅 Мой план на 7 дней")
@router.message(F.text == "📅 Мой план на 5 дней")
async def show_7_day_plan(message: types.Message) -> None:
    """Show the saved weekly plan as a reminder."""
    await _delete_private_message_safely(message)
    if not await database.has_completed_quiz(message.from_user.id):
        await message.answer(
            "🧭 Сначала пройди квиз. Потом я покажу тебе и большую цель, и план на 7 дней 👇",
            reply_markup=start_keyboard(WEB_APP_URL),
        )
        return

    user = await database.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала пройди стартовый путь в боте, чтобы мы могли сохранить твой план.")
        return

    active_goal = await database.get_active_goal(user["id"])
    if not active_goal:
        await message.answer("Пока 7-дневный план не собран. Начни с `🎯 Моя цель (30 дней)`.")
        return

    milestones = active_goal.get("milestones") or []
    if not milestones:
        await message.answer("Пока не вижу сохраненного плана на 7 дней. Давай соберем его заново через цель.")
        return

    lines = ["📅 <b>Твой план на 7 дней</b>\n"]
    for idx, milestone in enumerate(milestones, 1):
        lines.append(f"{idx}. {milestone}")
    lines.extend(
        [
            "",
            "Вот твой ближайший маршрут.\nНе надо помнить все в голове — просто возвращайся сюда и сверяй направление 💡",
        ]
    )
    await message.answer("\n".join(lines), reply_markup=private_hub_reply_keyboard())


@router.message(F.text == "📌 Мой день (до 3х задач)")
async def show_or_start_day(message: types.Message, state: FSMContext) -> None:
    """Entry point from reply keyboard to today's 3-task flow."""
    await _delete_private_message_safely(message)
    await _start_day_flow(message, state)


@router.message(GoalStates.waiting_goal_text)
async def handle_goal_text(message: types.Message, state: FSMContext) -> None:
    """Save the main 30-day goal in FSM only until user confirms it."""
    goal_text = (message.text or "").strip()
    if len(goal_text) < 5:
        await message.answer("🤏 Напиши цель чуть конкретнее, чтобы было понятно, к чему ты идешь.")
        return

    await state.update_data(goal_text=goal_text, milestones=[], editing_day=None)
    await state.set_state(GoalStates.waiting_day_text)
    await _answer_private_with_actions(
        message,
        "🔥 <b>Отлично. Большую цель зафиксировали.</b>\n\n"
        "Теперь не пытаемся расписать весь месяц сразу.\n"
        "Сейчас собираем <b>7 ближайших дней</b> — это не мелкие таски, а понятные дневные фокусы.\n\n"
        "Нажми кнопку ниже, и мы спокойно начнем с первого дня 👇",
        inline_markup=goal_day_step_keyboard(1),
    )


@router.callback_query(GoalStates.waiting_day_text, F.data.startswith("goal_day:"))
@router.callback_query(GoalStates.reviewing, F.data.startswith("goal_day:"))
async def open_goal_day_step(query: types.CallbackQuery, state: FSMContext) -> None:
    """Open a specific 7-day milestone step."""
    day_number = int(query.data.split(":")[1])
    data = await state.get_data()
    milestones = data.get("milestones", [])
    is_editing = len(milestones) >= day_number

    await state.update_data(editing_day=day_number)
    await state.set_state(GoalStates.editing_day if is_editing else GoalStates.waiting_day_text)

    prompts = {
        1: "📍 <b>День 1</b>\n\nНапиши главный фокус на первый день.\nЭто не список из 10 дел, а один сильный вектор, который реально запускает движение.",
        2: "📍 <b>День 2</b>\n\nОтлично, первый шаг есть.\nТеперь напиши фокус на второй день — что должно быть сделано, чтобы движение продолжилось?",
        3: "📍 <b>День 3</b>\n\nХорошо идем 🔥\nСейчас нужен главный фокус на третий день.",
        4: "📍 <b>День 4</b>\n\nУже появляется настоящий маршрут, а не просто желание.\nНапиши цель на четвертый день 👇",
        5: "📍 <b>День 5</b>\n\nСупер. Чем яснее маршрут, тем легче реально дойти до результата.\nНапиши фокус на пятый день.",
        6: "📍 <b>День 6</b>\n\nТы уже почти собрал недельный спринт.\nНапиши главную цель на шестой день 👇",
        7: "📍 <b>День 7</b>\n\nФинальный штрих недели.\nЗафиксируй седьмой день, и я покажу тебе весь маршрут целиком для проверки.",
    }
    await _answer_private_with_actions(
        query,
        prompts.get(day_number, "Напиши фокус дня 👇"),
        inline_markup=back_to_group_keyboard(CLUB_GROUP_URL) if CLUB_GROUP_URL else None,
        inline_text="Если хочешь прерваться — вернуться в группу можно здесь 👇",
    )
    await query.answer()


@router.message(GoalStates.waiting_day_text)
@router.message(GoalStates.editing_day)
async def save_goal_day_text(message: types.Message, state: FSMContext) -> None:
    """Save or edit one of the seven day focuses."""
    day_text = (message.text or "").strip()
    if len(day_text) < 3:
        await message.answer("🤏 Напиши чуть подробнее, чтобы фокус дня был понятным и конкретным.")
        return

    data = await state.get_data()
    day_number = int(data.get("editing_day") or 1)
    milestones = list(data.get("milestones", []))

    while len(milestones) < day_number:
        milestones.append("")
    milestones[day_number - 1] = day_text

    await state.update_data(milestones=milestones)

    if day_number < 7 and all(milestones[:day_number]):
        await state.update_data(editing_day=None)
        await state.set_state(GoalStates.waiting_day_text)
        await _answer_private_with_actions(
            message,
            f"✅ <b>{day_number}-й день сохранен.</b>\n\n"
            "Идем дальше спокойно, шаг за шагом 👇",
            inline_markup=goal_day_step_keyboard(day_number + 1),
        )
        return

    if all(milestones[:7]) and len(milestones) >= 7:
        await state.update_data(editing_day=None)
        await state.set_state(GoalStates.reviewing)
        await _show_goal_review(message, state)
        return

    next_missing = next((idx for idx, value in enumerate(milestones, 1) if not value), day_number + 1)
    await state.update_data(editing_day=None)
    await state.set_state(GoalStates.waiting_day_text)
    await _answer_private_with_actions(
        message,
        "✅ День сохранен. Продолжаем 👇",
        inline_markup=goal_day_step_keyboard(next_missing),
    )


@router.callback_query(GoalStates.reviewing, F.data == "goal_edit")
async def edit_goal_days(query: types.CallbackQuery, state: FSMContext) -> None:
    """Open selective editing for one of the 7 days."""
    await _answer_private_with_actions(
        query,
        "✏️ Выбери день, который хочешь поправить.\n\n"
        "Тебе не нужно переписывать все заново — можно изменить только то, что реально хочется улучшить 👇",
        inline_markup=goal_edit_days_keyboard(),
    )
    await query.answer()


@router.callback_query(GoalStates.reviewing, F.data == "goal_confirm")
async def confirm_goal_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    """Persist the goal and post the plan to the group after final confirmation."""
    data = await state.get_data()
    goal_text = data.get("goal_text", "").strip()
    milestones = [item.strip() for item in data.get("milestones", []) if item.strip()]
    if not goal_text or len(milestones) < 7:
        await query.answer("Не хватает данных для сохранения.", show_alert=True)
        return

    user = await database.ensure_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not user:
        await query.answer("Не удалось сохранить цель.", show_alert=True)
        return

    saved_goal = await database.set_active_goal(user["id"], goal_text, milestones)
    if not saved_goal:
        await query.answer("Не удалось сохранить цель в базе.", show_alert=True)
        return

    await cache.set_data(cache.KeyManager.get_goal_lock_key(query.from_user.id), goal_text, ex=30 * 24 * 60 * 60)
    for day_number, milestone in enumerate(milestones, 1):
        await cache.set_data(
            cache.KeyManager.get_goal_day_lock_key(query.from_user.id, day_number),
            milestone,
            ex=7 * 24 * 60 * 60,
        )

    if REPORTS_GROUP_ID:
        user_name = query.from_user.full_name or query.from_user.first_name or "Участник"
        group_text_lines = [
            "🔥 <b>Новый предприниматель зашел в игру всерьез</b>\n",
            f"<b>{user_name}</b> только что собрал свой маршрут в <b>LedoLab Business Club</b>.",
            "",
            "🎯 <b>Цель на 30 дней:</b>",
            goal_text,
            "",
            "📅 <b>Фокус на ближайшие 7 дней:</b>",
        ]
        for idx, milestone in enumerate(milestones, 1):
            group_text_lines.append(f"{idx}. {milestone}")
        group_text_lines.extend(
            [
                "",
                "Вот это уже не просто «хочу».\nВот это — маршрут к результату 💪",
                "",
                "Поддержите его огнем в комментариях и реакциях 🔥",
            ]
        )
        try:
            await query.bot.send_message(REPORTS_GROUP_ID, "\n".join(group_text_lines))
        except Exception as exc:
            logger.error("Failed to post goal to group: %s", exc, exc_info=True)

    me = await query.bot.get_me()
    await _answer_private_with_actions(
        query,
        "🚀 <b>Готово. Твоя большая цель и 7-дневный маршрут зафиксированы.</b>\n\n"
        "Теперь у тебя есть не просто желание, а понятный план движения.\n\n"
        "Если готов уже <b>сегодня</b> начать выполнять поставленные цели — нажимай кнопку\n"
        "<b>📅 Мой день (до 3х задач)</b>.\n\n"
        "Если пока не готов — просто вернись в группу и продолжишь позже.",
        inline_markup=after_goal_confirm_keyboard(me.username, CLUB_GROUP_URL),
    )
    await state.clear()
    await query.answer("Цели подтверждены ✅")
