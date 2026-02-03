"""SQLite-backed user store with bcrypt password hashing and Telegram linking."""

from __future__ import annotations

import re
import sqlite3
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bcrypt

from . import tokens

_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode("utf-8")

DEFAULT_DB_PATH = ".galaxy/users.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    telegram_id INTEGER UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
"""


@dataclass
class User:
    """Authenticated user record."""

    id: str
    username: str
    password_hash: str
    telegram_id: Optional[int]
    created_at: datetime
    last_seen_at: datetime


class UserStore:
    """SQLite user store with bcrypt passwords and Telegram account linking.

    Args:
        db_path: Path to SQLite database file. Parent directories are created
                 automatically. Defaults to ".galaxy/users.db".
        jwt_secret: Secret key for JWT token signing. Required for create_token/verify_token.
        token_expiry_hours: JWT token validity duration in hours (default 24).
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        jwt_secret: str = "",
        token_expiry_hours: int = 24,
    ) -> None:
        if jwt_secret and "CHANGE-ME" in jwt_secret:
            warnings.warn("jwt_secret contains placeholder value — tokens will be insecure")

        self._db_path = db_path
        self._jwt_secret = jwt_secret
        self._token_expiry_hours = token_expiry_hours
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def _next_id(self) -> str:
        return f"user-{uuid.uuid4().hex[:8]}"

    def _row_to_user(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            telegram_id=row["telegram_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_user(self, username: str, password: str) -> Optional[User]:
        """Create a new user with a bcrypt-hashed password.

        Returns the created User, or None if the username already exists
        or validation fails (username 3-32 chars alphanumeric, password 6+ chars).
        """
        if not username or len(username) < 3 or len(username) > 32:
            return None
        if not re.match(r"^[a-zA-Z0-9_-]+$", username):
            return None
        if not password or len(password) < 6:
            return None

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        now = self._now()
        user_id = self._next_id()

        try:
            self._conn.execute(
                "INSERT INTO users (id, username, password_hash, telegram_id, created_at, last_seen_at) "
                "VALUES (?, ?, ?, NULL, ?, ?)",
                (user_id, username, password_hash, now, now),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            return None

        return self.get_by_username(username)

    def verify_password(self, username: str, password: str) -> bool:
        """Check a plaintext password against the stored bcrypt hash.

        Performs constant-time comparison even for non-existent users
        to prevent timing-based username enumeration.
        """
        user = self.get_by_username(username)
        if user is None:
            bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH.encode("utf-8"))
            return False

        return bcrypt.checkpw(
            password.encode("utf-8"), user.password_hash.encode("utf-8")
        )

    def get_by_username(self, username: str) -> Optional[User]:
        """Look up a user by username."""
        row = self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return self._row_to_user(row) if row else None

    def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Look up a user by linked Telegram ID."""
        row = self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return self._row_to_user(row) if row else None

    def link_telegram(self, user_id: str, telegram_id: int) -> bool:
        """Associate a Telegram account with an existing user.

        Returns True on success, False if user_id not found or telegram_id
        is already linked to another account.
        """
        try:
            cur = self._conn.execute(
                "UPDATE users SET telegram_id = ? WHERE id = ?",
                (telegram_id, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0
        except sqlite3.IntegrityError:
            return False

    def list_users(self) -> list[User]:
        """Return all users ordered by creation time."""
        rows = self._conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
        return [self._row_to_user(r) for r in rows]

    def delete_user(self, user_id: str) -> bool:
        """Remove a user by ID. Returns True if a row was deleted."""
        cur = self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def create_token(self, user_id: str, username: str) -> str:
        """Create a signed JWT token for the given user."""
        return tokens.create_token(
            user_id, username, self._jwt_secret, self._token_expiry_hours
        )

    def verify_token(self, token: str) -> Optional[dict]:
        """Verify a JWT token. Returns {user_id, username} or None."""
        return tokens.verify_token(token, self._jwt_secret)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
