import asyncio
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
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
    find_user_by_target,
    init_db,
    is_admin,
    is_creator,
    list_attempts,
    list_users_by_role,
    upsert_user,
    username_placeholder_id,
)


dp = Dispatcher()
pending_actions = {}

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Пользователи"), KeyboardButton(text="Журнал аудита")]],
    resize_keyboard=True,
)

CREATOR_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Пользователи"), KeyboardButton(text="Админы")],
        [KeyboardButton(text="Журнал аудита")],
    ],
    resize_keyboard=True,
)

USERS_ACTIONS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Добавить", callback_data="add_users"),
            InlineKeyboardButton(text="Убрать", callback_data="remove_users"),
        ],
    ],
)

ADMINS_ACTIONS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Добавить", callback_data="add_admins"),
            InlineKeyboardButton(text="Убрать", callback_data="remove_admins"),
        ],
    ],
)


@dp.message(CommandStart())
async def start(message: Message):
    init_db()
    args = message.text.split(maxsplit=1)
    session_id = args[1].strip() if len(args) > 1 else ""

    if not session_id:
        if is_creator(message.from_user.id):
            await message.answer("Бот авторизации WOW Preview Engine. Вы вошли как Создатель.", reply_markup=CREATOR_MENU)
        elif is_admin(message.from_user.id):
            await message.answer("Бот авторизации WOW Preview Engine. Вы вошли как Админ.", reply_markup=ADMIN_MENU)
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


@dp.message(F.text == "Пользователи")
async def users_button(message: Message):
    await show_people(message, "User")


@dp.message(F.text == "Админы")
async def admins_button(message: Message):
    if not await require_creator(message):
        return
    await show_people(message, "Admin")


@dp.message(F.text == "Журнал аудита")
async def audit_button(message: Message):
    await show_audit(message)


@dp.callback_query(F.data.in_({"add_users", "remove_users", "add_admins", "remove_admins"}))
async def action_callback(callback: CallbackQuery):
    message = callback.message
    action = callback.data

    if action in ("add_admins", "remove_admins") and not is_creator(callback.from_user.id):
        await callback.answer("Только Создатель может управлять админами.", show_alert=True)
        return

    if action in ("add_users", "remove_users") and not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return

    pending_actions[callback.from_user.id] = action
    await callback.answer()
    await message.answer(instruction_for_action(action), reply_markup=menu_for(callback.from_user.id))


@dp.message(Command("add_user"))
async def add_user(message: Message):
    if await require_admin(message):
        await add_people_from_text(message, "User", command_payload(message.text))


@dp.message(Command("add_admin"))
async def add_admin(message: Message):
    if await require_creator(message):
        await add_people_from_text(message, "Admin", command_payload(message.text))


@dp.message(Command("remove_user"))
async def remove_user(message: Message):
    if await require_admin(message):
        await remove_people_from_text(message, command_payload(message.text), allow_admins=False)


@dp.message(Command("remove_admin"))
async def remove_admin(message: Message):
    if await require_creator(message):
        await remove_people_from_text(message, command_payload(message.text), allow_admins=True)


@dp.message(Command("users"))
async def users_command(message: Message):
    await show_people(message, "User")


@dp.message(Command("admins"))
async def admins_command(message: Message):
    if await require_creator(message):
        await show_people(message, "Admin")


@dp.message(Command("audit"))
async def audit_command(message: Message):
    await show_audit(message)


@dp.message(F.text)
async def text_router(message: Message):
    action = pending_actions.pop(message.from_user.id, None)
    if action == "add_users":
        await add_people_from_text(message, "User", message.text)
    elif action == "remove_users":
        await remove_people_from_text(message, message.text, allow_admins=False)
    elif action == "add_admins":
        if await require_creator(message):
            await add_people_from_text(message, "Admin", message.text)
    elif action == "remove_admins":
        if await require_creator(message):
            await remove_people_from_text(message, message.text, allow_admins=True)
    elif is_creator(message.from_user.id):
        await message.answer("Выберите действие в меню.", reply_markup=CREATOR_MENU)
    elif is_admin(message.from_user.id):
        await message.answer("Выберите действие в меню.", reply_markup=ADMIN_MENU)
    else:
        await message.answer("Откройте вход из приложения. Если вас нет в белом списке, у вас нет доступа.")


async def show_people(message: Message, role: str):
    if role == "Admin":
        if not await require_creator(message):
            return
        title = "Админы:"
        actions = ADMINS_ACTIONS
    else:
        if not await require_admin(message):
            return
        title = "Пользователи:"
        actions = USERS_ACTIONS

    rows = list_users_by_role(role)
    if not rows:
        await message.answer(f"{title}\nСписок пуст.", reply_markup=actions)
        return

    lines = [title]
    lines.extend(format_person(row) for row in rows[:60])
    await message.answer("\n".join(lines), reply_markup=actions)


