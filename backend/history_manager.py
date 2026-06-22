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


def init_db():
    conn = _connect()
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
    conn = _connect()
    conn.execute(
        "INSERT INTO playback_history (video_id, title, artist, played, queued_at) VALUES (?, ?, ?, 0, ?)",
        (video_id, title, artist, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    logger.info(f"Recorded enqueued: {title} - {artist}")


def mark_as_played(video_id: str):
    conn = _connect()
    conn.execute(
        "UPDATE playback_history SET played=1, played_at=? WHERE video_id=? AND played=0",
        (datetime.now(timezone.utc).isoformat(), video_id),
    )
    affected = conn.total_changes
    conn.commit()
    conn.close()
    if affected:
        logger.info(f"Marked as played: {video_id}")


def get_all_history() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id, video_id, title, artist, played, queued_at, played_at "
        "FROM playback_history ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_count() -> int:
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM playback_history").fetchone()[0]
    conn.close()
    return count


def get_history_page(page: int = 1, page_size: int = 200) -> dict:
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM playback_history").fetchone()[0]
    total_pages = max(1, -(-total // page_size))
    offset = (page - 1) * page_size
    rows = conn.execute(
        "SELECT id, video_id, title, artist, played, queued_at, played_at "
        "FROM playback_history ORDER BY id DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    ).fetchall()
    conn.close()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def find_duplicates() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT video_id, title, artist, COUNT(*) as count, MIN(id) as first_id "
        "FROM playback_history "
        "GROUP BY video_id HAVING COUNT(*) > 1 "
        "ORDER BY count DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clean_duplicates() -> int:
    conn = _connect()
    dups = conn.execute(
        "SELECT video_id FROM playback_history "
        "GROUP BY video_id HAVING COUNT(*) > 1"
    ).fetchall()
    removed = 0
    for row in dups:
        ids = conn.execute(
            "SELECT id FROM playback_history WHERE video_id=? ORDER BY id ASC",
            (row["video_id"],),
        ).fetchall()
        keep_id = ids[0]["id"]
        remove_ids = [r["id"] for r in ids[1:]]
        if remove_ids:
            placeholders = ",".join("?" for _ in remove_ids)
            conn.execute(
                f"DELETE FROM playback_history WHERE id IN ({placeholders})",
                remove_ids,
            )
            removed += len(remove_ids)
    conn.commit()
    conn.close()
    logger.info(f"Cleaned {removed} duplicate entries")
    return removed
