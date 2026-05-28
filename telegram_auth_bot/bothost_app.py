from aiohttp import ClientSession, web
from aiogram import Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from telegram_auth_bot.bot import dp
from telegram_auth_bot.config import (
    BOT_TOKEN,
    PORT,
    PUBLIC_BASE_URL,
    TELEGRAM_WEBHOOK_SECRET,
)
from telegram_auth_bot.database import (
    create_session,
    get_session,
    init_db,
    revoke_token,
    verify_token,
)


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


async def revoke(request):
    payload = await request.json()
    revoke_token(payload.get("access_token"), payload.get("device_id"))
    return web.json_response({"ok": True})


async def avatar(request):
    token = request.query.get("access_token")
    device_id = request.query.get("device_id")
    user = verify_token(token, device_id)
    if not user:
        return web.json_response({"ok": False, "error": "Access denied"}, status=403)

    photo = await load_telegram_avatar(user["telegram_id"])
    if not photo:
        return web.json_response({"ok": False, "error": "Avatar not found"}, status=404)

    return web.Response(body=photo, content_type="image/jpeg")


async def health(_request):
    return web.json_response(
        {
            "ok": True,
            "public_base_url_configured": bool(PUBLIC_BASE_URL),
            "webhook_url": f"{PUBLIC_BASE_URL}/telegram/webhook" if PUBLIC_BASE_URL else None,
            "port": PORT,
        }
    )


async def on_startup(bot: Bot):
    init_db()
    if not PUBLIC_BASE_URL:
        print("WARNING: PUBLIC_BASE_URL is empty. HTTP API is running, Telegram webhook was not set.")
        return

    webhook_url = f"{PUBLIC_BASE_URL}/telegram/webhook"
    await bot.set_webhook(
        webhook_url,
        secret_token=TELEGRAM_WEBHOOK_SECRET or None,
    )
    print(f"INFO: Telegram webhook set to {webhook_url}")


async def on_shutdown(bot: Bot):
    await bot.session.close()


async def load_telegram_avatar(telegram_id):
    async with ClientSession() as session:
        photos_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos"
        async with session.get(
            photos_url,
            params={"user_id": telegram_id, "limit": 1},
        ) as response:
            data = await response.json()

        if not data.get("ok") or data["result"].get("total_count", 0) < 1:
            return None

        file_id = data["result"]["photos"][0][-1]["file_id"]
        file_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile"
        async with session.get(file_url, params={"file_id": file_id}) as response:
            file_data = await response.json()

        if not file_data.get("ok"):
            return None

        path = file_data["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
        async with session.get(download_url) as response:
            if response.status != 200:
                return None
            return await response.read()


def create_app():
    if not BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN")

    bot = Bot(BOT_TOKEN)
    app = web.Application()

    app.router.add_get("/health", health)
    app.router.add_post("/api/auth/session", start_session)
    app.router.add_get("/api/auth/session/{session_id}", read_session)
    app.router.add_post("/api/auth/verify", verify)
    app.router.add_post("/api/auth/revoke", revoke)
    app.router.add_get("/api/auth/avatar", avatar)

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
