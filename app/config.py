"""
Конфігурація проєкту — все читається з ENV.

Змінні оточення задаються в Railway Variables або .env під час локальної розробки.
"""
from __future__ import annotations

import os
from typing import List, Optional


def _getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


# Основні
BOT_TOKEN: Optional[str] = _getenv("BOT_TOKEN")
REDIS_URL: Optional[str] = _getenv("REDIS_URL")
SUPABASE_URL: Optional[str] = _getenv("SUPABASE_URL")
SUPABASE_KEY: Optional[str] = _getenv("SUPABASE_KEY")
WEB_APP_URL: str = _getenv("WEB_APP_URL", "https://example.com")

# Опціональні
SENTRY_DSN: Optional[str] = _getenv("SENTRY_DSN")
REPORTS_GROUP_ID: int = int(_getenv("REPORTS_GROUP_ID", "0") or 0)
LOG_LEVEL: str = _getenv("LOG_LEVEL", "INFO").upper()

# Список адмінів (comma-separated в ENV)
def _parse_admins(raw: Optional[str]) -> List[int]:
    if not raw:
        return []
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


ADMIN_IDS: List[int] = _parse_admins(_getenv("ADMIN_IDS"))


__all__ = [
    "BOT_TOKEN",
    "REDIS_URL",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "WEB_APP_URL",
    "SENTRY_DSN",
    "REPORTS_GROUP_ID",
    "LOG_LEVEL",
    "ADMIN_IDS",
]
