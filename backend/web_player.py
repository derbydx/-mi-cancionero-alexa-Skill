import logging
import os
import sqlite3
import time

import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from music_service import init_ytmusic, get_watch_playlist

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("WEB_QUEUE_DB_PATH", "/app/data/web_queue.db")
REFILL_THRESHOLD = 5
REFILL_AMOUNT = 20

web_router = APIRouter(prefix="/web-player")


def init_web_queue_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS web_queue_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position INTEGER NOT NULL,
            video_id TEXT NOT NULL,
            title TEXT NOT NULL,
            artist TEXT DEFAULT '',
            thumbnail TEXT DEFAULT '',
            duration INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS web_queue_state (
            id INTEGER PRIMARY KEY DEFAULT 1,
            current_index INTEGER NOT NULL DEFAULT -1,
            token TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("INSERT OR IGNORE INTO web_queue_state (id, current_index, token) VALUES (1, -1, '')")
    conn.commit()
    conn.close()


class WebQueueManager:
    def __init__(self):
        init_web_queue_db()
        self._queue: list[dict] = []
        self._current_index: int = -1
        self._restore()

    def _get_conn(self):
        return sqlite3.connect(DB_PATH)

    def _restore(self):
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, position, video_id, title, artist, thumbnail, duration "
            "FROM web_queue_items ORDER BY position"
        ).fetchall()
        self._queue = []
        for row in rows:
            self._queue.append({
                "id": row[0], "video_id": row[2], "title": row[3],
                "artist": row[4], "thumbnail": row[5], "duration": row[6],
            })
        state = conn.execute(
            "SELECT current_index FROM web_queue_state WHERE id=1"
        ).fetchone()
        self._current_index = state[0] if state else -1
        conn.close()

    def _save(self):
        conn = self._get_conn()
        conn.execute("DELETE FROM web_queue_items")
        for i, item in enumerate(self._queue):
            conn.execute(
                "INSERT INTO web_queue_items (position, video_id, title, artist, thumbnail, duration) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (i, item["video_id"], item["title"], item["artist"],
                 item["thumbnail"], item.get("duration", 0)),
            )
        conn.execute(
            "UPDATE web_queue_state SET current_index=? WHERE id=1",
            (self._current_index,),
        )
        conn.commit()
        conn.close()

    def get_queue(self):
        return {
            "queue": self._queue,
            "current_index": self._current_index,
        }

    def add_song(self, song: dict):
        was_empty = len(self._queue) == 0
        self._queue.append(song)
        if was_empty:
            self._current_index = 0
        self._save()
        if len(self._queue) - self._current_index - 1 <= REFILL_THRESHOLD:
            self._refill()
        return self._queue, self._current_index

    def set_current(self, index: int):
        if 0 <= index < len(self._queue):
            self._current_index = index
            self._save()

    def next(self):
        if self._current_index < len(self._queue) - 1:
            self._current_index += 1
            self._save()
            remaining = len(self._queue) - self._current_index - 1
            if remaining <= REFILL_THRESHOLD:
                self._refill()
            return self._queue[self._current_index]
        self._current_index = -1
        self._save()
        return None

    def prev(self):
        if self._current_index > 0:
            self._current_index -= 1
            self._save()
            return self._queue[self._current_index]
        if self._current_index == 0:
            return self._queue[0]
        return None

    def reorder(self, from_pos: int, to_pos: int):
        if 0 <= from_pos < len(self._queue) and 0 <= to_pos < len(self._queue):
            item = self._queue.pop(from_pos)
            self._queue.insert(to_pos, item)
            if self._current_index == from_pos:
                self._current_index = to_pos
            elif from_pos < self._current_index <= to_pos:
                self._current_index -= 1
            elif to_pos <= self._current_index < from_pos:
                self._current_index += 1
            self._save()
            return self.get_queue()
        return None

    def remove(self, item_id: int):
        for i, item in enumerate(self._queue):
            if item["id"] == item_id:
                self._queue.pop(i)
                if self._current_index > i:
                    self._current_index -= 1
                elif self._current_index == i:
                    self._current_index = min(i, len(self._queue) - 1)
                self._save()
                return self.get_queue()
        return None

    def _refill(self):
        if not self._queue:
            return
        if self._current_index < 0 or self._current_index >= len(self._queue):
            vid = self._queue[-1]["video_id"]
        else:
            vid = self._queue[self._current_index]["video_id"]
        try:
            tracks = get_watch_playlist(vid, limit=REFILL_AMOUNT)
            existing_ids = {item["video_id"] for item in self._queue}
            added = 0
            for t in tracks:
                if t["video_id"] not in existing_ids:
                    self._queue.append(t)
                    existing_ids.add(t["video_id"])
                    added += 1
            if added > 0:
                self._save()
                logger.info("Web-player refill: added %d tracks", added)
        except Exception as e:
            logger.warning("Web-player refill failed: %s", e)

    def search(self, query: str) -> list[dict]:
        yt = init_ytmusic()
        results = yt.search(query, filter="songs", limit=5)
        songs = []
        for r in results:
            vid = r.get("videoId")
            if not vid:
                continue
            songs.append({
                "video_id": vid,
                "title": r.get("title", ""),
                "artist": ", ".join(
                    a.get("name", "") for a in r.get("artists", [])
                ),
                "thumbnail": r.get("thumbnails", [{}])[-1].get("url", ""),
                "duration": r.get("duration"),
            })
        return songs


