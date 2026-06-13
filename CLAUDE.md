# HomeGroup CRM — Telegram Bot

Telegram-бот для HomeGroup CRM. Сповіщення групи, перегляд плану зустрічей, відмітка присутніх, управління групою з приватного чату, анонімне опитування, потреби.
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
    keyboards.py           — private_main_keyboard() + member_main_keyboard()
    notif_settings.py      — async API-делегат для toggles сповіщень (читає/записує через бекенд API)
    utils.py               — find_admin_by_telegram(), find_person_by_telegram()
    middlewares.py         — TelegramChatIdMiddleware: зберігає chat_id в CRM при кожному повідомленні
    handlers/
      __init__.py
      common.py            — /start, /help, /test_notify, /test_conflict
      attendance.py        — /attendance + auto-trigger (inline FSM flow)
      plans.py             — /plan (перегляд плану в груповому чаті)
      group_events.py      — my_chat_member: при вступі бота в групу надсилає chat ID
      stats.py             — /stats (статистика: 2 сторінки, перемикач місяців)
      private.py           — приватний чат: Відмітка присутніх, пріоритет prevScheduledMeetingDate
      private_plan.py      — приватний чат: Plan (перегляд + повний inline редактор)
      home_group.py        — приватний чат: Домашка (inline submenu кабінету)
      home_group_events.py — приватний чат: Події домашки (CRUD подій)
      members.py           — приватний чат: Учасники (список членів групи)
      profile.py           — приватний чат: Профіль (перегляд + редагування)
      help_handler.py      — приватний чат: Допомога (5 секцій з back nav + публічні main_text/main_kb)
      notif.py             — приватний чат: Сповіщення групи (6 toggles)
      needs.py             — Рандомна потреба + Додати потребу (FSM; адмін і член)
      record_needs.py      — /record_needs: flow запису потреб після зустрічі (FSM, ForceReply)
      member_thanks.py     — "Подякувати за молитву" для членів домашки
      anon_poll.py         — /anon_poll + анонімний catch-all forwarder (реєструється ОСТАННІМ)
    schedulers/
      __init__.py
      notifications.py     — APScheduler jobs (attendance, events, conflicts, record_needs)
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
- `get_group_events(group_id)`, `create_event(...)`, `update_event(...)`, `delete_event(...)`
- `get_group_stats(group_id, period)`
- `record_attendance(...)`, `save_attendance_meta(...)`
- `get_attendance(group_id, date)` → AttendanceResponse[] (для pre-load існуючих відміток)
- `get_attendance_summary(group_id)` → AttendanceSummary[] (для списку минулих дат)
- `skip_meeting(group_id)`, `set_next_meeting(group_id, date)`
- `get_group_needs(group_id)` → GroupNeedDto[]
- `update_need(group_id, need_id, payload)` → оновити статус/поля потреби
- `create_need(group_id, payload)` → створити потребу
- `set_person_telegram_chat_id(person_id, chat_id)` → PUT /people/:id/telegram-chat-id
- `set_admin_telegram_chat_id(admin_id, chat_id)` → PUT /admins/:id/telegram-chat-id
- `create_anon_poll(group_id, destination_chat_id)` → POST /api/v1/anon-polls
- `get_active_anon_poll(group_id)` → dict | None
- `close_anon_poll(poll_id)` → DELETE /api/v1/anon-polls/:id
- `get_notif_settings(group_id)`, `update_notif_settings(group_id, settings)`

Маппінг `_NOTIF_FROM_API` / `_NOTIF_TO_API` конвертує camelCase бекенду ↔ snake_case бота:
`eventSevenDays` ↔ `event_7days`, `eventDay` ↔ `event_day`, `conflict` ↔ `conflict`,
`conflictResolved` ↔ `conflict_resolved`, `attendanceAsk` ↔ `attendance_ask`,
`needsRecordingAsk` ↔ `needs_recording_ask`.

### Main Keyboards (`bot/keyboards.py`)

**Адмін** (`private_main_keyboard`):
```
[Рандомна потреба]  [Додати потребу]
[Профіль]           [Домашка]
[Відмітка присутніх][План]
[Сповіщення групи]  [Допомога]
```

**Член домашки** (`member_main_keyboard`):
```
[Рандомна потреба]  [Подякувати за молитву]
[Додати потребу]
```

### Router Order (`bot/main.py`)
ВАЖЛИВО: `anon_poll` реєструється **останнім** — його catch-all `forward_anon_message`
перехоплює будь-який приватний текст. Усі більш специфічні хендлери мають бути до нього:
```
common → help_handler → notif → profile → home_group → needs → member_thanks →
members → home_group_events → private_plan → private → attendance → plans →
group_events → stats → record_needs → anon_poll (LAST)
```

