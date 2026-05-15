# HomeGroup CRM — Telegram Bot

Telegram-бот для HomeGroup CRM. Сповіщення групи, перегляд плану зустрічей, відмітка присутніх.
Запускається як окремий сервіс у тому ж docker-compose що і бекенд.

## Tech Stack

- **Python**: 3.12
- **Bot framework**: aiogram 3.x (async, inline keyboards)
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
      common.py            — /start, /help, /test_notify
      attendance.py        — /attendance + auto-trigger (inline FSM flow)
      plans.py             — /plan (перегляд плану зустрічі)
      group_events.py      — привітання при вступі бота в групу (chat ID)
    schedulers/
      __init__.py
      notifications.py     — APScheduler jobs
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
- `get_groups()` → список усіх груп (з `telegramGroupId`)
- `get_cabinet(group_id)` → `GroupCabinetResponse` (nextMeetingDate, lastMeetingDate, ...)
- `get_plan(group_id, date)` → `HomeMeetingPlan` або `None`
- `get_people()` → всі люди (для telegram lookup)
- `get_admins()` → всі адміни (для telegram lookup)
- `get_group_members(group_id)` → члени групи (Person + User)
- `get_group_events(group_id)` → події групи
- `record_attendance(group_id, meeting_date, entries)` → POST /api/v1/attendance
- `save_attendance_meta(group_id, meeting_date, guest_count)` → POST /api/v1/attendance/meta

### Handlers
Роутери підключаються в `main.py`. Порядок: `common` → `attendance` → `plans` → `group_events`.

**common.py** — `/start`, `/help`, `/test_notify` (тригерить notify_upcoming_events вручну)

**plans.py** — `/plan`:
- Знаходить групу по `telegramGroupId == chat_id`
- Бере `nextMeetingDate` з кабінету
- Завантажує план і форматує: `build_telegram_map(people, admins)` резолвить відповідальних до `@handle`
- Формат: `{time} - {title}: @responsible` + `   • info_line`, блоки без часу → футер після `------------------`

**attendance.py** — `/attendance` + auto-trigger:
- Стан зберігається в `sessions: dict[int, AttendanceSession]` (keyed by chat_id)
- Inline flow: `att_start` → `att_toggle_{i}` → `att_done` → `att_guests_{n}` → summary
- Команда `/attendance` → marks `lastMeetingDate`
- Auto-trigger → marks today's date (якщо є зустріч)

**group_events.py** — `my_chat_member` handler: при додаванні бота в групу надсилає chat ID для CRM.

### Scheduler (`bot/schedulers/notifications.py`)
Всі job-и в timezone `Europe/Kyiv`.

- `check_auto_attendance` — щохвилини: якщо `meetingTime + 60 хв` (±3 хв) → тригерить attendance flow
  - Дедуплікація: `_triggered: set[(group_id, date)]` в пам'яті
- `notify_upcoming_events` — щодня о 09:00: сповіщення про події групи
  - 🎉 Сьогодні / 📅 Через 7 днів
  - Рекурентні події (без року) — по місяць+день, одноразові (з роком) — точна дата
- `notify_meeting_plan` — щодня о 18:00 (TODO: надсилати план напередодні зустрічі)

## Key Patterns

### Визначення групи по чату
Бот знаходить групу через `telegramGroupId == str(message.chat.id)`.
Поле `TelegramGroupId` заповнюється в CRM — бот надсилає його при вступі в групу.

### Telegram lookup для відповідальних
`build_telegram_map(people, admins)` → `dict[name.lower() → telegram_handle]`.
`resolve_responsible(name, map)` → `@handle` якщо є telegram, інакше name як є.
Якщо значення вже починається з `@` — використовується без змін.

### Attendance session
Не FSM — звичайний dict `sessions[chat_id]` з `AttendanceSession` dataclass.
Стан: `init` → `members` → `guests`. При рестарті бота сесії втрачаються.
"Повторна команда" перезаписує існуючу сесію.

### Автентифікація бота до API
Credentials суперадміна (`API_EMAIL`, `API_PASSWORD`). При 401 → автоматично перелогінюється.

### Polling mode
Не webhook. Простіше для деплою — не потрібен публічний endpoint.

## Environment Variables

```
BOT_TOKEN=your-telegram-bot-token-from-botfather
API_BASE_URL=http://api:8080          # внутрішній docker-compose адрес API
API_EMAIL=admin@example.com           # credentials для логіну до API
API_PASSWORD=your-password
```

`BOT_TOKEN` також потрібен в `api` сервісі docker-compose (для `send-to-telegram` endpoint).

## Backend API Used

```
POST /api/v1/auth/login
GET  /api/v1/groups
GET  /api/v1/groups/:id/cabinet
GET  /api/v1/groups/:id/plans/date/:date
GET  /api/v1/groups/:id/members
GET  /api/v1/groups/:id/events
GET  /api/v1/people
GET  /api/v1/admins
POST /api/v1/attendance
POST /api/v1/attendance/meta
```

## Deployment

```bash
# З бекенду — запускає api + db + bot
cd homegroup-crm-backend
docker compose up --build

# Тільки бот
docker compose up --build bot -d

# Логи
docker compose logs -f bot
```

## Development

```bash
cd homegroup-crm-telegrambot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
API_BASE_URL=http://localhost:8081 python -m bot.main
```

## What's Done

- [x] ApiClient з авто-реавторизацією (JWT, retry on 401)
- [x] APScheduler з timezone Europe/Kyiv
- [x] Docker деплой як сервіс в docker-compose бекенду
- [x] При вступі в групу — надсилає chat ID для CRM
- [x] /plan — форматований план зустрічі з @telegram lookup, футером
- [x] /attendance — inline FSM: toggle members → guest count → summary → save to CRM
- [x] Auto-trigger attendance через 1 год після початку зустрічі (scheduler, ±3 хв вікно)
- [x] notify_upcoming_events — о 09:00: події сьогодні + через 7 днів
- [x] /test_notify — ручний тригер сповіщень про події

## TODO

- [ ] notify_meeting_plan — автоматична відправка плану в групу напередодні зустрічі
- [ ] Сповіщення лідеру якщо не відмічена присутність
