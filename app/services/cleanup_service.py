from __future__ import annotations

import asyncio

from aiogram import Bot, types


def schedule_delete_message(bot: Bot, chat_id: int, message_id: int, delay_seconds: int = 120) -> None:
    async def _worker() -> None:
        try:
            await asyncio.sleep(max(delay_seconds, 1))
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            return

    asyncio.create_task(_worker(), name=f"cleanup:{chat_id}:{message_id}")


async def send_temporary_message(
    target: types.Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = None,
    delete_after: int = 120,
) -> types.Message:
    sent = await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    schedule_delete_message(target.bot, sent.chat.id, sent.message_id, delete_after)
    return sent
