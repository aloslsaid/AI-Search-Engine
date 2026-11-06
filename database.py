"""SQLite persistence: per-user memory, settings (system prompt), usage, prefs.

Uses the standard-library sqlite3 module and runs every query in a worker
thread (asyncio.to_thread), so the bot's event loop is never blocked.
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import Any

from utils import now_iso, today_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    full_name  TEXT,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages (user_id, id);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER NOT NULL,
    day     TEXT NOT NULL,
    kind    TEXT NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, kind)
);

CREATE TABLE IF NOT EXISTS prefs (
    user_id INTEGER NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ setup
    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        conn.commit()
        self._conn = conn

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        with self._lock:
            if self._conn is None:
                self._open()
            # Drop usage counters older than ~60 days.
            self._conn.execute(  # type: ignore[union-attr]
                "DELETE FROM usage WHERE day < date('now', '-60 day')"
            )
            self._conn.commit()  # type: ignore[union-attr]

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _run(self, fn):
        """Run fn(conn) under the lock and commit; roll back on error."""
        with self._lock:
            if self._conn is None:
                self._open()
            conn = self._conn
            assert conn is not None
            try:
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    async def _arun(self, fn):
        return await asyncio.to_thread(self._run, fn)

    # ------------------------------------------------------------------ users
    async def touch_user(self, user_id: int, username: str | None, full_name: str | None) -> None:
        now = now_iso()

        def fn(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO users (user_id, username, full_name, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    last_seen = excluded.last_seen
                """,
                (user_id, username, full_name, now, now),
            )

        await self._arun(fn)

    # --------------------------------------------------------------- messages
    async def get_history(self, user_id: int, max_messages: int, max_chars: int) -> list[dict[str, str]]:
        def fn(conn: sqlite3.Connection) -> list[dict[str, str]]:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, max_messages),
            ).fetchall()
            selected: list[dict[str, str]] = []
            total = 0
            for row in rows:  # newest first
                size = len(row["content"])
                if selected and total + size > max_chars:
                    break
                selected.append({"role": row["role"], "content": row["content"]})
                total += size
            selected.reverse()
            while selected and selected[0]["role"] != "user":
                selected.pop(0)
            return selected

        return await self._arun(fn)

    async def add_exchange(self, user_id: int, user_text: str, assistant_text: str, keep: int) -> None:
        """Store one user/assistant pair and prune the user's oldest messages."""
        now = now_iso()
        keep = max(keep, 2)

        def fn(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (user_id, user_text, now),
            )
            conn.execute(
                "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
                (user_id, assistant_text, now),
            )
            conn.execute(
                """
                DELETE FROM messages
                WHERE user_id = ?
                  AND id NOT IN (
                      SELECT id FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
                  )
                """,
                (user_id, user_id, keep),
            )

        await self._arun(fn)

    async def clear_history(self, user_id: int) -> int:
        def fn(conn: sqlite3.Connection) -> int:
            cur = conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            return cur.rowcount

        return await self._arun(fn)

    async def count_messages(self, user_id: int) -> int:
        def fn(conn: sqlite3.Connection) -> int:
            return conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)
            ).fetchone()[0]

        return await self._arun(fn)

    # --------------------------------------------------------------- settings
    async def get_setting(self, key: str) -> str | None:
        def fn(conn: sqlite3.Connection) -> str | None:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

        return await self._arun(fn)

    async def set_setting(self, key: str, value: str) -> None:
        now = now_iso()

        def fn(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

        await self._arun(fn)

    async def delete_setting(self, key: str) -> bool:
        def fn(conn: sqlite3.Connection) -> bool:
            cur = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            return cur.rowcount > 0

        return await self._arun(fn)

    # ------------------------------------------------------------------ usage
    async def try_consume(self, user_id: int, day: str, kind: str, limit: int) -> tuple[bool, int]:
        """Atomically add 1 to today's counter unless the limit is reached.

        limit <= 0 means unlimited (the counter is still incremented for stats).
        Returns (allowed, used_after).
        """

        def fn(conn: sqlite3.Connection) -> tuple[bool, int]:
            row = conn.execute(
                "SELECT count FROM usage WHERE user_id = ? AND day = ? AND kind = ?",
                (user_id, day, kind),
            ).fetchone()
            used = row["count"] if row else 0
            if limit > 0 and used >= limit:
                return False, used
            conn.execute(
                """
                INSERT INTO usage (user_id, day, kind, count) VALUES (?, ?, ?, 1)
                ON CONFLICT(user_id, day, kind) DO UPDATE SET count = count + 1
                """,
                (user_id, day, kind),
            )
            return True, used + 1

        return await self._arun(fn)

    async def refund(self, user_id: int, day: str, kind: str) -> None:
        def fn(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE usage SET count = count - 1 WHERE user_id = ? AND day = ? AND kind = ? AND count > 0",
                (user_id, day, kind),
            )

        await self._arun(fn)

    async def get_usage(self, user_id: int, day: str, kind: str) -> int:
        def fn(conn: sqlite3.Connection) -> int:
            row = conn.execute(
                "SELECT count FROM usage WHERE user_id = ? AND day = ? AND kind = ?",
                (user_id, day, kind),
            ).fetchone()
            return row["count"] if row else 0

        return await self._arun(fn)

    # ------------------------------------------------------------------ prefs
    async def get_pref(self, user_id: int, key: str, default: str = "") -> str:
        def fn(conn: sqlite3.Connection) -> str:
            row = conn.execute(
                "SELECT value FROM prefs WHERE user_id = ? AND key = ?", (user_id, key)
            ).fetchone()
            return row["value"] if row else default

        return await self._arun(fn)

    async def set_pref(self, user_id: int, key: str, value: str) -> None:
        def fn(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO prefs (user_id, key, value) VALUES (?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
                """,
                (user_id, key, value),
            )

        await self._arun(fn)

    # ------------------------------------------------------------------ stats
    async def stats(self, utc_offset_hours: int = 0) -> dict[str, Any]:
        day = today_key(utc_offset_hours)

        def fn(conn: sqlite3.Connection) -> dict[str, Any]:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            ai_today = conn.execute(
                "SELECT COALESCE(SUM(count), 0) FROM usage WHERE day = ? AND kind = 'ai'", (day,)
            ).fetchone()[0]
            search_today = conn.execute(
                "SELECT COALESCE(SUM(count), 0) FROM usage WHERE day = ? AND kind = 'search'", (day,)
            ).fetchone()[0]
            return {
                "users": users,
                "messages": messages,
                "ai_today": ai_today,
                "search_today": search_today,
            }

        return await self._arun(fn)
