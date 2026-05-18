# HomeGroup CRM — Telegram Bot

Telegram-бот для HomeGroup CRM. Сповіщення групи, перегляд плану зустрічей, відмітка присутніх, управління групою з приватного чату.
Запускається як окремий сервіс у тому ж docker-compose що і бекенд.

## Tech Stack

- **Python**: 3.12
- **Bot framework**: aiogram 3.x (async, inline keyboards, FSM)
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
    keyboards.py           — private_main_keyboard() — головна ReplyKeyboard
    notif_settings.py      — persistent JSON storage для toggles сповіщень (data/notif_settings.json)
    utils.py               — find_admin_by_telegram(username) → dict | None
    handlers/
      __init__.py
      common.py            — /start, /help, /test_notify, /test_conflict
      attendance.py        — /attendance + auto-trigger (inline FSM flow)
      plans.py             — /plan (перегляд плану в груповому чаті)
      group_events.py      — my_chat_member: при вступі бота в групу надсилає chat ID
      stats.py             — /stats (статистика: 2 сторінки, перемикач місяців)
      private.py           — приватний чат: Відмітка присутніх, Статистика
      private_plan.py      — приватний чат: Plan (перегляд + повний inline редактор)
      home_group.py        — приватний чат: Домашка (налаштування групи)
      home_group_events.py — приватний чат: Події домашки (CRUD подій)
      members.py           — приватний чат: Учасники (список членів групи)
      profile.py           — приватний чат: Профіль (перегляд + редагування)
      help_handler.py      — приватний чат: Допомога (4 секції з back nav)
      notif.py             — приватний чат: Сповіщення групи (5 toggles)
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
- `get_groups()`, `get_group(group_id)`, `update_group(group_id, payload)`
- `get_cabinet(group_id)` → `GroupCabinetResponse`
- `get_plan(group_id, date)` → `HomeMeetingPlan | None`
- `save_plan(group_id, payload)` → upsert плану
- `delete_plan(group_id, date)` → видалити план
- `get_plan_templates()` → список глобальних шаблонів
- `send_plan_to_telegram(group_id, date)` → POST send-to-telegram
- `get_people()`, `get_person(person_id)`, `update_person(person_id, payload)`
- `get_admins()`, `get_admin(admin_id)`, `update_profile(admin_id, payload)`
- `get_group_members(group_id)` → Person + User з `isAdmin` флагом
- `get_group_events(group_id)`, `create_event(group_id, data)`, `update_event(group_id, event_id, data)`, `delete_event(group_id, event_id)`
- `get_group_stats(group_id, period)`
- `record_attendance(...)`, `save_attendance_meta(...)`
- `skip_meeting(group_id)`, `set_next_meeting(group_id, date)`

### Main Keyboard (`bot/keyboards.py`)
```
[Профіль]        [Домашка]
[Відмітка присутніх] [Статистика]
[План]           [Наступна домашка]
[Учасники]       [Події домашки]
[Сповіщення групи]  [Допомога]
```

### Private chat handlers
Всі приватні хендлери фільтруються через `F.chat.type == "private"`.
`_get_admin_group(message)` — спільна утиліта: знаходить адміна по `@username`, повертає `(admin, group_id)`.

**private_plan.py** — повний inline редактор плану (single-message UX):
- Показує план наступної домашки у форматі Telegram-повідомлення
- Кнопки: Змінити план / Очистити план / Відправити в групу / Створити план / З шаблону
- Редагування блоків: час, назва, опис, відповідальний, порядок
- **Single-message UX**: всі FSM стани зберігають `msg_id` → `bot.edit_message_text` + `bot.delete_message` для вводу
- Відповідальний: picker з адмінів групи або ввід вручну
- Порядок блоків: ↑↓ / На початок / В кінець — кожен рух одразу зберігається на API
- `_save_plan`: `time` завжди `""` якщо відсутній (не `null` — `SavePlanBlockRequest.Time` non-nullable)

**home_group_events.py** — CRUD подій групи:
- Показує 5 найближчих подій + кнопки "Показати всі" / "Редагувати"
- Дата вводиться як `dd.mm` або `dd.mm.yyyy`

**help_handler.py** — 4 секції з back nav (`help_main`, `help_connect`, `help_private`, `help_leaders`, `help_contact`)

**notif.py** — 5 toggles сповіщень (зберігаються в `data/notif_settings.json`):
- `event_7days`, `event_day`, `conflict`, `conflict_resolved`, `attendance_ask`
- Кожен toggle: ✅/❌ в заголовку рядка в повідомленні + кнопка з коротким іменем

### Notification Settings (`bot/notif_settings.py`)
Persistent storage у `data/notif_settings.json` (Docker volume `bot_data:/app/data`).
- `get(group_id)` → `dict[str, bool]` (defaults all `True`)
- `toggle(group_id, key)` → оновлює і повертає нові значення

### Scheduler (`bot/schedulers/notifications.py`)
Всі job-и в timezone `Europe/Kyiv`.

- `check_auto_attendance` — щохвилини: якщо `meetingTime + 60 хв` (±3 хв) → тригерить attendance flow
- `notify_upcoming_events` — щодня о 09:00: події сьогодні + через 7 днів
- `check_conflicts` — щодня о 09:00: накладки домашки з іншими подіями, дедупліковано
- `notify_meeting_plan` — щодня о 18:00 (TODO)

## Key Patterns

### Визначення групи по чату (груповий чат)
Бот знаходить групу через `telegramGroupId == str(message.chat.id)`.

