# Рабочие заметки — LedoLab Business Club bot

> Этот файл — память между сессиями (контейнер эфемерный, сбрасывается).
> Завтрашняя сессия: прочитать этот файл первым делом, чтобы продолжить без потерь.
> Перед мержем в main этот файл можно удалить.

## Проект
- Телеграм-бот для **LedoLab Business Club** — бизнес-сообщество (НЕ спорт).
- Стек: aiogram 3, FSM (GoalStates / TaskStates / ReportStates), Redis (кэш + локи, `app/cache.py` KeyManager), Supabase (Postgres), хостинг Railway.
- Логика клуба: цель на 30 дней → разбивка на 5-дневный маршрут → каждый день до 3 задач + вечерний отчёт → LedoScore/рейтинг.

## Правила работы (ВАЖНО, соблюдать строго)
1. Работаем **ТОЛЬКО** на ветке `feature/add-config`. Новые ветки не создавать никогда.
2. Workflow: **сначала обсуждаем логику фикса → юзер подтверждает → только потом меняем код → пушим**. Без самодеятельности — кроме обговоренного фикса ничего не трогать.
3. После изменений: commit + `git push -u origin feature/add-config`.
4. Отвечать на русском, по факту, без воды.

## Ключевые технические нюансы (набитые шишки)
- Telegram `file_id` привязан к конкретному боту (id от чужого бота не сработает).
- `ReplyKeyboardRemove` нельзя слать в одном сообщении с `InlineKeyboardMarkup` — нужно отдельное сообщение.
- Трюк «невидимое снятие reply-клавиатуры»: отправить "." с `ReplyKeyboardRemove`, затем сразу удалить это сообщение. Пустую строку/zero-width Telegram отвергает (`text must be non-empty`).
- `one_time_keyboard=True` прячет reply-клаву после использования; `is_persistent=True` держит постоянно.
- Две разные таблицы юзеров:
  - `database.get_user(tg_id)` → читает таблицу `quiz_data`, `id` это **int** (например 34).
  - `database.get_club_user(tg_id)` / `ensure_club_user(...)` → таблица `users`, `id` это **UUID**.
  - `database.get_active_goal(user_id)` ждёт **UUID** (goals.user_id). Передавать int → ошибка `invalid input syntax for type uuid`. Всегда брать UUID из club_user.
- Постинг в группу идёт в `REPORTS_GROUP_ID` (env). Если в группе не видно сообщений — проверить что env указывает на нужный чат, это конфиг, не код.
- Кнопки «Вернуться в группу» используют `CLUB_GROUP_URL = GROUP_ENTRY_URL = t.me/+WzcCVTajwSozNzYy` (инвайт-ссылка). Она открывает чат, но НЕ прыгает на закреплённое меню. Чтобы прыгать на закреп — нужна ссылка вида `t.me/c/<chat_id>/<msg_id>` и хранение message_id закрепа (пока не сделано, обсуждали 2 варианта: хардкод env / автопостинг+пин).

## Сделано в этой сессии (всё запушено в feature/add-config)
1. **Тихая кнопка «1-Й ДЕНЬ»** — после подтверждения 30-дн цели стейт оставался `confirming_goal`. Фикс: в `handle_goal_split_days` ставим `GoalStates.waiting_day_text` перед показом интро маршрута.
2. **Кнопка телефона не исчезала** — `contact_reply_keyboard` переведена на `one_time_keyboard=True`; после получения контакта шлём "." + `ReplyKeyboardRemove` и удаляем.
3. **Welcome видео-кружок** — правильный file_id `DQACAgIAAxkBAAIJAAFqLsz794WUmlRDtogPNDxFyHhzNAACjp8AAksxeEmZvGQ5Iw-gZTwE`, отправка в try/except (иначе хендлер падал молча).
4. **Стейт квиза не чистился** — `handle_quiz_completion` теперь делает `state.clear()` в начале.
5. **UX 5-дневного флоу** — авто-переход между днями (`_show_goal_day_prompt` с prefix), убраны мёртвые кнопки «Шаг назад», добавлены `goal_route_back` / `goal_review_back` / `goal_edit_back`.
6. **Locked сообщение 30-дн цели** — теперь тянет реальный текст цели из БД (через `ensure_club_user` → UUID) + кнопка «Вернуться в группу». (Был баг с `get_user` → int → UUID error, исправлен.)
7. **Залипшие кнопки старого флоу** (главный баг): после подтверждения 5 целей стейт чистится, но старые сообщения с кнопками остаются.
   - `handle_goal_split_days`: гард через `_route_already_set()` (проверка БД на ≥5 milestones) → если маршрут уже стоит, алерт «✅ Маршрут на 5 дней уже собран», без перезапуска флоу.
   - Добавлен catch-all без стейта `handle_stale_goal_buttons` (ловит `goal_day:*`, `goal_route_back`, `goal_review_back`, `goal_edit_back`, `goal_confirm`, `goal_edit`), зарегистрирован ПОСЛЕ стейтовых хендлеров → даёт алерт на устаревших сообщениях.
