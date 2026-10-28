# Telegram Helpdesk Router

Асинхронный бот технической поддержки для Telegram: пользователь создаёт обращение в личном чате, тикет уходит в нужную админ-группу, а ответ администратора возвращается автору. Состояние хранится в Upstash Redis (REST), приложение работает как Telegram webhook на Vercel Serverless Functions.

Проект рассчитан на несколько очередей поддержки одновременно: общие вопросы, техническая поддержка, оплата или любые другие категории. Для каждой категории можно указать отдельный чат и, при необходимости, тему (topic) форума.

## Возможности

- Создание тикетов через `/start` и выбор категории inline-кнопкой.
- Маршрутизация в несколько админ-чатов и тем форума через `TICKET_ROUTES_JSON`.
- Двусторонняя переписка: ответ администратора в группе доставляется пользователю в личный чат.
- Дополнение открытого тикета сообщениями пользователя без создания нового обращения.
- Публичный номер тикета `#TKT-0123456789ABCDEF` для ссылок и ручного закрытия.
- Админ-команды `/close`, `/ban`, `/unban`, `/admin_help`.
- Строгая проверка прав: команды доступны только в разрешённых чатах и только пользователям из белого списка.
- Бан пользователя с закрытием всех его открытых тикетов.
- Ограничение частоты сообщений, защита от повторной обработки Telegram-обновлений.
- HTML-экранирование пользовательского текста и отсутствие секретов в логах.
- Хранение только SHA-256 хеша reply-токена; сам токен в Redis не попадает.
- Готовые тесты, линтер и GitHub Actions CI.

## Архитектура

```text
Пользователь
    │  /start, текст обращения
    ▼
Telegram Bot API
    │  POST /webhook + X-Telegram-Bot-Api-Secret-Token
    ▼
Vercel Serverless Function (FastAPI + aiogram)
    │
    ├── User handlers ── создание тикета, дополнения, выбор категории
    ├── Admin handlers ─ ответы, /close, /ban, /unban
    ├── HelpdeskService ─ бизнес-логика и маршрутизация
    └── Upstash Redis ── тикеты, reply-индексы, сессии, баны, rate limit
    │
    ▼
Админ-группа general / tech / billing
```

Тикет не хранит открытый reply-токен. При создании обращения генерируется 256-битный токен, от него считается SHA-256, и в Redis сохраняется только хеш. Публичный ID тикета — первые 16 hex-символов хеша в верхнем регистре. Обратный маршрут «сообщение бота в админ-группе → тикет» строится по ключу `(chat_id, message_id)`, поэтому ответ администратора на любое сообщение с тикетом однозначно определяет пользователя.

### Жизненный цикл обращения

1. Пользователь вызывает `/start` или `/new`, выбирает категорию.
2. Категория сохраняется в Redis с TTL; следующее текстовое сообщение создаёт тикет.
3. Бот отправляет карточку тикета в чат маршрута и индексирует `message_id` этого сообщения.
4. Ответ администратора на карточку (или на любое follow-up-сообщение) уходит пользователю.
5. Сообщения пользователя при открытом тикете добавляются в него и дублируются в админ-чат.
6. `/close` закрывает тикет, очищает активную ссылку и уведомляет обе стороны.
7. `/ban` блокирует пользователя, закрывает его открытые тикеты и запрещает новые сообщения.

## Структура проекта

```text
telegram-helpdesk-router/
├── main.py                      # FastAPI: /webhook, /health, middleware
├── bot/
│   ├── config.py                # настройки, маршруты, проверка готовности
│   ├── runtime.py               # сборка Dispatcher, обработка update, dedup
│   ├── models.py                # Ticket, UserProfile, BanRecord
│   ├── security.py              # токены, SHA-256, HTML escaping
│   ├── texts.py                 # тексты сообщений на русском
│   ├── keyboards.py             # inline-клавиатуры
│   ├── filters/access.py        # фильтры админов и бан-фильтр
│   ├── handlers/user.py         # пользовательские сценарии
│   ├── handlers/admin.py        # команды и ответы администраторов
│   ├── services/helpdesk.py     # бизнес-логика тикетов
│   └── storage/                 # Redis REST и in-memory хранилище для тестов
├── scripts/
│   ├── set_webhook.py           # установка/проверка/удаление webhook
│   └── smoke_test.py            # проверка задеплоенного приложения
├── tests/                       # unit и integration тесты
├── vercel.json                  # rewrites, лимиты функции, заголовки
├── requirements.txt
└── .env.example
```

