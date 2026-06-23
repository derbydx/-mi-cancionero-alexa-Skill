import sqlite3
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "playback_history.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_favorites_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            thumbnail TEXT,
            added_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Favorites DB initialized")


def get_favorites() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT video_id, title, artist, thumbnail, added_at "
        "FROM favorites ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_favorite(video_id: str, title: str = "", artist: str = "", thumbnail: str = "") -> bool:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO favorites (video_id, title, artist, thumbnail, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (video_id, title, artist, thumbnail, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        logger.info("Added favorite: %s - %s", title, artist)
        return True
    except Exception as e:
        logger.error("Error adding favorite %s: %s", video_id, e)
        return False
    finally:
        conn.close()


def remove_favorite(video_id: str) -> bool:
    conn = _connect()
    try:
        conn.execute("DELETE FROM favorites WHERE video_id=?", (video_id,))
        conn.commit()
        logger.info("Removed favorite: %s", video_id)
        return True
    except Exception as e:
        logger.error("Error removing favorite %s: %s", video_id, e)
        return False
    finally:
        conn.close()


def is_favorite(video_id: str) -> bool:
    conn = _connect()
    row = conn.execute("SELECT 1 FROM favorites WHERE video_id=?", (video_id,)).fetchone()
    conn.close()
    return row is not None
