# HomeGroup CRM — Telegram Bot

Telegram-бот для HomeGroup CRM. Сповіщення групи, перегляд плану зустрічей, відмітка присутніх.
Запускається як окремий сервіс у тому ж docker-compose що і бекенд.

## Tech Stack

- **Python**: 3.12
- **Bot framework**: aiogram 3.x (async, FSM для multi-step flows)
- **Scheduler**: APScheduler 3.x (cron-задачі для сповіщень)
- **HTTP client**: httpx (async виклики до бекенд API)
- **Config**: pydantic-settings (env vars + .env файл)
- **Deployment**: Docker, сервіс `bot` в `homegroup-crm-backend/docker-compose.yml`

## Project Structure

```
homegroup-crm-telegrambot/
  bot/
    main.py                — точка входу, ініціалізація Bot + Dispatcher + Scheduler
    config.py              — Settings (pydantic-settings, читає .env)
    api_client.py          — ApiClient: HTTP клієнт до бекенду з авто-реавторизацією
    handlers/
      __init__.py
      common.py            — /start, /help
      attendance.py        — /attendance (FSM flow відмітки присутніх)
      plans.py             — /plan (перегляд плану зустрічі)
    schedulers/
      __init__.py
      notifications.py     — APScheduler jobs: notify_upcoming_events, notify_meeting_plan
  Dockerfile
  requirements.txt
  .env.example
  CLAUDE.md
```

## Architecture

### API Client (`bot/api_client.py`)
`ApiClient` — singleton (`api_client`). Логіниться через `POST /api/v1/auth/login` на старті
і при отриманні 401. JWT токен зберігається в пам'яті.

Доступні методи:
- `get_groups()` → список усіх груп
- `get_cabinet(group_id)` → `GroupCabinetResponse` (nextMeetingDate, members, stats, ...)
- `get_plan(group_id, date)` → `HomeMeetingPlan` або `None` якщо не знайдено
- `get_group_members(group_id)` → список членів групи
- `record_attendance(group_id, meeting_date, entries)` → POST /api/v1/attendance

### Handlers
Кожен хендлер — окремий `Router` з `bot/handlers/`.
Підключаються в `main.py` через `dp.include_router(...)`.

Порядок важливий: `common` → `attendance` → `plans`.

### Scheduler (`bot/schedulers/notifications.py`)
`setup_scheduler(scheduler, bot)` — реєструє APScheduler jobs.
Всі job-и запускаються в timezone `Europe/Kyiv`.

Заплановані задачі:
- `notify_upcoming_events` — щодня о 09:00
- `notify_meeting_plan` — щодня о 18:00 (відправляє план якщо завтра зустріч)

### FSM для відмітки присутніх
(TODO) Використовувати `aiogram.fsm.state.State` + `aiogram.fsm.state.StatesGroup`.
Storage: `MemoryStorage` (достатньо, стейт не потрібен між рестартами).

## Key Patterns

### TelegramGroupId
`HomeGroupEntity.TelegramGroupId` — id Telegram-групи куди бот надсилає сповіщення.
Для кожної домашньої групи в CRM можна вказати свій Telegram chat id.
Бот надсилає повідомлення через `bot.send_message(chat_id=group.telegramGroupId, ...)`.

### Автентифікація бота до API
Бот використовує credentials суперадміна (`API_EMAIL`, `API_PASSWORD`).
Токен кешується в `ApiClient._token`. При 401 → автоматично перелогінюється.

### Polling mode
Бот працює в polling режимі (не webhook). Простіше для деплою — не потрібен публічний endpoint.
Достатньо для нашого use case.

## Environment Variables

```
BOT_TOKEN=your-telegram-bot-token-from-botfather
API_BASE_URL=http://api:8080          # внутрішній docker-compose адрес API
API_EMAIL=admin@example.com           # credentials для логіну до API
API_PASSWORD=your-password
```

В `docker-compose.yml` бекенду змінна `BOT_TOKEN` береться з `.env`.
`API_EMAIL` і `API_PASSWORD` прокидаються як `${SUPERADMIN_EMAIL}` / `${SUPERADMIN_PASSWORD}`.

## Backend API Used

Бот використовує наступні endpoint-и бекенду (`homegroup-crm-backend`):

```
POST /api/v1/auth/login                     — отримати JWT
GET  /api/v1/groups                         — список груп (з TelegramGroupId)
GET  /api/v1/groups/:id/cabinet             — кабінет групи (nextMeetingDate, members)
GET  /api/v1/groups/:id/plans/date/:date    — план зустрічі
GET  /api/v1/groups/:id/members             — члени групи
POST /api/v1/attendance                     — записати відвідуваність
```

Повний API задокументований в `homegroup-crm-backend/CLAUDE.md`.

## Deployment

Бот запускається як сервіс `bot` в `homegroup-crm-backend/docker-compose.yml`.
Директорія `../homegroup-crm-telegrambot` використовується як build context.

```bash
# Запустити з бекенду (запускає api + db + bot)
cd homegroup-crm-backend
docker compose up --build

# Тільки бот (якщо api вже запущений)
docker compose up --build bot

# Логи бота
docker compose logs -f bot
```

Бот спілкується з API через внутрішню docker-compose мережу: `http://api:8080`.

## Development Commands

```bash
# Локально (без docker, потрібен запущений API)
cd homegroup-crm-telegrambot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заповнити BOT_TOKEN і API_*
API_BASE_URL=http://localhost:8081 python -m bot.main
```

## What's Done

- [x] Структура проекту (handlers, schedulers, api_client)
- [x] ApiClient з авто-реавторизацією
- [x] APScheduler з timezone Europe/Kyiv
- [x] Docker деплой як сервіс в docker-compose бекенду
- [x] /start, /help команди

## TODO

- [ ] /plan — отримати план наступної зустрічі і відформатувати для Telegram
- [ ] /attendance — FSM flow: список членів → inline кнопки присутній/відсутній → submit
- [ ] notify_upcoming_events — сповіщення про події з /cabinet за N днів наперед
- [ ] notify_meeting_plan — відправка плану в Telegram-групу напередодні зустрічі
- [ ] Визначення groupId по TelegramGroupId (яка група відповідає цьому чату)
