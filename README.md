# 🎯 Ledolab Business Club

**Закрытая система для предпринимателей** с квиз-диагностикой, постановкой дневных задач, отчетностью и рейтингом.

## 🚀 Что это?

Telegram бот для Business To-Do Club:
- 📋 Квиз-диагностика (6 вопросов на WebApp)
- 🎯 Постановка одной задачи в день
- ✅ Сдача отчета вечером
- ⭐ Система Leda Score (рейтинг участников)
- 🏆 Публичный лидерборд

---

## 🛠️ Технический стек

- **Язык**: Python 3.11+
- **Framework**: aiogram 3.x (Telegram API)
- **БД**: Supabase (PostgreSQL)
- **Cache**: Redis
- **Deployment**: Railway
- **UI**: HTML/CSS/JS WebApp для квиза

---

## 📦 Структура проекта

```
ledolab/
├── app/
│   ├── config.py              # Конфигурация из env variables
│   ├── logging_config.py      # Логирование
│   ├── main.py                # Entry point бота
│   ├── database.py            # Supabase операции
│   ├── cache.py               # Redis utilities
│   ├── handlers/              # Telegram handlers
│   │   ├── start.py           # /start команда
│   │   ├── quiz.py            # WebApp квиз
│   │   └── callbacks.py       # Inline кнопки
│   ├── services/              # Бизнес-логика
│   │   ├── quiz_service.py    # Профилирование
│   │   ├── task_service.py    # Управление задачами
│   │   ├── report_service.py  # Отчеты
│   │   ├── score_service.py   # Leda Score
│   │   └── rating_service.py  # Рейтинг
│   ├── keyboards/inline/      # UI кнопки
│   │   └── start.py
│   └── states/                # FSM states
│       └── quiz.py
├── docs/                      # Frontend
│   └── index.html             # WebApp квиз
├── requirements.txt           # Зависимости
├── .env.example               # Шаблон env
├── Dockerfile                 # Docker контейнер
└── docker-compose.yml         # Локальная разработка
```

---

## 🔧 Переменные окружения

**Обязательные:**
- `BOT_TOKEN` — токен бота от @BotFather
- `REDIS_URL` — Redis connection (вида `redis://:password@host:port`)
- `SUPABASE_URL` — URL проекта Supabase
- `SUPABASE_KEY` — Anon Key от Supabase

**Опциональные:**
- `REPORTS_GROUP_ID` — ID группы для публикации отчетов (по умолчанию: 0)
- `ADMIN_IDS` — Telegram ID админов (comma-separated)
- `WEB_APP_URL` — URL квиза (по умолчанию: https://your-domain.com)
- `LOG_LEVEL` — DEBUG/INFO/WARNING (по умолчанию: INFO)
- `SENTRY_DSN` — Для мониторинга ошибок

Полный список см. в `.env.example`

---

## 🚀 Развертывание на Railway

### 1️⃣ Подготовка

```bash
# Клонируй репо
git clone https://github.com/LedolabAgency/Ledolab.git
cd Ledolab

# Создай .env из шаблона (не коммить!)
cp .env.example .env
```

### 2️⃣ Создай сервисы в Railway

1. **Redis** (`Railway → Add Services → Redis`)
   - Copy `REDIS_URL` из подробностей сервиса

2. **Supabase** (внешний сервис)
   - Создай проект на supabase.com
   - Copy `SUPABASE_URL` и `SUPABASE_KEY`

### 3️⃣ Deploy на Railway

```bash
# 1. Connect repo to Railway
railway link

# 2. Add Telegram Bot Token
railway variables set BOT_TOKEN=your_token_here

# 3. Add other variables
railway variables set REDIS_URL=redis://:password@host:port
railway variables set SUPABASE_URL=https://your-project.supabase.co
railway variables set SUPABASE_KEY=your-anon-key
railway variables set REPORTS_GROUP_ID=your_group_id

# 4. Deploy
railway up
```

### 4️⃣ Webhook (опционально, вместо polling)

Если хочешь webhook вместо polling:

```bash
railway variables set WEBHOOK_URL=https://your-railway-domain/webhook
```

---

## 🗄️ Supabase схема

Необходимые таблицы:

```sql
-- Пользователи
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_id BIGINT UNIQUE NOT NULL,
  username TEXT,
  first_name TEXT,
  language_code TEXT DEFAULT 'ru',
  business_level TEXT,
  focus_zone TEXT,
  discipline_potential TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Ответы квиза
CREATE TABLE quiz_answers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_key TEXT NOT NULL,
  answer_key TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Дневные задачи
CREATE TABLE daily_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_text TEXT NOT NULL,
  date DATE NOT NULL,
  status TEXT DEFAULT 'waiting_report',
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, date)
);

-- Отчеты
CREATE TABLE reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id UUID NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
  report_text TEXT NOT NULL,
  proof_type TEXT,
  file_id TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Leda Score
CREATE TABLE scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  points INTEGER NOT NULL,
  reason TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 💻 Локальная разработка

```bash
# 1. Создай .env
cp .env.example .env

# 2. Обнови значения (используй локальный Redis или Railway Redis URL)
# BOT_TOKEN=your_token
# REDIS_URL=redis://localhost:6379/0
# SUPABASE_URL=https://your-project.supabase.co
# SUPABASE_KEY=your-key

# 3. Запусти контейнеры
docker-compose up -d

# 4. Или запусти напрямую
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
python -m app.main
```

---

## 📚 API

### Handlers

- `/start` — Начало, проверка регистрации
- `web_app_data` — Получение данных квиза

### Callbacks

- `club_enter` — Вход в клуб
- `task_set` — Постановка задачи
- `report_submit` — Сдача отчета
- `menu_back` — Возврат в меню

### Services

- `quiz_service.validate_quiz()` — Валидация данных
- `quiz_service.calculate_business_profile()` — Расчет профиля
- `task_service.set_daily_task()` — Создание задачи
- `report_service.submit_report()` — Создание отчета
- `rating_service.get_rating_leaderboard()` — Получение рейтинга

---

## 🐛 Debugging

```bash
# Посмотри логи на Railway
railway logs

# Или локально
LOG_LEVEL=DEBUG python -m app.main
```

---

## 📞 Support

- 🔗 Telegram: @LedolabAgency
- 📧 Email: ledolab.online@gmail.com

---

**Made with 🔥 by Leda.lab Agency**
