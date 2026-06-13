"""
Конфігурація проєкту — все читається з ENV.

Змінні оточення задаються в Railway Variables або .env під час локальної розробки.
"""
from __future__ import annotations

import os
from typing import List, Optional


def _getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


# Основні
BOT_TOKEN: str = _require("BOT_TOKEN")
REDIS_URL: str = _require("REDIS_URL")
SUPABASE_URL: str = _require("SUPABASE_URL")
SUPABASE_KEY: str = _require("SUPABASE_KEY")
WEB_APP_URL: str = _getenv("WEB_APP_URL", "https://example.com")
_GROUP_URL: str = _getenv("CLUB_GROUP_URL", "https://t.me/+WzcCVTajwSozNzYy")
CLUB_GROUP_URL: Optional[str] = _GROUP_URL
GROUP_ENTRY_URL: Optional[str] = _GROUP_URL

# Опціональні
SENTRY_DSN: Optional[str] = _getenv("SENTRY_DSN")
REPORTS_GROUP_ID: int = int(_getenv("REPORTS_GROUP_ID", "0") or 0)
LOG_LEVEL: str = _getenv("LOG_LEVEL", "INFO").upper()
TASK_SCORE_MAIN: int = int(_getenv("TASK_SCORE_MAIN", "1") or 1)
TASK_SCORE_EXTRA: int = int(_getenv("TASK_SCORE_EXTRA", "1") or 1)
REPORT_SCORE: int = int(_getenv("REPORT_SCORE", "5") or 5)
VIDEO_PROOF_SCORE: int = int(_getenv("VIDEO_PROOF_SCORE", "2") or 2)
GOAL_SCORE: int = int(_getenv("GOAL_SCORE", "3") or 3)
FAIL_DAY_SCORE: int = int(_getenv("FAIL_DAY_SCORE", "-3") or -3)
THROTTLE_SECONDS: int = int(_getenv("THROTTLE_SECONDS", "1") or 1)

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
    "CLUB_GROUP_URL",
    "GROUP_ENTRY_URL",
    "SENTRY_DSN",
    "REPORTS_GROUP_ID",
    "LOG_LEVEL",
    "TASK_SCORE_MAIN",
    "TASK_SCORE_EXTRA",
    "REPORT_SCORE",
    "VIDEO_PROOF_SCORE",
    "GOAL_SCORE",
    "FAIL_DAY_SCORE",
    "THROTTLE_SECONDS",
    "ADMIN_IDS",
]
