from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware

from app import cache
from app.config import THROTTLE_SECONDS

logger = logging.getLogger(__name__)


class ThrottleMiddleware(BaseMiddleware):
    """Lightweight per-user throttle backed by Redis."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        event_name = type(event).__name__.lower()
        key = f"throttle:{event_name}:{user.id}"
        allowed = await cache.acquire_lock(key, ex=THROTTLE_SECONDS)
        if allowed:
            return await handler(event, data)

        logger.info("THROTTLED | user=%s event=%s", user.id, event_name)
        return None
