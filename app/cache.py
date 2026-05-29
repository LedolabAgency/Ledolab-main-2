"""
Cache and Redis utilities for LedoLab.
Handles FSM storage, distributed locks, and caching.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
import redis.asyncio as redis
from app.config import REDIS_URL

logger = logging.getLogger(__name__)

# Global Redis client
redis_client: Optional[redis.Redis] = None


async def init_redis() -> redis.Redis:
    """
    Initialize Redis connection.
    
    Returns:
        redis.Redis: Async Redis client
    """
    global redis_client
    if redis_client:
        return redis_client
    try:
        redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("✅ Redis connected successfully")
        return redis_client
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}", exc_info=True)
        raise


async def close_redis() -> None:
    """Close Redis connection."""
    global redis_client
    if redis_client:
        try:
            await redis_client.aclose()
            logger.info("🛑 Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis: {e}")


async def set_data(key: str, value: str, ex: Optional[int] = None) -> None:
    """
    Set data in Redis with optional expiration.
    
    Args:
        key: Redis key
        value: Value to store
        ex: Expiration time in seconds
    """
    if not redis_client:
        return
    try:
        await redis_client.set(key, value, ex=ex)
    except Exception as e:
        logger.error(f"Error setting Redis key {key}: {e}")


async def get_data(key: str) -> Optional[str]:
    """
    Get data from Redis.
    
    Args:
        key: Redis key
        
    Returns:
        Value or None if not found
    """
    if not redis_client:
        return None
    try:
        return await redis_client.get(key)
    except Exception as e:
        logger.error(f"Error getting Redis key {key}: {e}")
        return None


async def delete_data(key: str) -> bool:
    """
    Delete data from Redis.
    
    Args:
        key: Redis key
        
    Returns:
        True if key was deleted
    """
    if not redis_client:
        return False
    try:
        result = await redis_client.delete(key)
        return bool(result)
    except Exception as e:
        logger.error(f"Error deleting Redis key {key}: {e}")
        return False


async def acquire_lock(key: str, ex: int = 1) -> bool:
    """
    Acquire a distributed lock to prevent duplicate requests.
    
    Args:
        key: Lock key
        ex: Expiration time in seconds
        
    Returns:
        True if lock acquired, False if already locked
    """
    if not redis_client:
        return True
    try:
        return await redis_client.set(key, "1", ex=ex, nx=True)
    except Exception as e:
        logger.error(f"Error acquiring lock {key}: {e}")
        return False


class KeyManager:
    """Manager for Redis key naming."""

    @staticmethod
    def get_user_key(user_id: int) -> str:
        """User profile key."""
        return f"user:{user_id}"

    @staticmethod
    def get_task_key(user_id: int, date: str) -> str:
        """Daily task key (date format: YYYY-MM-DD)."""
        return f"task:{user_id}:{date}"

    @staticmethod
    def get_report_key(user_id: int, date: str) -> str:
        """Daily report key."""
        return f"report:{user_id}:{date}"

    @staticmethod
    def get_fsm_key(user_id: int) -> str:
        """FSM state key."""
        return f"fsm:{user_id}"

    @staticmethod
    def get_lock_key(user_id: int, action: str) -> str:
        """Action lock key for duplicate prevention."""
        return f"lock:{user_id}:{action}"

    @staticmethod
    def get_streak_key(user_id: int) -> str:
        """User streak counter key."""
        return f"streak:{user_id}"

    @staticmethod
    def get_last_report_date_key(user_id: int) -> str:
        """Last successful report date key."""
        return f"last_report_date:{user_id}"

    @staticmethod
    def get_score_key(user_id: int) -> str:
        """User total Leda Score key."""
        return f"score:{user_id}"

    @staticmethod
    def get_day_plan_lock_key(user_id: int, date: str) -> str:
        """Day plan lock key until midnight."""
        return f"day_plan_lock:{user_id}:{date}"

    @staticmethod
    def get_pending_referrer_key(user_id: int) -> str:
        """Referrer telegram id captured from start deep link."""
        return f"pending_referrer:{user_id}"


def seconds_until_midnight() -> int:
    """Return seconds until the next local midnight."""
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    ttl = int((tomorrow - now).total_seconds())
    return max(ttl, 60)


def seconds_until_next_sunday_21() -> int:
    """Return seconds until the next Sunday 21:00 local time."""
    now = datetime.now()
    target = now.replace(hour=21, minute=0, second=0, microsecond=0)
    days_ahead = (6 - now.weekday()) % 7
    target = target + timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    ttl = int((target - now).total_seconds())
    return max(ttl, 60)


async def delete_keys_by_patterns(patterns: list[str]) -> int:
    """Delete all Redis keys matching the provided patterns."""
    if not redis_client:
        return 0

    deleted = 0
    try:
        for pattern in patterns:
            async for key in redis_client.scan_iter(match=pattern):
                deleted += int(await redis_client.delete(key))
        return deleted
    except Exception as e:
        logger.error(f"Error deleting Redis keys by patterns {patterns}: {e}", exc_info=True)
        return deleted
