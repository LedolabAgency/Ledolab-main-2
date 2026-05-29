from __future__ import annotations

import logging
from urllib.parse import quote

from aiogram import Bot
from aiogram.types import User

from app import cache, database

logger = logging.getLogger(__name__)

REFERRER_BONUS = 50
NEWBIE_BONUS = 20
REFERRAL_REPORT_THRESHOLD = 3


async def capture_referral_start(new_user_id: int, start_arg: str) -> int | None:
    raw = (start_arg or "").strip()
    if raw.startswith("ref_"):
        raw = raw[4:]
    if not raw.isdigit():
        return None
    referrer_id = int(raw)
    if referrer_id == new_user_id:
        return None
    await cache.set_data(cache.KeyManager.get_pending_referrer_key(new_user_id), str(referrer_id), ex=30 * 24 * 60 * 60)
    return referrer_id


async def bind_pending_referral(new_user_id: int) -> None:
    referrer_id_raw = await cache.get_data(cache.KeyManager.get_pending_referrer_key(new_user_id))
    if not referrer_id_raw:
        await database.sync_referral_users(new_user_id)
        return
    try:
        referrer_id = int(referrer_id_raw)
    except ValueError:
        return
    await database.upsert_referral_link(referrer_id, new_user_id)
    await database.sync_referral_users(new_user_id)


async def build_referral_invite(bot: Bot, actor: User) -> tuple[str, str]:
    me = await bot.get_me()
    referral_link = f"https://t.me/{me.username}?start=ref_{actor.id}"
    share_text = (
        "Не хватает фокуса?\n"
        "Теряешься в задачах, откладываешь важное и буксуешь без системы.\n\n"
        "В LedoLab Business Club — цель, дисциплина и окружение, которое держит в движении 🚀\n\n"
        "Никто не придёт и не сделает это за тебя. Начни двигаться к своей цели каждый день 👇"
    )
    share_url = f"https://t.me/share/url?url={quote(referral_link)}&text={quote(share_text)}"
    text = (
        "🚀 Рефералка LedoLab Business Club\n\n"
        f"Твой бонус: +{REFERRER_BONUS} LedoScore\n"
        f"Новичку: +{NEWBIE_BONUS} LedoScore\n\n"
        f"Важно: бонусы начисляются только после {REFERRAL_REPORT_THRESHOLD}-го отчета новичка.\n\n"
        "Нажми кнопку ниже и отправь приглашение 👇"
    )
    return text, share_url


async def process_referral_after_report(
    *,
    bot: Bot,
    newbie_user_id: str,
    newbie_telegram_id: int,
) -> dict | None:
    referral = await database.get_referral_by_referred_user(newbie_user_id)
    if not referral:
        referral = await database.get_referral_by_referred_telegram(newbie_telegram_id)
    if not referral:
        return None

    reports_completed = await database.count_daily_reports_for_user(newbie_user_id)
    await database.update_referral_progress(referral["id"], reports_completed)

    if referral.get("bonus_awarded") or reports_completed < REFERRAL_REPORT_THRESHOLD:
        return None

    hydrated = await database.sync_referral_users(newbie_telegram_id) or referral
    referrer_user_id = hydrated.get("referrer_user_id")
    referred_user_id = hydrated.get("referred_user_id") or newbie_user_id
    if not referrer_user_id or not referred_user_id:
        logger.warning("Referral award skipped, missing users ids | referral=%s", hydrated.get("id"))
        return None

    await database.award_score(referrer_user_id, REFERRER_BONUS, "Referral bonus after 3rd report")
    await database.award_score(referred_user_id, NEWBIE_BONUS, "Referral welcome bonus after 3rd report")
    await database.mark_referral_bonus_awarded(hydrated["id"], reports_completed)

    try:
        await bot.send_message(
            int(hydrated["referrer_telegram_id"]),
            f"🔥 Твой реферал закрыл {REFERRAL_REPORT_THRESHOLD}-й отчет.\n"
            f"Тебе начислено +{REFERRER_BONUS} LedoScore.",
        )
    except Exception as e:
        logger.warning("Failed to notify referrer %s: %s", hydrated.get("referrer_telegram_id"), e)

    try:
        await bot.send_message(
            newbie_telegram_id,
            f"🎁 Ты закрыл {REFERRAL_REPORT_THRESHOLD}-й отчет по рефералке.\n"
            f"Тебе начислено +{NEWBIE_BONUS} LedoScore.",
        )
    except Exception as e:
        logger.warning("Failed to notify newbie %s: %s", newbie_telegram_id, e)

    return {
        "referrer_bonus": REFERRER_BONUS,
        "newbie_bonus": NEWBIE_BONUS,
        "reports_completed": reports_completed,
    }
