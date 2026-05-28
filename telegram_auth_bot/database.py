import secrets
import sqlite3
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from telegram_auth_bot.config import (
    BOT_OWNER_ID,
    DATABASE_PATH,
    SESSION_TTL_MINUTES,
    TOKEN_TTL_DAYS,
)


def utc_now():
    return datetime.now(timezone.utc)


def utc_iso():
    return utc_now().isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@contextmanager
def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db():
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                nickname TEXT,
                role TEXT NOT NULL CHECK (role IN ('User', 'Admin')),
                is_active INTEGER NOT NULL DEFAULT 1,
                last_authorized_at TEXT,
                is_using INTEGER NOT NULL DEFAULT 0,
                added_by INTEGER,
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                status TEXT NOT NULL,
                telegram_id INTEGER,
                access_token TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS access_tokens (
                token TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER,
                action TEXT NOT NULL,
                target_id INTEGER,
                target_username TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS access_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                username TEXT,
                nickname TEXT,
                session_id TEXT,
                allowed INTEGER NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        if BOT_OWNER_ID:
            owner = db.execute(
                "SELECT telegram_id FROM users WHERE telegram_id = ?",
                (BOT_OWNER_ID,),
            ).fetchone()
            if owner is None:
                db.execute(
                    """
                    INSERT INTO users (
                        telegram_id, username, nickname, role, is_active, added_by, added_at
                    ) VALUES (?, ?, ?, 'Admin', 1, ?, ?)
                    """,
                    (BOT_OWNER_ID, "", "Owner", BOT_OWNER_ID, utc_iso()),
                )
                add_audit(db, BOT_OWNER_ID, "bootstrap_admin", BOT_OWNER_ID, "")


def create_session(device_id):
    session_id = secrets.token_urlsafe(24)
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO auth_sessions (session_id, device_id, status, created_at, expires_at)
            VALUES (?, ?, 'pending', ?, ?)
            """,
            (
                session_id,
                device_id,
                now.isoformat(),
                (now + timedelta(minutes=SESSION_TTL_MINUTES)).isoformat(),
            ),
        )
    return session_id


def get_session(session_id):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM auth_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None

        if row["status"] == "pending" and is_expired(row["expires_at"]):
            db.execute(
                "UPDATE auth_sessions SET status = 'expired' WHERE session_id = ?",
                (session_id,),
            )
            row = dict(row)
            row["status"] = "expired"
            return row

        return dict(row)


def approve_session(session_id, telegram_user):
    session = get_session(session_id)
    if not session or session["status"] != "pending":
        return False, "session_not_found_or_expired"

    user = find_active_user(telegram_user.id, telegram_user.username)
    allowed = user is not None
    reason = "allowed" if allowed else "not_in_whitelist"

    with connect() as db:
        add_access_attempt(
            db,
            telegram_user.id,
            telegram_user.username,
            telegram_user.full_name,
            session_id,
            allowed,
            reason,
        )

        if not allowed:
            db.execute(
                "UPDATE auth_sessions SET status = 'denied', telegram_id = ? WHERE session_id = ?",
                (telegram_user.id, session_id),
            )
            return False, reason

        target_user_id = user["telegram_id"]
        if target_user_id != telegram_user.id:
            migrate_placeholder_user(db, target_user_id, telegram_user)
            target_user_id = telegram_user.id

        token = secrets.token_urlsafe(32)
        now = utc_now()
        expires_at = (now + timedelta(days=TOKEN_TTL_DAYS)).isoformat()
        db.execute(
            """
            INSERT INTO access_tokens (token, telegram_id, device_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token, target_user_id, session["device_id"], now.isoformat(), expires_at),
        )
        db.execute(
            """
            UPDATE auth_sessions
            SET status = 'approved', telegram_id = ?, access_token = ?
            WHERE session_id = ?
            """,
            (telegram_user.id, token, session_id),
        )
        db.execute(
            """
            UPDATE users
            SET username = COALESCE(NULLIF(?, ''), username),
                nickname = COALESCE(NULLIF(?, ''), nickname),
                last_authorized_at = ?,
                is_using = 1
            WHERE telegram_id = ?
            """,
            (telegram_user.username or "", telegram_user.full_name or "", now.isoformat(), target_user_id),
        )
        add_audit(db, telegram_user.id, "auth_approved", target_user_id, user["username"])

    return True, "approved"


def verify_token(token, device_id):
    with connect() as db:
        row = db.execute(
            """
            SELECT t.*, u.telegram_id, u.username, u.nickname, u.role, u.is_active
            FROM access_tokens t
            JOIN users u ON u.telegram_id = t.telegram_id
            WHERE t.token = ? AND t.device_id = ? AND t.revoked_at IS NULL
            """,
            (token, device_id),
        ).fetchone()

        if not row or row["is_active"] != 1 or is_expired(row["expires_at"]):
            return None

        now = utc_iso()
        db.execute(
            "UPDATE users SET last_authorized_at = ?, is_using = 1 WHERE telegram_id = ?",
            (now, row["telegram_id"]),
        )
        return user_payload(row)


