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

## Открытые/возможные следующие задачи
- Кнопка прыжка на закреплённое меню в группе (обсуждали, не делали).
- Рефакторинг `start.py` (юзер хотел разбить файл на части, отложили «на потом»).
- Юзер планировал протестировать пункты после деплоя и написать что ещё поправить.
