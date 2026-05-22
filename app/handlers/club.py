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
    FAIL_DAY_SCORE,
    GOAL_SCORE,
    REPORTS_GROUP_ID,
    TASK_SCORE_EXTRA,
    TASK_SCORE_MAIN,
)
from app.keyboards.inline.start import club_group_keyboard, club_main_menu
from app.services import rating_service, report_service, task_service
from app.states.quiz import GoalStates, ReportStates, TaskStates

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


@router.callback_query(F.data == "rules_view")
async def view_rules(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return

    text = (
        "📘 Как работает LedoLab Business To-Do Club\n\n"
        "1. Утром ставишь 1 главную задачу на день.\n"
        "2. Вечером сдаешь отчет с доказательством результата.\n"
        "3. Двигаешься к одной цели на 30 дней.\n"
        "4. Получаешь Business Score за системность.\n"
        "5. Лучшие участники получают сопровождение от агентства."
    )
    await query.message.edit_text(text, reply_markup=club_main_menu())
    await query.answer()


@router.callback_query(F.data.in_({"task_set", "task_set_extra"}))
async def start_task_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return

    task_type = "extra" if query.data == "task_set_extra" else "main"
    prompt = (
        "Что ты сегодня делаешь, чтобы приблизиться к цели?\n\n"
        "Напиши 1 конкретное действие на сегодня."
        if task_type == "main"
        else "Какая дополнительная задача усилит твой день?\n\nНапиши 1 конкретное действие."
    )
    await state.set_state(TaskStates.waiting_task_text)
    await state.update_data(task_type=task_type)
    await query.message.answer(prompt)
    await query.answer()


@router.message(TaskStates.waiting_task_text)
async def save_task_text(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
        await state.clear()
        return

    data = await state.get_data()
    task_type = data.get("task_type", "main")
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
    task = await task_service.set_daily_task(
        user_id=club_user["id"],
        task_text=message.text,
        today=_today(),
        task_type=task_type,
        goal_id=active_goal["id"] if active_goal else None,
    )
    if not task:
        await message.answer("Не удалось сохранить задачу. Попробуй еще раз.")
        await state.clear()
        return

    points = TASK_SCORE_EXTRA if task_type == "extra" else TASK_SCORE_MAIN
    await database.award_score(
        club_user["id"],
        points,
        "Extra task set" if task_type == "extra" else "Daily task set",
    )
    await message.answer(await task_service.task_summary_text(task), reply_markup=club_main_menu())
    await state.clear()


@router.callback_query(F.data == "goal_view")
async def start_goal_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return

    await state.set_state(GoalStates.waiting_goal_text)
    await query.message.answer("Какая твоя цель на ближайшие 30 дней?")
    await query.answer()


@router.message(GoalStates.waiting_goal_text)
async def save_goal_text(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
        await state.clear()
        return

    await state.update_data(goal_text=message.text.strip())
    await state.set_state(GoalStates.waiting_milestones)
    await message.answer("Разбей цель на 5 этапов через запятую.")


@router.message(GoalStates.waiting_milestones)
async def save_goal_milestones(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
        await state.clear()
        return

    milestones = [item.strip() for item in message.text.split(",") if item.strip()]
    if len(milestones) < 3:
        await message.answer("Нужно минимум 3 этапа. Попробуй еще раз через запятую.")
        return

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

    goal = await database.set_active_goal(club_user["id"], data["goal_text"], milestones)
    if not goal:
        await message.answer("Не удалось сохранить цель. Попробуй еще раз.")
        await state.clear()
        return

    await database.award_score(club_user["id"], GOAL_SCORE, "30-day goal set")
    await message.answer(
        "🚀 Цель зафиксирована.\n\nТеперь каждый день ставь задачу так, чтобы она вела к одному из этапов.",
        reply_markup=club_main_menu(),
    )
    await state.clear()


@router.callback_query(F.data == "report_submit")
async def start_report_flow(query: types.CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_group_callback(query):
        return

    club_user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not club_user:
        await query.message.answer("Не удалось подготовить профиль участника. Попробуй позже.")
        await query.answer()
        return

    task = await database.get_task_by_type(club_user["id"], _today(), "main")
    if not task:
        await query.message.answer("Сначала поставь главную задачу на сегодня через кнопку «🎯 Поставить задачу».")
        await query.answer()
        return

    await state.set_state(ReportStates.waiting_report_text)
    await state.update_data(task_id=task["id"], task_text=task["task_text"])
    await query.message.answer(
        "Отправь короткий отчет:\n— что сделал\n— какой результат\n— что дальше"
    )
    await query.answer()


@router.message(ReportStates.waiting_report_text)
async def save_report_text(message: types.Message, state: FSMContext) -> None:
    if not await _ensure_group_interaction(message):
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

    report = await report_service.submit_report(
        user_id=club_user["id"],
        task_id=data["task_id"],
        report_text=proof_text,
        proof_type=proof_type,
        file_id=file_id,
    )
    if not report:
        await message.answer("Не удалось сохранить отчет. Попробуй еще раз.")
        await state.clear()
        return

    summary = await report_service.report_summary_text(
        username=message.from_user.username,
        task_text=data.get("task_text", ""),
        report_text=proof_text,
        score=report["score_awarded"],
    )
    target_chat_id = REPORTS_GROUP_ID or message.chat.id
    await message.bot.send_message(target_chat_id, summary)
    await message.answer("🔥 Отчет принят. Ты двигаешься, а не имитируешь движение.", reply_markup=club_main_menu())
    await state.clear()


@router.callback_query(F.data == "rating_view")
async def show_rating(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return

    users = await rating_service.get_rating_leaderboard()
    text = await rating_service.format_rating_text(users)
    await query.message.edit_text(text, reply_markup=club_main_menu())
    await query.answer()


@router.callback_query(F.data == "day_skip")
async def mark_rest_day(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return

    club_user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not club_user:
        await query.message.answer("Не удалось подготовить профиль участника. Попробуй позже.")
        await query.answer()
        return

    await database.mark_daily_status(club_user["id"], _today(), "rest")
    await query.message.answer("💤 День без фокуса зафиксирован. Завтра возвращайся в ритм.")
    await query.answer()


@router.callback_query(F.data == "day_fail")
async def mark_failed_day(query: types.CallbackQuery) -> None:
    if not await _ensure_group_callback(query):
        return

    club_user = await database.ensure_club_user(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        first_name=query.from_user.first_name,
        language_code=query.from_user.language_code or "ru",
    )
    if not club_user:
        await query.message.answer("Не удалось подготовить профиль участника. Попробуй позже.")
        await query.answer()
        return

    await database.mark_daily_status(club_user["id"], _today(), "fail")
    await database.award_score(club_user["id"], FAIL_DAY_SCORE, "Failed day")
    await query.message.answer("❌ День зафиксирован как слитый. Завтра нужно вернуться с действием.")
    await query.answer()