async def show_audit(message: Message):
    if not await require_admin(message):
        return

    rows = list_attempts(40)
    if not rows:
        await message.answer("Журнал аудита пуст.", reply_markup=menu_for(message.from_user.id))
        return

    lines = ["Журнал аудита:"]
    lines.extend(format_attempt(row) for row in rows)
    await message.answer("\n".join(lines), reply_markup=menu_for(message.from_user.id))


async def add_people_from_text(message: Message, role: str, text: str):
    targets = parse_targets(text)
    if not targets:
        await message.answer("Не вижу тегов или ID. Пришлите один или несколько тегов/ID.", reply_markup=menu_for(message.from_user.id))
        return

    added = []
    for target in targets:
        telegram_id, username = target_to_identity(target)
        upsert_user(message.from_user.id, telegram_id, username, "", role)
        added.append(format_target(target))

    await message.answer(
        f"Добавлено в роль {role_label(role)}:\n" + "\n".join(added),
        reply_markup=menu_for(message.from_user.id),
    )


async def remove_people_from_text(message: Message, text: str, allow_admins: bool):
    targets = parse_targets(text)
    if not targets:
        await message.answer("Не вижу тегов или ID. Пришлите один или несколько тегов/ID.", reply_markup=menu_for(message.from_user.id))
        return

    removed = []
    not_found = []
    for target in targets:
        existing = find_user_by_target(target)
        if not existing:
            not_found.append(format_target(target))
            continue

        if existing["role"] == "Creator":
            not_found.append(f"{format_target(target)} (Создателя убрать нельзя)")
            continue

        if existing["role"] == "Admin" and not allow_admins:
            not_found.append(f"{format_target(target)} (нужны права Создателя)")
            continue

        result = deactivate_user(message.from_user.id, target)
        if not result:
            not_found.append(format_target(target))
            continue

        removed.append(format_target(target))

    parts = []
    if removed:
        parts.append("Убрано:\n" + "\n".join(removed))
    if not_found:
        parts.append("Не удалось убрать:\n" + "\n".join(not_found))

    await message.answer("\n\n".join(parts), reply_markup=menu_for(message.from_user.id))


async def require_admin(message: Message):
    if is_admin(message.from_user.id):
        return True

    await message.answer("У вас нет доступа")
    return False


async def require_creator(message: Message):
    if is_creator(message.from_user.id):
        return True

    await message.answer("Только Создатель может выполнять это действие.")
    return False


def instruction_for_action(action):
    if action == "add_users":
        return "Пришлите тег или список тегов/ID пользователей для добавления.\nНапример:\n@user1 @user2\n123456789"
    if action == "remove_users":
        return "Пришлите тег или список тегов/ID пользователей, которых нужно убрать."
    if action == "add_admins":
        return "Пришлите тег или список тегов/ID админов для добавления."
    return "Пришлите тег или список тегов/ID админов, которых нужно убрать."


def menu_for(telegram_id):
    return CREATOR_MENU if is_creator(telegram_id) else ADMIN_MENU


def parse_targets(text):
    return [
        item.strip().rstrip(",;")
        for item in re.split(r"[\s,;]+", text or "")
        if item.strip().rstrip(",;") and (item.startswith("@") or item.strip().rstrip(",;").lstrip("-").isdigit())
    ]


def target_to_identity(target):
    if target.startswith("@"):
        return username_placeholder_id(target), target
    return int(target), ""


def command_payload(text):
    return text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""


def format_person(row):
    tag = format_tag(row["username"])
    name = row["nickname"] or "Без имени"
    status = "Авторизован" if row["is_using"] else "Не авторизован"
    last_request = format_datetime(row.get("last_request_at")) or "запросов не было"
    return f"{tag} / {name} / {status} / последний запрос: {last_request}"


def format_attempt(row):
    status = "разрешено" if row["allowed"] else "отказано"
    tag = format_tag(row["username"])
    name = row["nickname"] or "Без имени"
    created_at = format_datetime(row["created_at"]) or row["created_at"]
    return f"{created_at} / {tag} / {name} / {status} / {row['reason']}"


def format_datetime(value):
    if not value:
        return ""
    try:
        date = datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=3)))
    except ValueError:
        return value
    return date.strftime("%d.%m.%Y %H:%M МСК")


def role_label(role):
    if role == "Creator":
        return "Создатель"
    return "Админ" if role == "Admin" else "Юзер"


def format_tag(username):
    clean = (username or "").strip().lstrip("@")
    return f"@{clean}" if clean else "@без_тега"


def format_target(target):
    return target if target.startswith("@") else f"ID {target}"


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN")

    init_db()
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
