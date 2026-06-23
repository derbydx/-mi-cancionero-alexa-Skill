import os
import sqlite3
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "queue.db")


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_queue_db():
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queue_items (
            position INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL,
            title TEXT,
            artist TEXT,
            thumbnail TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queue_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            current_index INTEGER DEFAULT 0,
            current_video_id TEXT,
            looping INTEGER DEFAULT 0,
            playback_offset INTEGER DEFAULT 0,
            playback_token TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_queue(items: list[dict], state: dict):
    conn = _get_db()
    try:
        conn.execute("DELETE FROM queue_items")
        for pos, item in enumerate(items):
            conn.execute(
                "INSERT INTO queue_items (position, video_id, title, artist, thumbnail) VALUES (?, ?, ?, ?, ?)",
                (pos, item.get("video_id", ""), item.get("title", ""), item.get("artist", ""), item.get("thumbnail", "")),
            )
        conn.execute("""
            INSERT INTO queue_state (id, current_index, current_video_id, looping, playback_offset, playback_token)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                current_index=excluded.current_index,
                current_video_id=excluded.current_video_id,
                looping=excluded.looping,
                playback_offset=excluded.playback_offset,
                playback_token=excluded.playback_token
        """, (
            state.get("current_index", 0),
            state.get("current_video_id"),
            int(state.get("looping", False)),
            state.get("playback_offset", 0),
            state.get("playback_token"),
        ))
        conn.commit()
    finally:
        conn.close()


def load_queue() -> tuple[list[dict], dict] | tuple[None, None]:
    conn = _get_db()
    try:
        items_row = conn.execute("SELECT * FROM queue_items ORDER BY position").fetchall()
        state_row = conn.execute("SELECT * FROM queue_state WHERE id = 1").fetchone()
        if not state_row or not items_row:
            return None, None
        items = []
        for r in items_row:
            items.append({
                "video_id": r["video_id"],
                "title": r["title"] or "",
                "artist": r["artist"] or "",
                "thumbnail": r["thumbnail"] or "",
            })
        state = {
            "current_index": state_row["current_index"],
            "current_video_id": state_row["current_video_id"],
            "looping": bool(state_row["looping"]),
            "playback_offset": state_row["playback_offset"],
            "playback_token": state_row["playback_token"],
        }
        return items, state
    finally:
        conn.close()


def clear_queue():
    conn = _get_db()
    try:
        conn.execute("DELETE FROM queue_items")
        conn.execute("DELETE FROM queue_state WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