def revoke_token(token, device_id):
    with connect() as db:
        row = db.execute(
            """
            SELECT telegram_id
            FROM access_tokens
            WHERE token = ? AND device_id = ? AND revoked_at IS NULL
            """,
            (token, device_id),
        ).fetchone()
        if not row:
            return False

        now = utc_iso()
        db.execute(
            "UPDATE access_tokens SET revoked_at = ? WHERE token = ? AND device_id = ?",
            (now, token, device_id),
        )
        db.execute(
            "UPDATE users SET is_using = 0 WHERE telegram_id = ?",
            (row["telegram_id"],),
        )
        add_audit(db, row["telegram_id"], "logout", row["telegram_id"], "")
        return True


def find_active_user(telegram_id, username=None):
    with connect() as db:
        if telegram_id:
            row = db.execute(
                "SELECT * FROM users WHERE telegram_id = ? AND is_active = 1",
                (telegram_id,),
            ).fetchone()
            if row:
                return dict(row)

        normalized = normalize_username(username)
        if normalized:
            row = db.execute(
                """
                SELECT * FROM users
                WHERE lower(replace(username, '@', '')) = ? AND is_active = 1
                """,
                (normalized,),
            ).fetchone()
            if row:
                return dict(row)

    return None


def is_admin(telegram_id):
    user = find_active_user(telegram_id)
    return bool(user and user["role"] == "Admin")


def upsert_user(actor_id, telegram_id, username, nickname, role):
    with connect() as db:
        existing = db.execute(
            "SELECT telegram_id FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if existing:
            db.execute(
                """
                UPDATE users
                SET username = ?, nickname = ?, role = ?, is_active = 1, added_by = ?, added_at = ?
                WHERE telegram_id = ?
                """,
                (clean_username(username), nickname, role, actor_id, utc_iso(), telegram_id),
            )
            action = f"reactivate_{role.lower()}"
        else:
            db.execute(
                """
                INSERT INTO users (
                    telegram_id, username, nickname, role, is_active, added_by, added_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (telegram_id, clean_username(username), nickname, role, actor_id, utc_iso()),
            )
            action = f"add_{role.lower()}"

        add_audit(db, actor_id, action, telegram_id, clean_username(username))


def deactivate_user(actor_id, target):
    with connect() as db:
        if str(target).startswith("@"):
            row = db.execute(
                "SELECT * FROM users WHERE lower(replace(username, '@', '')) = ?",
                (normalize_username(target),),
            ).fetchone()
        else:
            try:
                target_id = int(target)
            except ValueError:
                return None

            row = db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (target_id,),
            ).fetchone()

        if not row:
            return None

        db.execute(
            "UPDATE users SET is_active = 0, is_using = 0 WHERE telegram_id = ?",
            (row["telegram_id"],),
        )
        db.execute(
            "UPDATE access_tokens SET revoked_at = ? WHERE telegram_id = ? AND revoked_at IS NULL",
            (utc_iso(), row["telegram_id"]),
        )
        add_audit(db, actor_id, "remove_user", row["telegram_id"], row["username"])
        return dict(row)


def list_users():
    with connect() as db:
        rows = db.execute(
            """
            SELECT telegram_id, username, nickname, role, is_active, last_authorized_at, is_using
            FROM users
            ORDER BY role DESC, is_active DESC, username COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]


def list_audit(limit=20):
    with connect() as db:
        rows = db.execute(
            """
            SELECT actor_id, action, target_id, target_username, created_at
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_attempts(limit=20):
    with connect() as db:
        rows = db.execute(
            """
            SELECT telegram_id, username, nickname, session_id, allowed, reason, created_at
            FROM access_attempts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def add_audit(db, actor_id, action, target_id, target_username):
    db.execute(
        """
        INSERT INTO audit_log (actor_id, action, target_id, target_username, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (actor_id, action, target_id, clean_username(target_username), utc_iso()),
    )


def migrate_placeholder_user(db, old_telegram_id, telegram_user):
    existing = db.execute(
        "SELECT telegram_id FROM users WHERE telegram_id = ?",
        (telegram_user.id,),
    ).fetchone()
    if existing:
        db.execute(
            """
            UPDATE users
            SET is_active = 0, is_using = 0
            WHERE telegram_id = ?
            """,
            (old_telegram_id,),
        )
        return

    db.execute(
        """
        UPDATE users
        SET telegram_id = ?,
            username = COALESCE(NULLIF(?, ''), username),
            nickname = COALESCE(NULLIF(?, ''), nickname)
        WHERE telegram_id = ?
        """,
        (
            telegram_user.id,
            telegram_user.username or "",
            telegram_user.full_name or "",
            old_telegram_id,
        ),
    )


def add_access_attempt(db, telegram_id, username, nickname, session_id, allowed, reason):
    db.execute(
        """
        INSERT INTO access_attempts (
            telegram_id, username, nickname, session_id, allowed, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            telegram_id,
            clean_username(username),
            nickname,
            session_id,
            int(allowed),
            reason,
            utc_iso(),
        ),
    )


def user_payload(row):
    return {
        "telegram_id": row["telegram_id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "role": row["role"],
    }


def is_expired(value):
    expires_at = parse_iso(value)
    return not expires_at or utc_now() > expires_at


def normalize_username(username):
    return clean_username(username).lower()


def clean_username(username):
    return (username or "").strip().lstrip("@")


def username_placeholder_id(username):
    normalized = normalize_username(username)
    return -int(zlib.crc32(normalized.encode("utf-8")))
