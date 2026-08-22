"""
SQLite persistence layer for the event bot.
Uses aiosqlite so all DB calls are non-blocking inside the discord.py event loop.
"""

import aiosqlite
import os
import time
from typing import Optional

# Locally this defaults to events.db in the project folder. On Railway, set the
# DB_PATH env var to a path inside your mounted volume (e.g. /app/data/events.db)
# so the database survives redeploys instead of resetting each time.
DB_PATH = os.environ.get("DB_PATH", "events.db")

_conn: Optional[aiosqlite.Connection] = None

ACCEPTED = "accepted"
PRIORITY = "priority"


async def init_db():
    """Create tables if they don't exist, migrate older DBs, and open the shared connection."""
    global _conn
    _conn = await aiosqlite.connect(DB_PATH)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            start_ts INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            closed INTEGER NOT NULL DEFAULT 0,
            world TEXT
        )
        """
    )
    await _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signups (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            list_type TEXT NOT NULL DEFAULT 'accepted',
            signed_at INTEGER NOT NULL,
            PRIMARY KEY (event_id, user_id, list_type),
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        """
    )
    await _migrate_add_list_type()
    await _migrate_add_world()
    await _conn.commit()


async def _migrate_add_world():
    """Older DBs (before /event set_world existed) don't have the world column."""
    cur = await _conn.execute("PRAGMA table_info(events)")
    columns = [row[1] for row in await cur.fetchall()]
    if "world" not in columns:
        await _conn.execute("ALTER TABLE events ADD COLUMN world TEXT")


async def _migrate_add_list_type():
    """
    Older DBs (before Priority existed) have a signups table with PRIMARY KEY
    (event_id, user_id) and no list_type column. SQLite can't ALTER a primary
    key in place, so if we detect the old shape, rebuild the table and copy
    every existing row over as 'accepted'.
    """
    cur = await _conn.execute("PRAGMA table_info(signups)")
    columns = [row[1] for row in await cur.fetchall()]
    if "list_type" in columns:
        return  # already on the new schema

    await _conn.execute("ALTER TABLE signups RENAME TO signups_old")
    await _conn.execute(
        """
        CREATE TABLE signups (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            list_type TEXT NOT NULL DEFAULT 'accepted',
            signed_at INTEGER NOT NULL,
            PRIMARY KEY (event_id, user_id, list_type),
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        """
    )
    await _conn.execute(
        """
        INSERT INTO signups (event_id, user_id, username, list_type, signed_at)
        SELECT event_id, user_id, username, 'accepted', signed_at FROM signups_old
        """
    )
    await _conn.execute("DROP TABLE signups_old")


async def create_event(guild_id: int, channel_id: int, title: str, description: str,
                        start_ts: int, creator_id: int) -> int:
    cur = await _conn.execute(
        "INSERT INTO events (guild_id, channel_id, title, description, start_ts, creator_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (guild_id, channel_id, title, description, start_ts, creator_id, int(time.time())),
    )
    await _conn.commit()
    return cur.lastrowid


async def set_message_id(event_id: int, message_id: int):
    await _conn.execute("UPDATE events SET message_id = ? WHERE id = ?", (message_id, event_id))
    await _conn.commit()


async def get_event(event_id: int) -> Optional[aiosqlite.Row]:
    cur = await _conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    return await cur.fetchone()


async def get_event_by_message(message_id: int) -> Optional[aiosqlite.Row]:
    cur = await _conn.execute("SELECT * FROM events WHERE message_id = ?", (message_id,))
    return await cur.fetchone()


async def get_active_events():
    """All events that aren't closed (used by the countdown refresh loop)."""
    cur = await _conn.execute("SELECT * FROM events WHERE closed = 0")
    return await cur.fetchall()


async def get_events_by_guild(guild_id: int):
    cur = await _conn.execute(
        "SELECT * FROM events WHERE guild_id = ? AND closed = 0 ORDER BY start_ts ASC", (guild_id,)
    )
    return await cur.fetchall()


async def close_event(event_id: int):
    await _conn.execute("UPDATE events SET closed = 1 WHERE id = ?", (event_id,))
    await _conn.commit()


async def set_world(event_id: int, world: str):
    await _conn.execute("UPDATE events SET world = ? WHERE id = ?", (world, event_id))
    await _conn.commit()


async def delete_event(event_id: int):
    await _conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    await _conn.execute("DELETE FROM signups WHERE event_id = ?", (event_id,))
    await _conn.commit()


async def add_signup(event_id: int, user_id: int, username: str, list_type: str = ACCEPTED):
    await _conn.execute(
        "INSERT OR REPLACE INTO signups (event_id, user_id, username, list_type, signed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, user_id, username, list_type, int(time.time())),
    )
    await _conn.commit()


async def remove_signup(event_id: int, user_id: int, list_type: str = ACCEPTED):
    await _conn.execute(
        "DELETE FROM signups WHERE event_id = ? AND user_id = ? AND list_type = ?",
        (event_id, user_id, list_type),
    )
    await _conn.commit()


async def get_signups(event_id: int, list_type: str = ACCEPTED):
    cur = await _conn.execute(
        "SELECT * FROM signups WHERE event_id = ? AND list_type = ? ORDER BY signed_at ASC",
        (event_id, list_type),
    )
    return await cur.fetchall()


async def is_signed_up(event_id: int, user_id: int, list_type: str = ACCEPTED) -> bool:
    cur = await _conn.execute(
        "SELECT 1 FROM signups WHERE event_id = ? AND user_id = ? AND list_type = ?",
        (event_id, user_id, list_type),
    )
    return await cur.fetchone() is not None
