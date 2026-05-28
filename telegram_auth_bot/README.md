# Telegram authorization server

This package is the cloud side of the app authorization flow.

## Environment

Set these variables on the server:

```bash
TELEGRAM_BOT_TOKEN=123456:telegram-token
TELEGRAM_BOT_OWNER_ID=123456789
PUBLIC_BASE_URL=https://bot-123.bothost.ru
PORT=8000
AUTH_DATABASE_PATH=/app/shared/auth_bot.db
AUTH_SESSION_TTL_MINUTES=10
AUTH_TOKEN_TTL_DAYS=30
```

`TELEGRAM_BOT_OWNER_ID` is inserted as the first `Admin` on startup.

## Run

Install server dependencies:

```bash
pip install -r requirements_server.txt
```

Run the API for the desktop app:

```bash
python -m telegram_auth_bot.run_api
```

Run the Telegram bot:

```bash
python -m telegram_auth_bot.bot
```

In production, run both processes on the same persistent volume so they share
the SQLite database.

## Bothost single-process mode

If the hosting gives one public URL and one `PORT`, run the bot and API together:

```bash
python -m telegram_auth_bot.bothost_app
```

This starts:

```text
/telegram/webhook
/api/auth/session
/api/auth/session/{session_id}
/api/auth/verify
/health
```

Use the Bothost URL as the app auth server:

```json
{
  "auth_server_url": "https://bot-123.bothost.ru",
  "telegram_bot_username": "YourBotName"
}
```

## Bot commands

Only `Admin` users can manage access:

```text
/add_user <telegram_id|@username> [@username] [nickname]
/add_admin <telegram_id|@username> [@username] [nickname]
/remove_user <telegram_id|@username>
/users
/audit
/access_attempts
```

Admins also see a Telegram reply menu with buttons:

```text
Пользователи
Журнал аудита
Добавить Юзера
Добавить Админа
Убрать пользователя
```

The desktop app must have these values in `config/app_config.json`:

```json
{
  "auth_server_url": "https://your-auth-server.example.com",
  "telegram_bot_username": "YourBotName"
}
```
