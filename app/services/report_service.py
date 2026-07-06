"""
Service layer for daily report submission, public moderation, and admin review.
"""

from __future__ import annotations

import logging
from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional

from aiogram import types

from app import cache, database

logger = logging.getLogger(__name__)

DAILY_REPORT_SCORE = 30
SUSPICIOUS_FLAGS_THRESHOLD = 3
WARNING_SCORE_PENALTY = 15
STREAK_BONUSES = {
    3: 10,
    5: 25,
}


def _week_window(now: datetime) -> tuple[datetime, datetime]:
    """Current club week — delegates to the single source of truth in cache."""
    return cache.club_week_window(now)


def report_task_prompt(task_number: int, task_text: str) -> str:
    return (
        f"📌 Задача {task_number}\n"
        f"{escape(str(task_text))}\n\n"
        "Теперь пришли доказательство по этой задаче.\n"
        "Лучше всего — кружок или видео с записью экрана.\n"
        "Если нужно, можно добавить фото."
    )


def report_intro_text(task_texts: List[str]) -> str:
    lines = [
        "📤 Давай спокойно сдадим отчет за сегодня, чтобы зафиксировать день и получить LedoScore.\n",
        "Вот твои задачи на день:",
    ]
    for idx, task in enumerate(task_texts, 1):
        lines.append(f"{idx}. {escape(str(task))}")
    lines.extend(
        [
            "",
            "Теперь запиши один кружочек с полным отчетом сразу по всем задачам.",
            "Важно: кружочек в Telegram длится до 1 минуты, поэтому говори коротко и по делу.",
            "",
            "После записи я покажу тебе превью и дам выбрать: подтвердить или заменить.",
            "",
            "⏳ У тебя есть 5 минут для сдачи отчета.",
        ]
    )
    return "\n".join(lines)


def task_proof_saved_keyboard(is_last: bool) -> types.InlineKeyboardMarkup:
    buttons = []
    if not is_last:
        buttons.append([types.InlineKeyboardButton(text="✅ Завершить и продолжить", callback_data="report_task_done")])
    else:
        buttons.append([types.InlineKeyboardButton(text="✅ Завершить задачу", callback_data="report_task_done")])
    buttons.append([types.InlineKeyboardButton(text="💬 Добавить комментарий", callback_data="report_task_comment")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


def task_comment_skip_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="⏭ Пропустить комментарий", callback_data="report_skip_comment")]]
    )


def report_preview_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Отправить отчет", callback_data="report_send")],
            [types.InlineKeyboardButton(text="✏️ Переделать отчет", callback_data="report_redo")],
        ]
    )


def group_report_vote_keyboard(report_id: str, ok_count: int = 0, flag_count: int = 0) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text=f"👍 Норм ({ok_count})", callback_data=f"report_vote:ok:{report_id}"),
                types.InlineKeyboardButton(text=f"❗️ Сомнительно ({flag_count})", callback_data=f"report_vote:flag:{report_id}"),
            ]
        ]
    )


def admin_review_keyboard(report_id: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Подтвердить отчет", callback_data=f"admin_report:approve:{report_id}")],
            [types.InlineKeyboardButton(text="⚠️ Сомнительно", callback_data=f"admin_report:reject:{report_id}")],
            [types.InlineKeyboardButton(text="💬 Вернуть с комментарием", callback_data=f"admin_report:comment:{report_id}")],
        ]
    )


def redo_report_keyboard(report_id: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🔁 Переделать отчет", callback_data=f"user_report:redo:{report_id}")],
            [types.InlineKeyboardButton(text="🚫 Забить болт", callback_data=f"user_report:drop:{report_id}")],
        ]
    )


def render_report_preview(entries: List[Dict[str, Any]]) -> str:
    lines = ["Проверь отчет перед отправкой:\n"]
    if entries:
        entry = entries[0]
        lines.append("✅ Кружочек с отчетом записан")
        comment = (entry.get("comment_text") or "").strip()
        if comment:
            lines.append(f"💬 Комментарий: {escape(comment)}")
        lines.append("")
    lines.append("Если все ок — подтверждай.")
    return "\n".join(lines)


def build_group_summary(
    username: Optional[str],
    entries: List[Dict[str, Any]],
    *,
    score_awarded: Optional[int] = None,
    current_streak: Optional[int] = None,
    total_ledoscore: Optional[int] = None,
) -> str:
    author = f"@{username}" if username else "Участник клуба"
    safe_author = escape(str(author))
    lines = [f"{safe_author}\n", "📤 Отчет за день:\n"]
    if entries:
        entry = entries[0]
        task_lines = entry.get("task_lines") or []
        if task_lines:
            lines.append("Задачи:")
            for idx, task in enumerate(task_lines, 1):
                lines.append(f"{idx}. {escape(str(task or ''))}")
            lines.append("")
        lines.append("🎥 Кружочек с отчетом — в сообщении выше")
        comment = (entry.get("comment_text") or "").strip()
        if comment:
            lines.append(f"💬 {escape(comment)}")
    if score_awarded is not None or current_streak is not None or total_ledoscore is not None:
        lines.append("")
        lines.append("📊 LedoScore:")
        if score_awarded is not None:
            lines.append(f"За этот отчет: +{int(score_awarded)}")
        if current_streak is not None:
            lines.append(f"Текущий стрик: {int(current_streak)} дн.")
        if total_ledoscore is not None:
            lines.append(f"Общий баланс: {int(total_ledoscore)}")
    lines.append("")
    lines.append("Отчет отправлен в клуб.")
    return "\n".join(lines)