web_queue = WebQueueManager()


# ── Serve frontend ────────────────────────────────────────────────────────

@web_router.get("/")
async def web_player_index():
    path = os.path.join(os.path.dirname(__file__), "static", "web-player", "index.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Web Player</h1><p>Frontend no encontrado.</p>")


# ── API endpoints ─────────────────────────────────────────────────────────

@web_router.get("/api/search")
async def search(q: str = ""):
    if not q.strip():
        return {"results": []}
    results = web_queue.search(q.strip())
    return {"results": results}


@web_router.get("/api/queue")
async def get_queue():
    return web_queue.get_queue()


@web_router.post("/api/queue")
async def add_to_queue(request: Request):
    body = await request.json()
    song = {
        "video_id": body["video_id"],
        "title": body.get("title", ""),
        "artist": body.get("artist", ""),
        "thumbnail": body.get("thumbnail", ""),
        "duration": body.get("duration", 0),
    }
    web_queue.add_song(song)
    return web_queue.get_queue()


@web_router.post("/api/queue/play/{index}")
async def play_from_queue(index: int):
    web_queue.set_current(index)
    return web_queue.get_queue()


@web_router.post("/api/queue/next")
async def next_track():
    song = web_queue.next()
    return {"song": song, "queue": web_queue.get_queue()}


@web_router.post("/api/queue/prev")
async def prev_track():
    song = web_queue.prev()
    return {"song": song, "queue": web_queue.get_queue()}


@web_router.post("/api/queue/reorder")
async def reorder_queue(request: Request):
    body = await request.json()
    result = web_queue.reorder(body["from"], body["to"])
    if result is None:
        return JSONResponse(status_code=400, content={"error": "Invalid positions"})
    return result


@web_router.delete("/api/queue/{item_id}")
async def remove_from_queue(item_id: int):
    result = web_queue.remove(item_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "Item not found"})
    return result


@web_router.get("/api/favorites")
async def get_favorites():
    from favorites_manager import get_favorites
    return {"favorites": get_favorites()}


@web_router.post("/api/favorites/toggle/{video_id}")
async def toggle_favorite(video_id: str):
    from favorites_manager import is_favorite, add_favorite, remove_favorite
    if is_favorite(video_id):
        remove_favorite(video_id)
        return {"favorited": False}
    else:
        add_favorite(video_id)
        return {"favorited": True}
