import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from telegram_auth_bot.config import BOT_TOKEN
from telegram_auth_bot.database import (
    approve_session,
    deactivate_user,
    init_db,
    is_admin,
    list_attempts,
    list_audit,
    list_users,
    upsert_user,
    username_placeholder_id,
)


dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    init_db()
    args = message.text.split(maxsplit=1)
    session_id = args[1].strip() if len(args) > 1 else ""

    if not session_id:
        await message.answer("Бот авторизации WOW Preview Engine. Откройте вход из приложения.")
        return

    allowed, reason = approve_session(session_id, message.from_user)
    if allowed:
        await message.answer("Готово. Авторизация подтверждена, можно вернуться в приложение.")
    elif reason == "not_in_whitelist":
        await message.answer("Доступ запрещен: вас нет в белом списке.")
    else:
        await message.answer("Сессия авторизации не найдена или истекла. Запустите вход из приложения заново.")


@dp.message(Command("add_user"))
async def add_user(message: Message):
    await add_person(message, "User")


@dp.message(Command("add_admin"))
async def add_admin(message: Message):
    await add_person(message, "Admin")


async def add_person(message: Message, role: str):
    if not await require_admin(message):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        await message.answer(f"Формат: /add_{role.lower()} <telegram_id|@username> [@username] [никнейм]")
        return

    if parts[1].startswith("@"):
        telegram_id = username_placeholder_id(parts[1])
        username = parts[1]
        nickname = " ".join(parts[2:]) if len(parts) >= 3 else ""
    else:
        try:
            telegram_id = int(parts[1])
        except ValueError:
            await message.answer("telegram_id должен быть числом, либо укажите @username.")
            return

        username = parts[2] if len(parts) >= 3 and parts[2].startswith("@") else ""
        nickname = parts[3] if len(parts) >= 4 else ""
        if not nickname and username == "":
            nickname = " ".join(parts[2:]) if len(parts) >= 3 else ""

    upsert_user(message.from_user.id, telegram_id, username, nickname, role)
    await message.answer(f"{role} добавлен/обновлен: {telegram_id} {username}".strip())


@dp.message(Command("remove_user"))
async def remove_user(message: Message):
    if not await require_admin(message):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /remove_user <telegram_id|@username>")
        return

    removed = deactivate_user(message.from_user.id, parts[1].strip())
    if not removed:
        await message.answer("Пользователь не найден.")
        return

    await message.answer(f"Пользователь исключен: {removed['telegram_id']} @{removed['username']}")


@dp.message(Command("users"))
async def users(message: Message):
    if not await require_admin(message):
        return

    rows = list_users()
    if not rows:
        await message.answer("Белый список пуст.")
        return

    await message.answer("\n".join(format_user(row) for row in rows[:40]))


@dp.message(Command("audit"))
async def audit(message: Message):
    if not await require_admin(message):
        return

    rows = list_audit()
    if not rows:
        await message.answer("Журнал аудита пуст.")
        return

    await message.answer("\n".join(format_audit(row) for row in rows))


@dp.message(Command("access_attempts"))
async def access_attempts(message: Message):
    if not await require_admin(message):
        return

    rows = list_attempts()
    if not rows:
        await message.answer("Попыток входа пока нет.")
        return

    await message.answer("\n".join(format_attempt(row) for row in rows))


@dp.message(F.text)
async def fallback(message: Message):
    await message.answer(
        "Команды: /add_user, /add_admin, /remove_user, /users, /audit, /access_attempts"
    )


async def require_admin(message: Message):
    if is_admin(message.from_user.id):
        return True

    await message.answer("Недостаточно прав. Нужна роль Admin.")
    return False


def format_user(row):
    active = "active" if row["is_active"] else "blocked"
    using = "using" if row["is_using"] else "idle"
    return (
        f"{row['role']} {active} {using}: "
        f"{row['telegram_id']} @{row['username']} {row['nickname'] or ''}"
    ).strip()


def format_audit(row):
    username = f"@{row['target_username']}" if row["target_username"] else ""
    return (
        f"{row['created_at']} | actor {row['actor_id']} | "
        f"{row['action']} | target {row['target_id']} {username}"
    ).strip()


def format_attempt(row):
    status = "allowed" if row["allowed"] else "denied"
    username = f"@{row['username']}" if row["username"] else ""
    return (
        f"{row['created_at']} | {status} | {row['telegram_id']} "
        f"{username} {row['nickname'] or ''} | {row['reason']}"
    ).strip()


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN")

    init_db()
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
