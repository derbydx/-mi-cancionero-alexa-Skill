import sqlite3
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "playback_history.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playback_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            title TEXT,
            artist TEXT,
            played INTEGER DEFAULT 0,
            queued_at TEXT,
            played_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"Playback history DB initialized at {DB_PATH}")


def record_enqueued(video_id: str, title: str, artist: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO playback_history (video_id, title, artist, played, queued_at) VALUES (?, ?, ?, 0, ?)",
        (video_id, title, artist, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    logger.info(f"Recorded enqueued: {title} - {artist}")


def mark_as_played(video_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE playback_history SET played=1, played_at=? WHERE video_id=? AND played=0",
        (datetime.now(timezone.utc).isoformat(), video_id),
    )
    affected = conn.total_changes
    conn.commit()
    conn.close()
    if affected:
        logger.info(f"Marked as played: {video_id}")


def get_history(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT video_id, title, artist, played, queued_at, played_at FROM playback_history ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