def build_admin_summary(user_label: str, goal_text: str, entries: List[Dict[str, Any]], flags: int) -> str:
    lines = [
        "⚠️ Нужен ручной чек отчета\n",
        f"Участник: {escape(str(user_label or 'Участник'))}",
    ]
    if goal_text:
        lines.append(f"Цель: {escape(str(goal_text))}")
    lines.append(f"Флаги: {escape(str(flags))}\n")
    for idx, entry in enumerate(entries, 1):
        lines.append(f"{idx}. {escape(str(entry['task_text']))}")
        comment = (entry.get("comment_text") or "").strip()
        if comment:
            lines.append(f"   💬 {escape(comment)}")
    return "\n".join(lines)


def build_admin_approved_summary(original_text: str) -> str:
    return original_text + "\n\n✅ Отчет проверен админом — все ок."


def build_admin_rejected_summary(original_text: str) -> str:
    return original_text + "\n\n❌ Отчет отклонён админом — баллы сняты."


def build_admin_returned_summary(original_text: str) -> str:
    return original_text + "\n\n💬 Отчет возвращён админом на переделку."


def _extract_proof_file_ids(entries: List[Dict[str, Any]]) -> List[str]:
    file_ids: List[str] = []
    for entry in entries:
        for key in ("file_id", "proof_file_id", "video_id", "video_note_file_id"):
            value = str(entry.get(key) or "").strip()
            if value:
                file_ids.append(value)
    return file_ids


def _has_forwarded_proof(entries: List[Dict[str, Any]]) -> bool:
    for entry in entries:
        if entry.get("forward_from") or entry.get("forward_date") or entry.get("forward_origin"):
            return True
    return False


async def save_daily_report(
    user_id: str,
    telegram_id: int,
    username: Optional[str],
    report_date: str,
    entries: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Persist and immediately award the base daily score."""
    try:
        if _has_forwarded_proof(entries):
            logger.warning(
                "Rejected forwarded daily report proof: user_id=%s telegram_id=%s date=%s",
                user_id,
                telegram_id,
                report_date,
            )
            return None

        proof_file_ids = _extract_proof_file_ids(entries)
        if proof_file_ids:
            unique_proof_file_ids = list(dict.fromkeys(proof_file_ids))
            for proof_file_id in unique_proof_file_ids:
                if await database.has_report_file_for_user(user_id, proof_file_id):
                    logger.warning(
                        "Rejected duplicate daily report proof: user_id=%s telegram_id=%s date=%s file_id=%s",
                        user_id,
                        telegram_id,
                        report_date,
                        proof_file_id,
                    )
                    return None

        score_awarded = DAILY_REPORT_SCORE
        streak_key = cache.KeyManager.get_streak_key(telegram_id)
        last_report_key = cache.KeyManager.get_last_report_date_key(telegram_id)
        current_streak = int((await cache.get_data(streak_key)) or 0)
        last_report_date = await cache.get_data(last_report_key)

        if last_report_date == report_date:
            new_streak = max(current_streak, 1)
        else:
            report_dt = datetime.fromisoformat(report_date).date()
            if last_report_date:
                last_dt = datetime.fromisoformat(last_report_date).date()
                new_streak = current_streak + 1 if (report_dt - last_dt).days == 1 else 1
            else:
                new_streak = 1

        streak_bonus = STREAK_BONUSES.get(new_streak, 0)
        score_awarded += streak_bonus
        tasks_snapshot = [entry["task_text"] for entry in entries]
        summary_text = build_group_summary(username, entries)
        report = await database.create_or_update_daily_report(
            user_id=user_id,
            report_date=report_date,
            tasks_snapshot=tasks_snapshot,
            report_payload=entries,
            summary_text=summary_text,
            score_awarded=score_awarded,
            status="approved",
        )
        if not report:
            return None
        await database.award_score(user_id, score_awarded, f"Daily report submitted (streak {new_streak})")
        total_ledoscore = await database.get_user_total_score(user_id)
        await cache.set_data(streak_key, str(new_streak))
        await cache.set_data(last_report_key, report_date)
        summary_text = build_group_summary(
            username,
            entries,
            score_awarded=score_awarded,
            current_streak=new_streak,
            total_ledoscore=total_ledoscore,
        )
        await database.update_daily_report_summary_text(report["id"], summary_text)
        week_start, week_end = _week_window(datetime.now(cache.KYIV_TZ))
        weekly_ledoscore = await database.get_user_score_for_period(
            user_id, week_start.isoformat(), week_end.isoformat()
        )
        report["summary_text"] = summary_text
        report["current_streak"] = new_streak
        report["streak_bonus"] = streak_bonus
        report["total_ledoscore"] = total_ledoscore
        report["weekly_ledoscore"] = weekly_ledoscore
        return report
    except Exception as e:
        logger.error(f"Error saving daily report {user_id}: {e}", exc_info=True)
        return None


async def vote_on_report(report_id: str, voter_telegram_id: int, vote_type: str) -> Optional[Dict[str, Any]]:
    """Register a report vote and update flags if needed."""
    try:
        saved = await database.add_daily_report_vote(report_id, voter_telegram_id, vote_type)
        if not saved:
            return None

        ok_count = await database.count_daily_report_votes(report_id, "ok")
        flag_count = await database.count_daily_report_votes(report_id, "flag")
        report = await database.get_daily_report_by_id(report_id)
        if not report:
            return None

        await database.update_daily_report_flags(report_id, flag_count)
        if flag_count >= SUSPICIOUS_FLAGS_THRESHOLD:
            await database.set_daily_report_status(report_id, "suspicious")
            report["status"] = "suspicious"

        report["ok_count"] = ok_count
        report["flag_count"] = flag_count
        return report
    except Exception as e:
        logger.error(f"Error voting on report {report_id}: {e}", exc_info=True)
        return None