### FSM single-message UX (private_plan.py)
При вході у FSM state (через callback): `await state.update_data(msg_id=callback.message.message_id)`.
В text-handler: `bot.delete_message(chat_id, message.message_id)` + `bot.edit_message_text(chat_id=..., message_id=data["msg_id"], ...)`.
Так весь flow залишається в одному повідомленні.

### Callback prefixes (private_plan.py)
- `pp_reload_`, `pp_edit_` — перезавантаження/відкриття списку блоків
- `pp_eblk_{gid}_{order}` — картка блоку
- `pp_btime_`, `pp_btitle_`, `pp_binfo_`, `pp_bresp_` — редагування поля блоку
- `pp_bdel_`, `pp_bdelok_` — видалення блоку
- `pp_border_`, `pp_bord_{dir}_{gid}_{order}` — reorder (dir: up/dn/tp/bt)
- `pp_badd_` — додати блок
- `pp_create_`, `pp_template_`, `pp_tmpl_` — створення плану
- `pp_clear_`, `pp_clearok_` — очистити план
- `pp_send_` — відправити в групу
- `pp_respsel_{uid}` — вибір відповідального

### Telegram lookup для відповідальних
`build_telegram_map(people, admins)` → `dict[name.lower() → @handle]`.

### Автентифікація бота до API
Credentials суперадміна (`API_EMAIL`, `API_PASSWORD`). При 401 → автоматично перелогінюється.

## Environment Variables

```
BOT_TOKEN=your-telegram-bot-token-from-botfather
API_BASE_URL=http://api:8080          # внутрішній docker-compose адрес API
API_EMAIL=admin@example.com
API_PASSWORD=your-password
WEBSITE_URL=https://your-site.com    # опційно — відображається в /Допомога
```

Задаються в `homegroup-crm-backend/.env` і передаються в контейнер через docker-compose.
`BOT_TOKEN` також потрібен в `api` сервісі (для `send-to-telegram` endpoint).

## Backend API Used

```
POST /api/v1/auth/login
GET  /api/v1/groups,  GET/PUT /api/v1/groups/:id
GET  /api/v1/groups/:id/cabinet
GET  /api/v1/groups/:id/plans/date/:date
POST /api/v1/groups/:id/plans
DELETE /api/v1/groups/:id/plans/date/:date
POST /api/v1/groups/:id/plans/date/:date/send-to-telegram
GET  /api/v1/plan-templates
GET  /api/v1/groups/:id/members
GET/POST/PUT/DELETE /api/v1/groups/:id/events/:eventId
GET  /api/v1/groups/:id/stats?period=1m|3m|6m
GET  /api/v1/people,  GET/PUT /api/v1/people/:id
GET  /api/v1/admins,  GET/PUT /api/v1/admins/:id
PUT  /api/v1/admins/:id/profile
PUT  /api/v1/groups/:id/next-meeting
PUT  /api/v1/groups/:id/skip-meeting
POST /api/v1/attendance
POST /api/v1/attendance/meta
```

## Deployment

```bash
# З бекенду — запускає api + db + bot
cd homegroup-crm-backend
git pull && cd ../homegroup-crm-telegrambot && git pull && cd ../homegroup-crm-backend
docker compose up --build -d

# Тільки бот (після змін в telegrambot репо)
cd ~/homegroup-crm-telegrambot && git pull
cd ~/homegroup-crm-backend && docker compose up --build -d bot

# Логи
docker compose logs -f bot
```

## What's Done

- [x] ApiClient з авто-реавторизацією (JWT, retry on 401)
- [x] APScheduler з timezone Europe/Kyiv
- [x] Docker деплой як сервіс в docker-compose бекенду, volume `bot_data` для notif_settings.json
- [x] При вступі в групу — надсилає chat ID для CRM
- [x] /plan (груповий чат) — форматований план з @telegram lookup і футером
- [x] /attendance — inline FSM: toggle members → guest count → summary → save
- [x] Auto-trigger attendance через 1 год після початку зустрічі
- [x] notify_upcoming_events — о 09:00: події сьогодні + через 7 днів
- [x] check_conflicts — о 09:00: накладки домашки, дедупліковано
- [x] /stats — статистика за 1/3/6 місяців, 2 сторінки, stateless inline keyboard
- [x] Приватний чат: Профіль, Домашка, Учасники, Наступна домашка
- [x] Приватний чат: Відмітка присутніх, Статистика
- [x] Приватний чат: Події домашки — повний CRUD (FSM, back nav)
- [x] Приватний чат: План — перегляд + повний inline редактор (single-message UX)
  - [x] Додати/видалити/редагувати блок (час, назва, опис, відповідальний)
  - [x] Зміна порядку блоків (↑↓, на початок/кінець)
  - [x] Створити план / Створити з шаблону
  - [x] Очистити план (з підтвердженням)
  - [x] Відправити план у Telegram-групу
- [x] Приватний чат: Допомога — 4 секції (підключення, приватний, лідери, контакт)
- [x] Приватний чат: Сповіщення групи — 5 persistent toggles (JSON файл)
- [x] WEBSITE_URL env var — відображається в розділі Допомога

## TODO

- [ ] notify_meeting_plan — автоматична відправка плану в групу напередодні зустрічі
- [ ] Використовувати notif_settings toggles в schedulers (зараз ігноруються)
- [ ] Сповіщення лідеру якщо не відмічена присутність
