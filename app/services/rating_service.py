"""
Service layer for public LedoScore leaderboard.
"""

import logging
from html import escape
from typing import Any, Dict, List, Optional

from app import cache, database

logger = logging.getLogger(__name__)


async def _attach_streaks(users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for user in users:
        telegram_id = user.get("telegram_id")
        streak = 0
        if telegram_id:
            streak = int((await cache.get_data(cache.KeyManager.get_streak_key(int(telegram_id)))) or 0)
        enriched.append({**user, "streak": streak})
    enriched.sort(key=lambda item: (int(item.get("total_score", 0)), int(item.get("streak", 0))), reverse=True)
    return enriched


async def get_rating_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    try:
        users = await database.get_top_users(500)
        users = await _attach_streaks(users)
        logger.info("✅ Rating generated: %s users", len(users))
        return users[:limit]
    except Exception as e:
        logger.error(f"Error getting rating: {e}", exc_info=True)
        return []


async def get_period_leaderboard(start_iso: str, end_iso: str, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        users = await database.get_top_users_for_period(start_iso, end_iso, limit=500)
        users = await _attach_streaks(users)
        return users[:limit]
    except Exception as e:
        logger.error(f"Error getting period rating {start_iso}..{end_iso}: {e}", exc_info=True)
        return []


async def get_user_rating_position(telegram_id: int) -> Optional[Dict[str, Any]]:
    try:
        users = await database.get_top_users(500)
        users = await _attach_streaks(users)
        for idx, user in enumerate(users, 1):
            if int(user.get("telegram_id") or 0) == telegram_id:
                return {
                    "place": idx,
                    "total_score": int(user.get("total_score", 0)),
                    "streak": int(user.get("streak", 0)),
                }
        return None
    except Exception as e:
        logger.error(f"Error getting user rating position {telegram_id}: {e}", exc_info=True)
        return None


def _display_label(user: Dict[str, Any]) -> str:
    username = user.get("username")
    first_name = user.get("first_name") or "Участник"
    label = f"@{username}" if username else str(first_name)
    return escape(str(label))


def _streak_progress(streak: int) -> tuple[int, str]:
    """Position (1-5) within the current 5-day route cycle, plus a fill bar."""
    position = ((streak - 1) % 5) + 1 if streak > 0 else 0
    bar = "🟩" * position + "⬜" * (5 - position)
    return position, bar


async def format_rating_text(users: List[Dict[str, Any]], viewer_telegram_id: Optional[int] = None) -> str:
    if not users:
        return "🏆 Рейтинг LedoLab Business Club\n\nПока в рейтинге еще нет участников."

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 Рейтинг LedoLab Business Club\n"]

    top_three = users[:3]
    for idx, user in enumerate(top_three, 1):
        streak = int(user.get("streak", 0))
        position, bar = _streak_progress(streak)
        lines.extend(
            [
                f"{medals[idx - 1]} {idx} место — {_display_label(user)}",
                f"LedoScore: {int(user.get('total_score', 0))} ⭐️",
                f"Streak 🔥 {position}/5 дней",
                bar,
                "",
            ]
        )

    if viewer_telegram_id:
        viewer_row = None
        for idx, user in enumerate(users, 1):
            if int(user.get("telegram_id") or 0) == viewer_telegram_id:
                viewer_row = (idx, user)
                break
        if viewer_row and viewer_row[0] > 3:
            place, user = viewer_row
            streak = int(user.get("streak", 0))
            position, bar = _streak_progress(streak)
            lines.extend(
                [
                    "—",
                    f"Твое место: {place}",
                    f"Твой LedoScore: {int(user.get('total_score', 0))} ⭐️",
                    f"Твой Streak 🔥 {position}/5 дней",
                    bar,
                ]
            )

    return "\n".join(line for line in lines if line is not None).strip()
