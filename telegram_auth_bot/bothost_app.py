from aiohttp import web
from aiogram import Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from telegram_auth_bot.bot import dp
from telegram_auth_bot.config import (
    BOT_TOKEN,
    PORT,
    PUBLIC_BASE_URL,
    TELEGRAM_WEBHOOK_SECRET,
)
from telegram_auth_bot.database import create_session, get_session, init_db, verify_token


async def start_session(request):
    payload = await request.json()
    device_id = payload.get("device_id")
    if not device_id:
        return web.json_response({"ok": False, "error": "device_id is required"}, status=400)

    return web.json_response({"ok": True, "session_id": create_session(device_id)})


async def read_session(request):
    session = get_session(request.match_info["session_id"])
    if not session:
        return web.json_response({"ok": False, "error": "Session not found"}, status=404)

    payload = {"ok": True, "status": session["status"]}
    if session["status"] == "approved":
        payload["access_token"] = session["access_token"]
        payload["user"] = verify_token(session["access_token"], session["device_id"])

    return web.json_response(payload)


async def verify(request):
    payload = await request.json()
    user = verify_token(payload.get("access_token"), payload.get("device_id"))
    if not user:
        return web.json_response({"ok": False, "error": "Access denied"}, status=403)

    return web.json_response({"ok": True, "user": user})


async def health(_request):
    return web.json_response({"ok": True})


async def on_startup(bot: Bot):
    init_db()
    if not PUBLIC_BASE_URL:
        raise RuntimeError("Set PUBLIC_BASE_URL to the HTTPS URL issued by Bothost")

    await bot.set_webhook(
        f"{PUBLIC_BASE_URL}/telegram/webhook",
        secret_token=TELEGRAM_WEBHOOK_SECRET or None,
    )


async def on_shutdown(bot: Bot):
    await bot.session.close()


def create_app():
    if not BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN")

    bot = Bot(BOT_TOKEN)
    app = web.Application()

    app.router.add_get("/health", health)
    app.router.add_post("/api/auth/session", start_session)
    app.router.add_get("/api/auth/session/{session_id}", read_session)
    app.router.add_post("/api/auth/verify", verify)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=TELEGRAM_WEBHOOK_SECRET or None,
    ).register(app, path="/telegram/webhook")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    setup_application(app, dp, bot=bot)
    return app


def main():
    web.run_app(create_app(), host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
