import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from telegram_auth_bot.config import BOT_TOKEN
from telegram_auth_bot.database import (
    approve_session,
    deactivate_user,
    init_db,
    is_admin,
    list_attempts,
    list_users,
    upsert_user,
    username_placeholder_id,
)


dp = Dispatcher()

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Пользователи"), KeyboardButton(text="Журнал аудита")],
    ],
    resize_keyboard=True,
)

USERS_ACTIONS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Добавить юзера",
                switch_inline_query_current_chat="/add_user ",
            ),
            InlineKeyboardButton(
                text="Убрать юзера",
                switch_inline_query_current_chat="/remove_user ",
            ),
        ],
    ],
)


@dp.message(CommandStart())
async def start(message: Message):
    init_db()
    args = message.text.split(maxsplit=1)
    session_id = args[1].strip() if len(args) > 1 else ""

    if not session_id:
        if is_admin(message.from_user.id):
            await message.answer(
                "Бот авторизации WOW Preview Engine. Вы вошли как Админ.",
                reply_markup=ADMIN_MENU,
            )
        else:
            await message.answer("Бот авторизации WOW Preview Engine. Откройте вход из приложения.")
        return

    allowed, reason = approve_session(session_id, message.from_user)
    if allowed:
        await message.answer("Готово. Авторизация подтверждена, можно вернуться в приложение.")
    elif reason == "not_in_whitelist":
        await message.answer("У вас нет доступа")
    else:
        await message.answer("Сессия авторизации не найдена или истекла. Запустите вход из приложения заново.")


@dp.message(Command("add_user"))
async def add_user(message: Message):
    await add_person(message, "User")


@dp.message(Command("add_admin"))
async def add_admin(message: Message):
    await add_person(message, "Admin")


@dp.message(Command("remove_user"))
async def remove_user(message: Message):
    await remove_person(message)


@dp.message(Command("users"))
async def users(message: Message):
    await show_users(message)


@dp.message(Command("audit"))
async def audit(message: Message):
    await show_audit(message)


@dp.message(Command("access_attempts"))
async def access_attempts(message: Message):
    await show_audit(message)


@dp.message(F.text == "Пользователи")
async def users_button(message: Message):
    await show_users(message)


@dp.message(F.text == "Журнал аудита")
async def audit_button(message: Message):
    await show_audit(message)


async def add_person(message: Message, role: str):
    if not await require_admin(message):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        await message.answer(
            f"Формат: /add_{role.lower()} <telegram_id|@username> [@username] [имя]",
            reply_markup=ADMIN_MENU,
        )
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
    await message.answer(
        f"{role_label(role)} добавлен/обновлен: {format_tag(username)}",
        reply_markup=ADMIN_MENU,
    )


async def remove_person(message: Message):
    if not await require_admin(message):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Формат: /remove_user <telegram_id|@username>",
            reply_markup=ADMIN_MENU,
        )
        return

    removed = deactivate_user(message.from_user.id, parts[1].strip())
    if not removed:
        await message.answer("Пользователь не найден.", reply_markup=ADMIN_MENU)
        return

    await message.answer(
        f"Пользователь исключен: {format_tag(removed['username'])}",
        reply_markup=ADMIN_MENU,
    )


async def show_users(message: Message):
    if not await require_admin(message):
        return

    rows = list_users()
    if not rows:
        await message.answer("Белый список пуст.", reply_markup=ADMIN_MENU)
        return

    lines = ["Пользователи:"]
    lines.extend(format_user(row) for row in rows[:60])
    await message.answer(
        "\n".join(lines),
        reply_markup=USERS_ACTIONS,
    )


async def show_audit(message: Message):
    if not await require_admin(message):
        return

    rows = list_attempts(40)
    if not rows:
        await message.answer("Журнал аудита пуст.", reply_markup=ADMIN_MENU)
        return

    lines = ["Журнал аудита:"]
    lines.extend(format_attempt(row) for row in rows)
    await message.answer("\n".join(lines), reply_markup=ADMIN_MENU)


@dp.message(F.text)
async def fallback(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "Выберите действие в меню или используйте команды:\n"
            "/add_user, /remove_user, /users, /audit",
            reply_markup=ADMIN_MENU,
        )
    else:
        await message.answer("Откройте вход из приложения. Если вас нет в белом списке, у вас нет доступа.")


async def require_admin(message: Message):
    if is_admin(message.from_user.id):
        return True

    await message.answer("У вас нет доступа")
    return False


def format_user(row):
    tag = format_tag(row["username"])
    name = row["nickname"] or "Без имени"
    status = "Авторизован" if row["is_using"] else "Не авторизован"
    last_request = row.get("last_request_at") or "Запросов не было"
    role = role_label(row["role"])
    return f"{tag} / {name} / {role} / {status} / {last_request}"


def format_attempt(row):
    status = "разрешено" if row["allowed"] else "отказано"
    tag = format_tag(row["username"])
    name = row["nickname"] or "Без имени"
    return f"{row['created_at']} / {tag} / {name} / {status} / {row['reason']}"


def role_label(role):
    return "Админ" if role == "Admin" else "Юзер"


def format_tag(username):
    clean = (username or "").strip().lstrip("@")
    return f"@{clean}" if clean else "@без_тега"


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN")

    init_db()
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
