"""
Service layer for daily task management.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from app import database, cache

logger = logging.getLogger(__name__)


async def set_daily_task(
    user_id: int,
    task_text: str,
    today: str,
) -> Optional[Dict[str, Any]]:
    """
    Set a daily task for the user.
    
    Args:
        user_id: User database ID
        task_text: Task description
        today: Date in YYYY-MM-DD format
        
    Returns:
        Task data or None
    """
    try:
        task = await database.create_task(user_id, task_text, today)
        
        if task:
            # Cache task for quick access
            await cache.set_data(
                cache.KeyManager.get_task_key(user_id, today),
                task_text,
                ex=86400,
            )
            logger.info(f"✅ Task set: {user_id} on {today}")
            return task
        
        return None
    except Exception as e:
        logger.error(f"Error setting task {user_id}: {e}", exc_info=True)
        return None


async def get_today_task(user_id: int, today: str) -> Optional[Dict[str, Any]]:
    """
    Get today's task if it exists.
    
    Args:
        user_id: User database ID
        today: Date in YYYY-MM-DD format
        
    Returns:
        Task data or None
    """
    try:
        task = await database.get_today_task(user_id, today)
        return task
    except Exception as e:
        logger.error(f"Error getting task {user_id}: {e}", exc_info=True)
        return None


async def task_summary_text(task_data: Dict[str, Any]) -> str:
    """
    Generate task confirmation message.
    
    Args:
        task_data: Task record
        
    Returns:
        Formatted text
    """
    task_text = task_data.get("task_text", "")
    
    return (
        f"◆ Задача зафиксирована\n\n"
        f"Сегодняшний фокус:\n"
        f'"{task_text}"\n\n'
        f"Вечером вернись и сдай отчет.\n"
        f"Нужен результат, а не идеальность."
    )