### Middleware (`bot/middlewares.py`)
`TelegramChatIdMiddleware` — реєструється через `dp.message.middleware(...)`.
На кожному приватному повідомленні: якщо username розпізнано і `chat_id` змінився від
закешованого — запускає фоновий `asyncio.create_task(_sync_chat_id(...))`.
In-memory кеш `_SYNCED_CHAT_IDS: dict[str, int]` запобігає повторним API-запитам.

### Private chat handlers
Всі приватні хендлери фільтруються через `F.chat.type == "private"`.
`_get_admin_group(message)` — спільна утиліта: знаходить адміна по `@username`, повертає `(admin, group_id)`.

**home_group.py** — кабінет домашки як inline submenu:
- `_overview_kb(group_id)` → inline кнопки: Статистика / Наступна домашка / Учасники /
  Події домашки / Записати потреби / Анонімне опитування / Налаштування
- Всі підрозділи мають кнопку `← Домашка` (callback: `hg_overview`)
- `hg_record_needs` → делегує в record_needs flow
- `hg_anon_poll` → делегує в anon_poll flow

**private_plan.py** — повний inline редактор плану (single-message UX):
- Показує план наступної домашки у форматі Telegram-повідомлення
- Кнопки: Змінити план / Очистити план / Відправити в групу / Створити план / З шаблону
- Редагування блоків: час, назва, опис, відповідальний, порядок
- **Single-message UX**: всі FSM стани зберігають `msg_id` → `bot.edit_message_text` + `bot.delete_message`
- Відповідальний: picker з адмінів групи або ввід вручну
- Порядок блоків: ↑↓ / На початок / В кінець — кожен рух одразу зберігається на API
- `_save_plan`: `time` завжди `""` якщо відсутній (не `null`)

**needs.py** — потреби для адмінів і членів:
- `btn_random_need`: для адміна — з кнопками статусів (nd_status_); для члена — тільки перегляд
- `btn_add_need` (адмін): picker → тип (член/гість) → ім'я → текст → save
- `btn_add_need` (член): simple text input → зберігає зі своїм `personId`
- FSM: `AddNeedStates.waiting_guest_name`, `waiting_need_text`

**record_needs.py** — запис потреб після зустрічі:
- Запускається з: `/record_needs` (груповий чат), `hg_record_needs` callback (приват), авто (scheduler)
- `ACTIVE_SESSIONS: dict[chat_id, {sid, msg_id, user_id}]` — одна сесія на чат
- **ForceReply pattern** (обхід Group Privacy mode): для введення тексту бот надсилає окреме
  `ForceReply(selective=True)` повідомлення. `_clear_prompt(bot, chat_id, state)` видаляє його.
- Picker: список членів з ✓ для вже записаних; кнопки "Гість", "Готово", "Скасувати"
- Звіт: групується по людях, telegram-посилання через `t.me/{username}`
- `meeting_date`: `prevScheduledMeetingDate` або `lastMeetingDate` або today

**member_thanks.py** — "Подякувати за молитву" (члени):
- Список власних активних потреб (personId == self, status == active)
- Картка потреби: [Отримано відповідь][Не актуальна][← Назад]
- Callback префікси: `th_open_`, `th_set_answered_`, `th_set_irrelevant_`, `th_back`

**help_handler.py** — 5 секцій:
- `help_main`, `help_connect`, `help_private`, `help_leaders`, `help_member`, `help_contact`
- Публічні враппери `main_text()` і `main_kb()` — для імпорту в `common.py` (уникнення circular import)
- `_PRIVATE_TEXT` — повний опис функцій адміна в приваті (всі пункти submenu)
- `_LEADERS_TEXT` — всі команди групового чату + автосповіщення
- `_MEMBER_TEXT` — функції члена: рандомна потреба, подяка, додати потребу, анонімне опитування

**anon_poll.py** — анонімне опитування:
- `/anon_poll` (груповий чат) → confirmation → create poll, `destinationChatId = group chat id`
- `hg_anon_poll` callback (приват адміна) → confirmation → create poll, `destinationChatId = admin's chat`
- `_notify_members`: надсилає NOTIF_TO_MEMBER всім членам (non-admin, non-former) з відомим TelegramChatId
- **catch-all `forward_anon_message`**: `F.chat.type == "private", F.text, ~F.text.startswith("/")`
  - Перевіряє `state.get_state() is None` (пропускає якщо mid-FSM — форма введення тексту)
  - Перевіряє admin і person (адміни теж можуть відправляти анонімно)
  - Пропускає якщо `int(dest) == message.chat.id` (самовідправка — адмін запустив в приват)
  - Форвардить як `📩 Анонімне:\n<text>`, відповідає `✓ Передано анонімно`