## Требования

- Python 3.11+ (в проекте закреплён Python 3.12).
- Бот, созданный в [@BotFather](https://t.me/BotFather).
- Админ-группа или супергруппа Telegram, куда добавлен бот.
- База Upstash Redis с включённым REST API.
- Аккаунт Vercel и Vercel CLI для деплоя.
- `gh` (GitHub CLI) — опционально, для публикации репозитория.

## Настройка Telegram

1. Создайте бота через `@BotFather` командой `/newbot` и сохраните токен.
2. Создайте группу поддержки, добавьте бота и выдайте ему права администратора (как минимум отправка сообщений и чтение истории).
3. Отключите privacy mode у бота: `@BotFather` → `/setprivacy` → выберите бота → `Disable`. Иначе бот может не получать часть сообщений в группе.
4. Узнайте ID группы. Отрицательный ID вида `-100...` можно получить, отправив сообщение в группу и открыв:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` — в ответе будет `chat.id`.
5. Узнайте Telegram ID администраторов через `@userinfobot` и перечислите их в `ADMIN_USER_IDS`.
6. Если используются темы форума, включите в группе режим тем и укажите `message_thread_id` нужной темы в маршруте.

Бот должен быть участником каждого чата из маршрутов. Для закрытых групп добавьте его заранее.

## Переменные окружения

Скопируйте `.env.example` в `.env` для локальных скриптов. На Vercel эти же значения задаются в настройках проекта (Production и, при необходимости, Preview).

| Переменная | Обязательна | По умолчанию | Назначение |
|---|---:|---|---|
| `BOT_TOKEN` | да | — | Токен бота от `@BotFather`. |
| `TELEGRAM_WEBHOOK_SECRET` | да | — | Секрет webhook, 16–256 символов `[A-Za-z0-9_-]`. Передаётся Telegram и проверяется на каждом запросе. |
| `DEFAULT_ADMIN_CHAT_ID` | да | `0` | Отрицательный ID группы по умолчанию. Используется, если маршрут не задаёт `chat_id`. |
| `ADMIN_USER_IDS` | да | пусто | Telegram ID администраторов через запятую. Пустой список полностью запрещает админ-команды. |
| `TICKET_ROUTES_JSON` | нет | пусто | JSON-объект с маршрутами. Пустое значение создаёт `general`, `tech`, `billing` в чате по умолчанию. |
| `UPSTASH_REDIS_REST_URL` | да | — | HTTPS URL базы Upstash Redis. |
| `UPSTASH_REDIS_REST_TOKEN` | да | — | Токен Upstash Redis REST. |
| `REDIS_KEY_PREFIX` | нет | `helpdesk` | Префикс ключей, `^[a-z][a-z0-9_-]{1,31}$`. |
| `REDIS_TIMEOUT_SECONDS` | нет | `5` | Таймаут запросов к Redis, 0–30 секунд. |
| `ENVIRONMENT` | нет | `production` | `production`, `development` или `test`. |
| `LOG_LEVEL` | нет | `INFO` | Уровень JSON-логов. |
| `RATE_LIMIT_WINDOW_SECONDS` | нет | `600` | Окно rate limit в секундах. |
| `RATE_LIMIT_MAX_MESSAGES` | нет | `12` | Максимум сообщений пользователя за окно. |
| `PENDING_CATEGORY_TTL_SECONDS` | нет | `1800` | Сколько секунд действует выбранная категория до отправки текста. |
| `TICKET_TTL_SECONDS` | нет | `2592000` | Срок жизни тикета в Redis (30 дней). |
| `BAN_TTL_SECONDS` | нет | `31536000` | Срок жизни бана (365 дней). |
| `TELEGRAM_API_TIMEOUT_SECONDS` | нет | `20` | Таймаут запросов к Telegram Bot API. |
| `WEBHOOK_MAX_BODY_BYTES` | нет | `1048576` | Максимальный размер тела webhook по `Content-Length`. |
| `UPDATE_LOCK_SECONDS` | нет | `120` | Блокировка update_id от параллельной обработки. |
| `UPDATE_DEDUPLICATION_TTL_SECONDS` | нет | `86400` | Сколько хранится отметка об обработанном update_id. |
| `USER_TICKET_HISTORY_LIMIT` | нет | `50` | Сколько последних тикетов пользователя хранить. |
| `MAX_USER_MESSAGE_LENGTH` | нет | `3000` | Максимальная длина сообщения пользователя. |
| `MAX_ADMIN_MESSAGE_LENGTH` | нет | `4000` | Максимальная длина ответа администратора. |
| `PUBLIC_BASE_URL` | нет | — | Базовый URL для `scripts/set_webhook.py` и `scripts/smoke_test.py`. |

Сгенерировать webhook-секрет:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Маршруты

Пустой `TICKET_ROUTES_JSON` создаёт три категории в `DEFAULT_ADMIN_CHAT_ID`:

```json
{
  "general": {"title": "Общие вопросы", "emoji": "💬"},
  "tech": {"title": "Техническая поддержка", "emoji": "🛠"},
  "billing": {"title": "Оплата и биллинг", "emoji": "💳"}
}
```

Пример с отдельными чатами и темами форума:

```json
{
  "general": {
    "title": "Общие вопросы",
    "emoji": "💬",
    "chat_id": -1001111111111
  },
  "tech": {
    "title": "Техническая поддержка",
    "emoji": "🛠",
    "chat_id": -1002222222222,
    "message_thread_id": 42,
    "description": "Ошибки, доступы, интеграции"
  },
  "billing": {
    "title": "Оплата и биллинг",
    "emoji": "💳",
    "chat_id": -1003333333333
  }
}
```

Правила валидации:

- ключ категории: `^[a-z][a-z0-9_]{1,31}$`, максимум 8 маршрутов;
- `chat_id` — отрицательный ID группы или супергруппы;
- `message_thread_id` — положительный ID темы, необязателен;
- `title`, `emoji`, `description` — необязательные строки;
- неизвестные поля в маршруте приводят к ошибке конфигурации, а не игнорируются.

## Локальный запуск

```powershell
git clone https://github.com/<owner>/telegram-helpdesk-router.git
cd telegram-helpdesk-router

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

Copy-Item .env.example .env
# заполните .env
```

Запуск FastAPI локально:

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Проверка:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Для реального Telegram webhook нужен публичный HTTPS-адрес. Локально удобно использовать Cloudflare Tunnel или ngrok:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
python scripts/set_webhook.py --url https://<tunnel-domain>
```

Не оставляйте локальный webhook включённым после тестов: `python scripts/set_webhook.py --delete`.

## Деплой на Vercel

```powershell
npm.cmd install -g vercel
vercel.cmd login
vercel.cmd link
```

Добавьте переменные окружения. Удобнее всего через панель Vercel: Project → Settings → Environment Variables. Для автоматизации:

```powershell
"<value>" | vercel.cmd env add BOT_TOKEN production
"<value>" | vercel.cmd env add TELEGRAM_WEBHOOK_SECRET production
"<value>" | vercel.cmd env add DEFAULT_ADMIN_CHAT_ID production
"<value>" | vercel.cmd env add ADMIN_USER_IDS production
"<value>" | vercel.cmd env add UPSTASH_REDIS_REST_URL production
"<value>" | vercel.cmd env add UPSTASH_REDIS_REST_TOKEN production
```

Деплой:

```powershell
vercel.cmd --prod --yes
```

`vercel.json` уже содержит:

- rewrites `/webhook` → `/api/webhook` и `/health` → `/api/health`;
- лимит функции 30 секунд и 1024 MB;
- исключение тестов и скриптов из бандла;
- заголовки `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store`.

FastAPI одновременно обслуживает `/webhook` и `/api/webhook`, поэтому маршрут работает и при прямом обращении, и после rewrite.

После деплоя проверьте:

```powershell
curl.exe https://<project>.vercel.app/health
```

Ожидаемый ответ при корректной конфигурации:

```json
{"ok":true,"service":"telegram-helpdesk-router","version":"1.0.0","ready":true}
```

`ready: false` означает, что не заданы или некорректны обязательные переменные. Подробности пишутся в JSON-логи Vercel; наружу секреты не отдаются.

## Установка webhook

```powershell
python scripts/set_webhook.py --url https://<project>.vercel.app
```

Скрипт вызывает `setWebhook` с `secret_token`, `allowed_updates=["message", "callback_query"]` и `max_connections=40`.

Другие режимы:

```powershell
python scripts/set_webhook.py --info
python scripts/set_webhook.py --url https://<project>.vercel.app --dry-run
python scripts/set_webhook.py --delete
python scripts/set_webhook.py --url https://<project>.vercel.app --drop-pending
```

Проверка задеплоенного приложения:

```powershell
python scripts/smoke_test.py --url https://<project>.vercel.app
```

Скрипт проверяет `/health` и убеждается, что `/webhook` без секрета возвращает `403` (или `503`, если сервис ещё не сконфигурирован).

## Команды

### Пользователь

| Команда | Действие |
|---|---|
| `/start` | Приветствие и выбор категории. |
| `/new` | Новое обращение. |
| `/cancel` | Отмена выбора категории. |
| `/help` | Справка. |
| Любой текст | Создание тикета или дополнение активного обращения. |

Пользователь может отправить только текст. Фото, документы, голосовые и стикеры отклоняются с подсказкой.

### Администратор

| Команда | Действие |
|---|---|
| Ответ на сообщение с тикетом | Доставка ответа пользователю. |
| `/close` | Закрыть тикет ответом на него. |
| `/close #TKT-…` | Закрыть тикет по публичному ID. |
| `/ban [причина]` | Забанить автора тикета; работает только ответом. |
| `/unban` | Снять бан; работает только ответом на тикет. |
| `/admin_help` | Справка по админ-командам. |

Одновременно использовать reply и аргумент в `/close` нельзя. `/ban` и `/unban` намеренно требуют reply, чтобы нельзя было заблокировать произвольного пользователя по угаданному ID.

Ограничения доступа:

- сообщение должно прийти из чата, который указан в маршрутах;
- автор сообщения должен входить в `ADMIN_USER_IDS`;
- боты и анонимные администраторы не проходят проверку;
- тикет, принадлежащий другому админ-чату, нельзя закрыть или прокомментировать — доступ отклоняется и логируется.

## Безопасность

- **Секрет webhook.** Telegram присылает `X-Telegram-Bot-Api-Secret-Token`; сравнение выполняется в постоянном времени. Без секрета — `403`.
- **Content-Type.** Принимается только `application/json`; иначе `415`.
- **Размер тела.** Проверяется `Content-Length`; превышение — `413`.
- **Идемпотентность.** Каждый `update_id` захватывается в Redis на `UPDATE_LOCK_SECONDS`. Повторный обработанный update игнорируется, параллельный — получает `503` с `Retry-After`.
- **Fail-closed доступ.** Пустой `ADMIN_USER_IDS` означает, что админ-команды недоступны никому. Фильтры применяются до обработчиков.
- **Изоляция маршрутов.** Тикет можно открыть только из чата, в который он был отправлен.
- **Баны.** Проверяются middleware для сообщений и callback-кнопок; забаненный пользователь не может создать тикет или нажать кнопку.
- **Rate limit.** Атомарный `INCR` + `EXPIRE` в Redis ограничивает поток сообщений.
- **HTML.** Пользовательский текст экранируется перед вставкой в `parse_mode=HTML`; длинные ответы разбиваются без разрыва HTML-сущностей.
- **Токены.** Reply-токен не сохраняется. В Redis лежит только SHA-256 хеш; публичный ID — префикс хеша.
- **Логи.** JSON-логи содержат `ticket_id`, `user_id`, `admin_chat_id`, но не токены и не текст сообщений. Health-эндпоинт не раскрывает значения переменных.
- **Секреты.** `.env` исключён из git и из бандла Vercel. Не коммитьте реальные токены.

Важно: секрет webhook — единственный механизм аутентификации запросов. Telegram не публикует стабильный список IP-адресов, поэтому IP-allowlist здесь не используется. При компрометации токена бота или секрета перевыпустите их и заново вызовите `set_webhook.py`.

## Хранение данных

Ключи Redis (с префиксом `REDIS_KEY_PREFIX`):

| Ключ | Содержимое | TTL |
|---|---|---|
| `ticket:{token_hash}` | JSON тикета | `TICKET_TTL_SECONDS` |
| `ticket_id:{ticket_id}` | `token_hash` | `TICKET_TTL_SECONDS` |
| `reply:{chat_id}:{message_id}` | `token_hash` | `TICKET_TTL_SECONDS` |
| `active:{user_id}` | `token_hash` активного тикета | `TICKET_TTL_SECONDS` |
| `pending:{user_id}` | выбранная категория | `PENDING_CATEGORY_TTL_SECONDS` |
| `user:{user_id}:tickets` | список `token_hash` | `TICKET_TTL_SECONDS` |
| `rate:{user_id}` | счётчик сообщений | `RATE_LIMIT_WINDOW_SECONDS` |
| `ban:{user_id}` | JSON бана | `BAN_TTL_SECONDS` |
| `update:{update_id}` | `processing` / `done` | lock / dedup TTL |

Upstash должен быть доступен по HTTPS. Для production используйте отдельную базу или уникальный префикс, чтобы не пересекаться с другими проектами.

## Тесты и линтер

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```

Покрыты:

- валидация конфигурации и маршрутов;
- генерация токенов, нормализация ID, HTML-escaping;
- in-memory хранилище и жизненный цикл update;
- разрешение тикета по reply и по публичному ID;
- изоляция админ-чатов;
- сквозной сценарий «пользователь → админ → ответ → закрытие»;
- отказ в закрытии тикета пользователю вне белого списка;
- проверка секрета, Content-Type и тела webhook.

CI workflow находится в `.github/workflows/ci.yml` и запускает линтер и тесты на Python 3.12 при push и pull request.

## Ограничения

- Только текст: вложения не пересылаются.
- Нет полноценного FSM: состояние категории и активного тикета хранится в Redis, а не в памяти процесса.
- Один активный указатель на пользователя: создание нового тикета заменяет `active:{user_id}`, старый тикет остаётся открытым до `/close`.
- После истечения `TICKET_TTL_SECONDS` тикет нельзя закрыть или разбанить через reply — запись удалена.
- Команды работают только для обычных пользователей; анонимные администраторы и боты отклоняются.
- Vercel ограничивает время выполнения функции и размер запроса; очень большие сообщения и медленный Telegram API могут привести к таймауту.
- In-memory хранилище предназначено только для тестов: в serverless-окружении процессы не разделяют память.

## Диагностика

| Симптом | Что проверить |
|---|---|
| `/health` возвращает `ready: false` | Все обязательные переменные заданы? `DEFAULT_ADMIN_CHAT_ID` отрицательный? `TICKET_ROUTES_JSON` валиден? |
| Webhook отвечает `403` | Совпадает ли `TELEGRAM_WEBHOOK_SECRET` на Vercel и в `setWebhook`? |
| Webhook отвечает `503` | Redis недоступен, конфигурация неполная или update уже обрабатывается. |
| Бот молчит в группе | Бот добавлен в группу, является администратором, privacy mode отключён. |
| Ответ администратора не доходит | Ответ отправлен именно на сообщение бота с `#TKT-…`, а не на произвольное сообщение. |
| `setWebhook` возвращает ошибку | URL должен быть публичным HTTPS; секрет — 16–256 символов `[A-Za-z0-9_-]`. |
| Тикет не находится по ID | Истёк TTL или указан неверный префикс; проверьте `TICKET_TTL_SECONDS`. |

Информация о webhook:

```powershell
python scripts/set_webhook.py --info
```

Логи Vercel:

```powershell
vercel.cmd logs https://<project>.vercel.app
```

## Лицензия

MIT. См. [LICENSE](LICENSE).