8. **«День закрыт»** — под сообщение `_show_day_closed_message` добавлена инлайн-кнопка «Вернуться в группу».
9. **Дневные задачи в группу** — `confirm_day_tasks` теперь постит в `REPORTS_GROUP_ID` (упоминание юзера + список задач + дедлайн). Маршрут на 5 дней постился и раньше (`confirm_goal_flow`).

## Важные места в коде
- `app/handlers/start.py` — основной файл (~1700 строк):
  - `_route_already_set()` — хелпер проверки «маршрут уже в БД».
  - `handle_goal_split_days` (~472), `handle_stale_goal_buttons` (~1652, в конце).
  - `confirm_goal_flow` (~1518) — постит маршрут в группу.
  - `confirm_day_tasks` (~1271) — постит дневные задачи в группу.
  - `_show_day_closed_message` (~103), `_start_goal_flow` (~366).
- `app/handlers/quiz.py` — квиз + шеринг контакта + welcome.
- `app/keyboards/inline/start.py` — все клавиатуры.
- `app/cache.py` — Redis KeyManager (goal_lock, goal_day_lock, day_plan_lock, streak и т.д.).

## Сделано в сессии 15.06 (всё в feature/add-config)
1. **Извлечение file_id с кружочка/фото** — временные хендлеры (приватный чат, фильтр `F.chat.type == "private"`). **Оба временных перехватчика уже удалены.**
2. **Видео-кружки на экранах цели/маршрута** — file_id вставлены перед «🔥 Цель зафиксирована!» (`DQACAgIAAxkBAAIJ2WovIRV-D8EaM36b9EkcM3QmV5VKAAKZnwACSzGASRFzE7wUgPYzPAQ`) и перед «🚀 Готово…» (`DQACAgIAAxkBAAIJ3GovIl7y-TqRnzydfAABRSzrDtx23AACqJ8AAksxgElxbENHNxKwRTwE`).
3. **Залипший goal_lock после ресета БД** — Redis-ключ `goal_lock` (TTL 30 дней) переживал сброс БД. Фикс в `_start_goal_flow`: проверяем активную цель в БД, если её нет — удаляем устаревший Redis-ключ.
4. **Рефералка — полный фикс (была сломана целиком):**
   - `capture_referral_start` никогда не вызывался → добавили в `cmd_start`: `if args.startswith("ref_"): await referral_service.capture_referral_start(...)`.
   - `?start=ref_setup` вёл в никуда → добавили `if args == "ref_setup": await _show_referral_invite(...)`.
   - Кнопка «💸 Рефералка» в `club_main_menu` (`app/keyboards/inline/start.py`).
   - Объявление в группу при входе реферала: `referral_service.announce_referred_member_joined()`.
   - **Дубль смс в группу** — `handle_contact_share` слал И реферальное объявление, И generic `community_service.announce_member_joined`. Фикс: generic шлём только если юзер НЕ реферал (проверка `get_referral_by_referred_telegram`).
   - **Картинка перед маршрутом** (`_send_goal_route_intro`, `GOAL_ROUTE_IMAGE`) — убрана, шлём только текст.
5. **Реферальный шеринг через inline-режим (итоговый вид):**
   - Включён Inline Mode в @BotFather (`/setinline`, placeholder «Пригласить друга 🔗»). Без этого код не работает.
   - Кнопка «🔗 Получить реферальную ссылку» = `switch_inline_query=""` (НЕ `t.me/share/url`).
   - Inline-хендлер `inline_referral_share` (start.py) отдаёт `InlineQueryResultCachedPhoto`: фото-карточка LedoLab + подпись (текст из `referral_service.build_referral_inline_content`) + инлайн-кнопка «🚀 Вступить в LedoLab Business Club» (url = реф-ссылка).
   - **file_id картинки карточки:** `REFERRAL_CARD_PHOTO_ID = "AgACAgIAAxkBAAIKdWowbaW6cU3zHGChGVTZ4Bp8Y0CZAAKUHmsbhDCBSYZ-9klgXBR2AQADAgADeAADPAQ"` (константа вверху start.py).
   - **Почему так (ограничения Telegram):** превью для bot-ссылки `?start=ref_X` Telegram НЕ генерирует. `t.me/share/url` требует `url=` для открытия списка контактов и всегда лепит ссылку ПЕРВОЙ строкой (вниз не убрать). Inline-режим даёт фото+текст+кнопку, но требует 2 тапа (выбрать чат → тапнуть результат) — поведение Telegram, убрать нельзя. Решили оставить красивую карточку с двойным тапом.
   - Профиль бота: юзер настроил `/setdescription` (текст про клуб) — видно ПОСЛЕ перехода в бота, к реф-смс отношения не имеет.

## Открытые/возможные следующие задачи
- Кнопка прыжка на закреплённое меню в группе (обсуждали, не делали).
- Рефакторинг `start.py` (юзер хотел разбить файл на части, отложили «на потом»).
- Юзер планировал протестировать пункты после деплоя и написать что ещё поправить.