**common.py** — /start і /help:
- `GROUP_START_TEXT` — HTML, всі команди + автосповіщення групового чату
- `PRIVATE_KNOWN_TEXT` + `MEMBER_KNOWN_TEXT` — включають `{group_line}` (🏠 Твоя домашка: **name**)
- `_handle_private`: розгалуження admin vs person, обидва з parse_mode="HTML"
- `/help` у приваті → `help_main_text()` + `help_main_kb()`; в групі → GROUP_START_TEXT

### Notification Settings (`bot/notif_settings.py`)
Делегує до бекенд API (`GET/PUT /groups/:id/notif-settings`). Локальний JSON-файл більше не використовується.
- `get(group_id)` → `dict[str, bool]` (async, defaults all `True` при помилці)
- `toggle(group_id, key)` → async get + flip + update, повертає нові значення
- 6 ключів: `event_7days`, `event_day`, `conflict`, `conflict_resolved`, `attendance_ask`, `needs_recording_ask`

### Scheduler (`bot/schedulers/notifications.py`)
Всі job-и в timezone `Europe/Kyiv`. Кожен job перевіряє відповідний toggle через `ns.get(group_id)`.

- `check_auto_attendance` — щохвилини: `prevScheduledMeetingDate == today` + `meetingTime + 60 хв` (±3 хв)
  → тригерить attendance flow. Перевіряє `attendance_ask` toggle.
  **Важливо**: `prevScheduledMeetingDate` (не `nextMeeting`) — за 1 год після зустрічі schedule вже
  показує наступний тиждень.
- `notify_upcoming_events` — щодня о 09:00: події сьогодні + через 7 днів
  (перевіряє `event_day` і `event_7days` toggles)
- `check_conflicts` — щодня о 09:00: накладки домашки з іншими подіями, дедупліковано
  (перевіряє `conflict` і `conflict_resolved` toggles)
- `check_record_needs_prompt` — щохвилини: `prevScheduledMeetingDate == today` + `meetingEndTime - 30 хв`
  (±2 хв) → викликає `send_record_needs_prompt(bot, tg_id)`. Перевіряє `needs_recording_ask` toggle.
  Ключ дедупу: `(group_id, f"needs:{today_str}")`

### Utils (`bot/utils.py`)
- `find_admin_by_telegram(username)` → шукає в `get_admins()`, матчить `telegram` поле
- `find_person_by_telegram(username)` → шукає в `get_people()`, скіпає `isAdmin=True`,
  матчить `telegram` поле

## Key Patterns

### Визначення групи по чату (груповий чат)
Бот знаходить групу через `telegramGroupId == str(message.chat.id)`.

### FSM single-message UX (private_plan.py, home_group.py)
При вході у FSM state: `await state.update_data(msg_id=callback.message.message_id)`.
В text-handler: `bot.delete_message(chat_id, message.message_id)` + `bot.edit_message_text(...)`.
Весь flow залишається в одному повідомленні.

### ForceReply pattern (record_needs.py — груповий чат)
Group Privacy mode блокує plain text у груповому чаті. Рішення: бот надсилає окреме
`ForceReply(selective=True)` повідомлення, яке змушує юзера відповісти. Відповідь видно боту
навіть у закритому груповому чаті. `prompt_msg_id` зберігається в FSM state.
`_clear_prompt(bot, chat_id, state)` видаляє prompt перед наступним кроком.

### Пріоритет дати зустрічі
`meeting_date = cabinet.get("prevScheduledMeetingDate") or cabinet.get("lastMeetingDate")`
Вживається в `private.py btn_attendance` і `record_needs.py cb_start`.

### TelegramChatId відстеження
Middleware автоматично персистить `chat_id` при кожному приватному повідомленні.
Використовується `anon_poll` для надсилання сповіщень членам без lookup через username.

### Callback prefixes
- `pp_*` — private_plan.py (план)
- `hg_*` — home_group.py (кабінет)
- `nd_status_`, `nd_undo_`, `addn_*` — needs.py (потреби)
- `rn_*` — record_needs.py (запис потреб, session-based: `rn_{sid}_*`)
- `th_*` — member_thanks.py (подяка за молитву)
- `ap_*` — anon_poll.py (анонімне опитування: `ap_cancel`, `ap_go_{group_id}_{dest_chat_id}`)
- `help_*` — help_handler.py
- `notif_*` — notif.py (сповіщення)

