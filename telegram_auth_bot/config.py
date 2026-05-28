import os
from pathlib import Path


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BOT_OWNER_ID = int(os.getenv("TELEGRAM_BOT_OWNER_ID", "0").strip() or "0")
SHARED_DIR = Path(os.getenv("SHARED_DIR", "/app/shared").strip())
DATABASE_PATH = Path(
    os.getenv("AUTH_DATABASE_PATH", str(SHARED_DIR / "auth_bot.sqlite3")).strip()
)
SESSION_TTL_MINUTES = int(os.getenv("AUTH_SESSION_TTL_MINUTES", "10").strip() or "10")
TOKEN_TTL_DAYS = int(os.getenv("AUTH_TOKEN_TTL_DAYS", "30").strip() or "30")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
PORT = int(os.getenv("PORT", "3000").strip() or "3000")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
