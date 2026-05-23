"""
Group business club handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from app import database
from app.config import (
    CLUB_GROUP_URL,
    REPORTS_GROUP_ID,
)
from app.keyboards.inline.start import club_group_keyboard, club_main_menu, open_private_flow_keyboard, report_count_keyboard
from app.services import rating_service, report_service, task_service
from app.states.quiz import ReportStates, TaskStates

logger = logging.getLogger(__name__)
router = Router()


def _today() -> str:
    return datetime.now().date().isoformat()


async def _ensure_group_interaction(event_message: types.Message) -> bool:
    if event_message.chat.type == "private":
        await event_message.answer(
            "Рабочие действия доступны только в группе LedoLab Business To-Do Club.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        return False
    return True


async def _ensure_group_callback(query: types.CallbackQuery) -> bool:
    if query.message.chat.type == "private":
        await query.message.answer(
            "Рабочие действия доступны только в группе LedoLab Business To-Do Club.",
            reply_markup=club_group_keyboard(CLUB_GROUP_URL),
        )
        await query.answer()
        return False
    return True


async def _ensure_quiz_for_query(query: types.CallbackQuery) -> bool:
    if await database.has_completed_quiz(query.from_user.id):
        return True

    me = await query.bot.get_me()
    await query.message.answer(
        "🧭 Сначала пройди квиз в личке бота.\n\n"
        "Пока квиз не пройден, рабочие кнопки клуба закрыты 👇",
        reply_markup=open_private_flow_keyboard(me.username, "onboarding", "ПРОЙТИ КВИЗ В ЛИЧКЕ"),
    )
    await query.answer()
    return False


async def _ensure_quiz_for_message(message: types.Message) -> bool:
    if await database.has_completed_quiz(message.from_user.id):
        return True

    me = await message.bot.get_me()
    await message.answer(
        "🧭 Сначала пройди квиз в личке бота.\n\n"
        "Пока квиз не пройден, рабочие кнопки клуба закрыты 👇",
        reply_markup=open_private_flow_keyboard(me.username, "onboarding", "ПРОЙТИ КВИЗ В ЛИЧКЕ"),
    )
    return False


@router.callback_query(F.data == "rules_view")
async def view_rules(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    me = await query.bot.get_me()
    text = (
        "📘 Как работает LedoLab Business To-Do Club\n\n"
        "1. Ставишь 1 цель на 30 дней.\n"
        "2. Разбиваешь ее на 5 рабочих дней недели.\n"
        "3. Каждый день фиксируешь 3 задачи.\n"
        "4. Вечером сдаешь отчет и получаешь баллы.\n"
        "5. Лучшие участники поднимаются в рейтинге и получают доступ к призам."
    )
    await query.message.edit_text(text, reply_markup=club_main_menu(me.username))
    await query.answer()


@router.callback_query(F.data == "goal_view")
async def start_goal_flow(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    me = await query.bot.get_me()
    await query.message.answer(
        "Цель на 30 дней задается в личке с ботом.",
        reply_markup=open_private_flow_keyboard(
            me.username,
            "goal_setup",
            "ОТКРЫТЬ ЦЕЛЬ В ЛИЧКЕ",
        ),
    )
    await query.answer()


@router.callback_query(F.data == "day_view")
async def open_day_view(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    me = await query.bot.get_me()
    await query.message.answer(
        "Собрать день лучше в личке, чтобы ничего не терялось и весь рабочий путь был в одном месте 👇",
        reply_markup=open_private_flow_keyboard(
            me.username,
            "day_setup",
            "ОТКРЫТЬ МОЙ ДЕНЬ В ЛИЧКЕ",
        ),
    )
    await query.answer()


@router.message(TaskStates.waiting_day_tasks)
async def save_day_tasks(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
        await state.clear()
        return
    if not await _ensure_quiz_for_message(message):
        await state.clear()
        return

    me = await message.bot.get_me()
    raw_tasks = [line.strip("-• \t") for line in message.text.splitlines() if line.strip()]
    if len(raw_tasks) != 3:
        await message.answer("Нужно отправить ровно 3 задачи. Каждую задачу с новой строки.")
        return

    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить профиль участника. Попробуй позже.")
        await state.clear()
        return

    active_goal = await database.get_active_goal(club_user["id"])
    for idx, task_text in enumerate(raw_tasks, 1):
        await task_service.set_daily_task(
            user_id=club_user["id"],
            task_text=task_text,
            today=_today(),
            task_type=f"day_{idx}",
            goal_id=active_goal["id"] if active_goal else None,
        )

    await message.answer(
        "📅 День зафиксирован.\n\nТвои 3 задачи сохранены. Вечером возвращайся и сдавай отчет.",
        reply_markup=club_main_menu(me.username),
    )
    await state.clear()


@router.callback_query(F.data == "report_submit")
async def start_report_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return
    me = await query.bot.get_me()
    await query.message.answer(
        "Отчет теперь тоже сдается в личке бота — так безопаснее для данных и удобнее для пользователя 👇",
        reply_markup=open_private_flow_keyboard(
            me.username,
            "report_setup",
            "ОТКРЫТЬ ОТЧЕТ В ЛИЧКЕ",
        ),
    )
    await query.answer()


@router.callback_query(F.data.startswith("report_count:"))
async def capture_report_count(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    completed_count = int(query.data.split(":", 1)[1])
    await state.update_data(completed_count=completed_count)
    await state.set_state(ReportStates.waiting_report_text)
    await query.message.answer(
        "Отправь короткий отчет:\n— что сделал\n— какой результат\n— что дальше"
    )
    await query.answer()


@router.message(ReportStates.waiting_report_text)
async def save_report_text(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
        await state.clear()
        return
    if not await _ensure_quiz_for_message(message):
        await state.clear()
        return

    await state.update_data(report_text=message.text.strip())
    await state.set_state(ReportStates.waiting_proof)
    await message.answer(
        "Теперь отправь daily proof.\n\nНа MVP можно прислать кружок, видео или короткий текст-подтверждение."
    )


@router.message(ReportStates.waiting_proof, F.video | F.video_note | F.text)
async def finish_report_flow(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
        await state.clear()
        return
    if not await _ensure_quiz_for_message(message):
        await state.clear()
        return

    me = await message.bot.get_me()
    data = await state.get_data()
    club_user = await database.ensure_club_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language_code=message.from_user.language_code or "ru",
    )
    if not club_user:
        await message.answer("Не удалось подготовить профиль участника. Попробуй позже.")
        await state.clear()
        return

    proof_type = "text"
    file_id = None
    if message.video_note:
        proof_type = "video"
        file_id = message.video_note.file_id
    elif message.video:
        proof_type = "video"
        file_id = message.video.file_id

    proof_text = data.get("report_text", "")
    if message.text and message.text != proof_text:
        proof_text = f"{proof_text}\n\nProof: {message.text}".strip()

    task_ids = data.get("task_ids", [])
    report = await report_service.submit_report(
        user_id=club_user["id"],
        task_id=task_ids[0],
        report_text=proof_text,
        completed_tasks=data.get("completed_count", 0),
        proof_type=proof_type,
        file_id=file_id,
    )
    if not report:
        await message.answer("Не удалось сохранить отчет. Попробуй еще раз.")
        await state.clear()
        return

    await database.update_tasks_status(task_ids, "reported")

    score = report["score_awarded"]
    mood = "🔥 Сильный день" if score >= 40 else "🔥 Хороший день" if score >= 20 else "🔥 Движение есть"

    summary = await report_service.report_summary_text(
        username=message.from_user.username,
        task_text="\n".join(f"— {item}" for item in data.get("task_texts", [])),
        report_text=proof_text,
        score=score,
    )
    target_chat_id = REPORTS_GROUP_ID or message.chat.id
    await message.bot.send_message(target_chat_id, summary)
    await message.answer(
        f"Отчет принят.\n\nБаллы начислены: +{score}\n{mood}",
        reply_markup=club_main_menu(me.username),
    )
    await state.clear()


@router.callback_query(F.data == "rating_view")
async def show_rating(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return
    if not await _ensure_quiz_for_query(query):
        return

    me = await query.bot.get_me()
    users = await rating_service.get_rating_leaderboard()
    text = await rating_service.format_rating_text(users)
    await query.message.edit_text(text, reply_markup=club_main_menu(me.username))
    await query.answer()