### Telegram lookup для відповідальних (plans.py / private_plan.py)
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
GET/POST/PUT/DELETE /api/v1/groups/:id/needs/:needId
GET  /api/v1/people,  GET/PUT /api/v1/people/:id
PUT  /api/v1/people/:id/telegram-chat-id
GET  /api/v1/admins,  GET/PUT /api/v1/admins/:id
PUT  /api/v1/admins/:id/profile
PUT  /api/v1/admins/:id/telegram-chat-id
PUT  /api/v1/groups/:id/next-meeting
PUT  /api/v1/groups/:id/skip-meeting
POST /api/v1/attendance
POST /api/v1/attendance/meta
GET/PUT /api/v1/groups/:id/notif-settings
POST /api/v1/anon-polls
GET  /api/v1/anon-polls/active?homeGroupId=
DELETE /api/v1/anon-polls/:id
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
- [x] Docker деплой як сервіс в docker-compose бекенду
- [x] При вступі в групу — надсилає chat ID для CRM
- [x] /plan (груповий чат) — форматований план з @telegram lookup і футером
- [x] /attendance — inline FSM: toggle members → guest count → summary → save
- [x] Auto-trigger attendance через 1 год після початку зустрічі
- [x] notify_upcoming_events — о 09:00: події сьогодні + через 7 днів
- [x] check_conflicts — о 09:00: накладки домашки, дедупліковано
- [x] /stats — статистика за 1/3/6 місяців, 2 сторінки, stateless inline keyboard
- [x] Приватний чат: Профіль, Учасники (всі в inline submenu Домашка)
- [x] Приватний чат: Відмітка присутніх, Статистика
- [x] Приватний чат: Події домашки — повний CRUD (FSM, back nav)
- [x] Приватний чат: План — перегляд + повний inline редактор (single-message UX)
  - [x] Додати/видалити/редагувати блок (час, назва, опис, відповідальний)
  - [x] Зміна порядку блоків (↑↓, на початок/кінець)
  - [x] Створити план / Створити з шаблону
  - [x] Очистити план (з підтвердженням)
  - [x] Відправити план у Telegram-групу
- [x] Приватний чат: Допомога — 5 секцій (підключення, адмін-приват, лідери, член, контакт)
- [x] Приватний чат: Сповіщення групи — 6 toggles (зберігаються в бекенд API)
  - event_7days, event_day, conflict, conflict_resolved, attendance_ask, needs_recording_ask
- [x] WEBSITE_URL env var — відображається в розділі Допомога
- [x] notif_settings.py делегує до бекенд API замість локального JSON-файлу
- [x] Schedulers перевіряють відповідний toggle перед кожним типом сповіщення
- [x] /attendance flow редизайн — 3-кнопкове меню: поточна дата / минула дата / скасувати
      - pre-load існуючої відвідуваності, pre-check вже присутніх
      - Filter out former group members (isFormer=true)
- [x] check_auto_attendance використовує `prevScheduledMeetingDate` (не `nextMeeting`)
- [x] Пріоритет дат: `prevScheduledMeetingDate` > `lastMeetingDate` в attendance + record_needs
- [x] Домашка inline submenu: Статистика / Наступна домашка / Учасники / Події / Записати потреби /
      Анонімне опитування / Налаштування. Кнопка `← Домашка` в кожному розділі.
- [x] Рандомна потреба: для адміна — з кнопками статусів + Скасувати (undo);
      для члена — тільки перегляд
- [x] Додати потребу (адмін): FSM picker → член/гість → ім'я → текст → save
- [x] Додати потребу (член): simple text → save зі своїм personId
- [x] /record_needs: інтерактивний flow запису потреб після зустрічі
  - ForceReply для введення тексту в груповому чаті (обхід Group Privacy)
  - Picker з ✓ для вже записаних членів
  - Кнопки: вибрати члена / гість / готово / скасувати
  - Звіт з telegram-посиланнями (t.me/{username})
  - Авто-тригер за 30 хв до meetingEndTime (toggle: needs_recording_ask)
- [x] Подякувати за молитву (член): власні активні потреби → змінити статус
- [x] Анонімне опитування:
  - /anon_poll в груповому чаті → destination = group chat
  - hg_anon_poll в приваті → destination = admin's private chat
  - Сповіщення членів (non-admin, non-former, з TelegramChatId)
  - Форвардинг анонімних повідомлень (адміни теж можуть; FSM check; self-forward prevention)
- [x] TelegramChatIdMiddleware: автоматично персистить chat_id при приватних повідомленнях
- [x] find_person_by_telegram(): скіпає isAdmin=True
- [x] Вітання /start показує домашку: 🏠 Твоя домашка: <name>
- [x] Клавіатура члена: Рандомна потреба / Подякувати за молитву / Додати потребу

## TODO

- [ ] notify_meeting_plan — автоматична відправка плану в групу напередодні зустрічі
- [ ] Сповіщення лідеру якщо не відмічена присутність
