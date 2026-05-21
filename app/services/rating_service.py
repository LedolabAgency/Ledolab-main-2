"""
Service layer for rating and leaderboard.
"""

import logging
from typing import List, Dict, Any
from app import database

logger = logging.getLogger(__name__)


async def get_rating_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get top users for rating display.
    
    Args:
        limit: Number of top users
        
    Returns:
        List of users with scores
    """
    try:
        users = await database.get_top_users(limit)
        logger.info(f"✅ Rating generated: {len(users)} users")
        return users
    except Exception as e:
        logger.error(f"Error getting rating: {e}", exc_info=True)
        return []


async def format_rating_text(users: List[Dict[str, Any]]) -> str:
    """
    Format rating as readable text.
    
    Args:
        users: List of users with scores
        
    Returns:
        Formatted rating text
    """
    if not users:
        return "🏆 ТОП предпринимателей Leda.lab\n\nПока нет участников в рейтинге."
    
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 ТОП предпринимателей Leda.lab\n"]
    
    for idx, user in enumerate(users[:10], 1):
        medal = medals[idx - 1] if idx <= 3 else f"{idx}."
        username = user.get("username") or user.get("first_name") or "Участник"
        score = user.get("total_score", 0)
        
        lines.append(f"{medal} @{username} — {score} ⚡")
    
    return "\n".join(lines)
