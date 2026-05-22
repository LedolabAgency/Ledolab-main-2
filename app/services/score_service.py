"""
Service layer for Leda Score management.
"""

import logging
from typing import Optional
from app import database

logger = logging.getLogger(__name__)


async def get_user_total_score(user_id: int) -> int:
    """
    Get user's total Leda Score.
    
    Args:
        user_id: User database ID
        
    Returns:
        Total score
    """
    try:
        total = await database.get_user_total_score(user_id)
        logger.debug(f"User {user_id} total score: {total}")
        return total
    except Exception as e:
        logger.error(f"Error getting score {user_id}: {e}", exc_info=True)
        return 0


async def format_score_display(score: int) -> str:
    """
    Format score for display with visual indicator.
    
    Args:
        score: User's score
        
    Returns:
        Formatted score text
    """
    if score >= 500:
        indicator = "🔥🔥🔥"
    elif score >= 300:
        indicator = "🔥🔥"
    elif score >= 100:
        indicator = "🔥"
    else:
        indicator = "⚡"
    
    return f"{indicator} {score} Business Score"
