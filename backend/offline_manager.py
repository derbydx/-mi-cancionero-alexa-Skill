import hashlib
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

OFFLINE_DIR = Path(os.getenv("OFFLINE_DIR", "/app/data/offline"))
OFFLINE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = Path(os.getenv("AUDIO_CACHE_DIR", "/app/data/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = os.getenv("OFFLINE_DB", os.path.join(os.path.dirname(__file__), "..", "data", "offline_tasks.db"))


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_offline_db():
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS offline_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL UNIQUE,
            title TEXT,
            artist TEXT,
            thumbnail TEXT,
            status TEXT DEFAULT 'pending',
            filepath TEXT,
            actual_title TEXT,
            actual_artist TEXT,
            error TEXT,
            attempts INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON offline_tasks(status)")
    conn.commit()
    conn.close()


def create_offline_task(video_id: str, title: str = "", artist: str = "", thumbnail: str = ""):
    conn = _get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO offline_tasks (video_id, title, artist, thumbnail) VALUES (?, ?, ?, ?)",
            (video_id, title, artist, thumbnail or ""),
        )
        conn.commit()
        inserted = conn.execute("SELECT changes()").fetchone()[0]
        if inserted:
            logger.info("Offline task created: %s - %s", video_id, title)
    finally:
        conn.close()


def get_pending_tasks(limit: int = 5) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM offline_tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_task_status(task_id: int, status: str, filepath: str = "", error: str = "",
                       actual_title: str = "", actual_artist: str = ""):
    conn = _get_db()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if status == "complete":
        conn.execute(
            "UPDATE offline_tasks SET status=?, filepath=?, actual_title=?, actual_artist=?, completed_at=? WHERE id=?",
            (status, filepath, actual_title, actual_artist, now, task_id),
        )
    elif status == "downloading":
        conn.execute("UPDATE offline_tasks SET status=?, attempts=attempts+1 WHERE id=?", (status, task_id))
    elif status == "failed":
        conn.execute("UPDATE offline_tasks SET status=?, error=? WHERE id=?", (status, error, task_id))
    else:
        conn.execute("UPDATE offline_tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()
    conn.close()


def get_task_status(video_id: str) -> dict | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM offline_tasks WHERE video_id = ?", (video_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_statuses_for_ids(video_ids: list[str]) -> dict[str, str]:
    if not video_ids:
        return {}
    conn = _get_db()
    placeholders = ",".join("?" for _ in video_ids)
    rows = conn.execute(
        f"SELECT video_id, status FROM offline_tasks WHERE video_id IN ({placeholders})",
        video_ids,
    ).fetchall()
    conn.close()
    return {r["video_id"]: r["status"] for r in rows}


def list_completed() -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM offline_tasks WHERE status = 'complete' ORDER BY completed_at DESC",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_offline(video_id: str) -> bool:
    conn = _get_db()
    row = conn.execute(
        "SELECT filepath FROM offline_tasks WHERE video_id = ? AND status = 'complete'",
        (video_id,),
    ).fetchone()
    conn.close()

    removed = False
    if row and row["filepath"]:
        fp = Path(row["filepath"])
        if fp.exists():
            fp.unlink()
            removed = True

    conn = _get_db()
    conn.execute("DELETE FROM offline_tasks WHERE video_id = ?", (video_id,))
    conn.commit()
    conn.close()
    return removed


def cache_path_for(video_id: str) -> Path:
    safe = hashlib.sha1(video_id.encode()).hexdigest()[:12]
    return CACHE_DIR / f"{safe}_{video_id}.m4a"


def offline_path_for(video_id: str, title: str = "", artist: str = "") -> Path:
    safe_title = _sanitize_filename(title or "unknown")
    safe_artist = _sanitize_filename(artist or "unknown")
    name = f"{safe_artist} - {safe_title}.m4a"
    if len(name) > 220:
        name = name[:215] + ".m4a"
    return OFFLINE_DIR / name


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:100] if name else "unknown"


def list_all_tasks() -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM offline_tasks ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ensure_download_tasks(songs: list[dict]):
    conn = _get_db()
    existing = set(
        r["video_id"] for r in
        conn.execute("SELECT video_id FROM offline_tasks").fetchall()
    )
    for s in songs:
        vid = s.get("video_id", "")
        if vid and vid not in existing:
            conn.execute(
                "INSERT OR IGNORE INTO offline_tasks (video_id, title, artist, thumbnail) VALUES (?, ?, ?, ?)",
                (vid, s.get("title", ""), s.get("artist", ""), s.get("thumbnail", "")),
            )
    conn.commit()
    conn.close()


def retry_task(video_id: str) -> bool:
    conn = _get_db()
    conn.execute(
        "UPDATE offline_tasks SET status='pending', error='', attempts=0 WHERE video_id=? AND status='failed'",
        (video_id,)
    )
    affected = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    return affected > 0
