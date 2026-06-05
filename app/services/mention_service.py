from __future__ import annotations

from html import escape


def build_user_mention(
    *,
    telegram_id: int | None,
    username: str | None = None,
    first_name: str | None = None,
    fallback: str = "Участник",
) -> str:
    display_text = f"@{username}" if username else str(first_name or fallback)
    safe_text = escape(display_text)

    if telegram_id:
        return f'<a href="tg://user?id={telegram_id}">{safe_text}</a>'
    if username:
        safe_username = escape(str(username))
        return f'<a href="https://t.me/{safe_username}">{safe_text}</a>'
    return safe_text
