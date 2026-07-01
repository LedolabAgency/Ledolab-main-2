from __future__ import annotations

import logging
from html import escape
from urllib.parse import quote

from aiogram import Bot
from aiogram import types
from aiogram.types import User

from app import cache, database
from app.config import REPORTS_GROUP_ID
from app.services import mention_service

logger = logging.getLogger(__name__)

REFERRER_BONUS = 50
NEWBIE_BONUS = 20
REFERRAL_REPORT_THRESHOLD = 3


def _last_group_chat_key(user_id: int) -> str:
    return f"last_group_chat:{user_id}"


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
        "💸 <b>Реферальная программа</b>\n\n"
        "Приглашайте предпринимателей в LedoLab Business Club по своей реферальной ссылке.\n\n"
        "Как это работает:\n\n"
        "1️⃣ Друг регистрируется по вашей ссылке.\n"
        "2️⃣ Выполняет условия клуба (сдаёт 3 отчёта).\n"
        "3️⃣ Вы получаете +100 грн.\n"
        "4️⃣ Друг получает +100 грн.\n\n"
        "🔥 Сейчас участие в клубе бесплатно только для первых 100 участников. "
        "После этого стоимость входа будет увеличиваться х2 каждые 100 юзеров.\n\n"
        "Чем больше рекомендаций — тем больше вознаграждений."
    )
    return text, share_url


async def _resolve_target_group_ids(
    *,
    newbie_telegram_id: int,
    referral: dict,
) -> list[int]:
    candidate_ids: list[int] = []

    newbie_chat = await cache.get_data(_last_group_chat_key(newbie_telegram_id))
    if newbie_chat:
        try:
            candidate_ids.append(int(newbie_chat))
        except ValueError:
            pass

    referrer_telegram_id = referral.get("referrer_telegram_id")
    if referrer_telegram_id:
        referrer_chat = await cache.get_data(_last_group_chat_key(int(referrer_telegram_id)))
        if referrer_chat:
            try:
                chat_id = int(referrer_chat)
                if chat_id not in candidate_ids:
                    candidate_ids.append(chat_id)
            except ValueError:
                pass

    if REPORTS_GROUP_ID and REPORTS_GROUP_ID not in candidate_ids:
        candidate_ids.append(REPORTS_GROUP_ID)

    return candidate_ids


async def _announce_referral_bonus_to_group(
    *,
    bot: Bot,
    newbie_telegram_id: int,
    referral: dict,
) -> None:
    target_group_ids = await _resolve_target_group_ids(
        newbie_telegram_id=newbie_telegram_id,
        referral=referral,
    )
    if not target_group_ids:
        logger.warning("Referral group bonus skipped | newbie=%s reason=no_target_group", newbie_telegram_id)
        return

    me = await bot.get_me()
    referrer_telegram_id = int(referral.get("referrer_telegram_id") or 0)
    referrer = await database.get_club_user(referrer_telegram_id) if referrer_telegram_id else None
    referrer_mention = mention_service.build_user_mention(
        telegram_id=referrer_telegram_id,
        username=(referrer or {}).get("username"),
        first_name=(referrer or {}).get("first_name"),
        fallback="участнику клуба",
    )
    text = (
        f"🎉 +100 грн начислено {referrer_mention}!\n\n"
        "За участника, зарегистрированного по реферальной ссылке 💰\n\n"
        "Получайте вознаграждение за каждую успешную рекомендацию.\n\n"
        "Нажмите кнопку ниже, чтобы получить свою реферальную ссылку."
    )
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🚀 Рефералка",
                    url=f"https://t.me/{me.username}?start=ref_setup",
                )
            ]
        ]
    )

    for target_group_id in target_group_ids:
        try:
            await bot.send_message(target_group_id, text, reply_markup=markup, parse_mode="HTML")
            logger.info("Referral group bonus sent | newbie=%s chat=%s", newbie_telegram_id, target_group_id)
            return
        except Exception as e:
            logger.warning(
                "Referral group bonus failed | newbie=%s chat=%s error=%s",
                newbie_telegram_id,
                target_group_id,
                e,
            )


async def announce_referred_member_joined(
    *,
    bot: Bot,
    newbie_telegram_id: int,
    newbie_username: str | None,
    newbie_first_name: str | None,
) -> None:
    """Announce in the group that a referred entrepreneur just joined the club."""
    referral = await database.get_referral_by_referred_telegram(newbie_telegram_id)
    if not referral:
        return

    referrer_telegram_id = int(referral.get("referrer_telegram_id") or 0)
    if not referrer_telegram_id:
        return

    target_group_ids = await _resolve_target_group_ids(
        newbie_telegram_id=newbie_telegram_id,
        referral=referral,
    )
    if not target_group_ids:
        logger.warning("Referral join announce skipped | newbie=%s reason=no_target_group", newbie_telegram_id)
        return

    referrer = await database.get_club_user(referrer_telegram_id)
    referrer_mention = mention_service.build_user_mention(
        telegram_id=referrer_telegram_id,
        username=(referrer or {}).get("username"),
        first_name=(referrer or {}).get("first_name"),
        fallback="участник клуба",
    )
    newbie_mention = mention_service.build_user_mention(
        telegram_id=newbie_telegram_id,
        username=newbie_username,
        first_name=newbie_first_name,
        fallback="новый предприниматель",
    )

    text = (
        "🤝 <b>Новый бизнес-партнёр в клубе!</b>\n\n"
        f"{referrer_mention} привёл нового предпринимателя — {newbie_mention}.\n\n"
        f"Как только новичок сдаст свой {REFERRAL_REPORT_THRESHOLD}-й отчёт — оба получат\n"
        f"LedoScore (+{REFERRER_BONUS} / +{NEWBIE_BONUS}) и по 100 грн 🔥\n\n"
        "Сильное окружение растит сильных. Поддержите новенького 💪"
    )
    if CLUB_MENU_URL:
        text += f"\n\n👇 {newbie_mention}, для постановки целей переходи в <a href=\"{CLUB_MENU_URL}\">Меню клуба</a>"

    for target_group_id in target_group_ids:
        try:
            await bot.send_message(target_group_id, text, parse_mode="HTML")
            logger.info("Referral join announced | newbie=%s chat=%s", newbie_telegram_id, target_group_id)
            return
        except Exception as e:
            logger.warning(
                "Referral join announce failed | newbie=%s chat=%s error=%s",
                newbie_telegram_id,
                target_group_id,
                e,
            )


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

    newbie = await database.get_club_user(newbie_telegram_id)
    newbie_mention = mention_service.build_user_mention(
        telegram_id=newbie_telegram_id,
        username=(newbie or {}).get("username"),
        first_name=(newbie or {}).get("first_name"),
        fallback="твой реферал",
    )
    try:
        await bot.send_message(
            int(hydrated["referrer_telegram_id"]),
            f"🔥 Твой реферал {newbie_mention} сдал {REFERRAL_REPORT_THRESHOLD}-й отчёт!\n\n"
            f"За это тебе начислено +{REFERRER_BONUS} LedoScore, твоему рефералу +{NEWBIE_BONUS}.\n"
            "И вам обоим — по 100 грн 💰",
            parse_mode="HTML",
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

    await _announce_referral_bonus_to_group(
        bot=bot,
        newbie_telegram_id=newbie_telegram_id,
        referral=hydrated,
    )

    return {
        "referrer_bonus": REFERRER_BONUS,
        "newbie_bonus": NEWBIE_BONUS,
        "reports_completed": reports_completed,
    }
