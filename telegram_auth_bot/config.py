import os
from pathlib import Path


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_OWNER_ID = int(os.getenv("TELEGRAM_BOT_OWNER_ID", "0") or "0")
SHARED_DIR = Path(os.getenv("SHARED_DIR", "/app/shared"))
DATABASE_PATH = Path(
    os.getenv("AUTH_DATABASE_PATH", str(SHARED_DIR / "auth_bot.sqlite3"))
)
SESSION_TTL_MINUTES = int(os.getenv("AUTH_SESSION_TTL_MINUTES", "10"))
TOKEN_TTL_DAYS = int(os.getenv("AUTH_TOKEN_TTL_DAYS", "30"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8000") or "8000")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
