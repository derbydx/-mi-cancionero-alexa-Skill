from music_service import search_song, get_watch_playlist
from config import settings
from history_manager import record_enqueued
from queue_db import save_queue, load_queue, clear_queue


class QueueManager:
    def __init__(self):
        self._queue: list[dict] = []
        self._index: int = 0
        self._current_video_id: str | None = None
        self._looping: bool = False
        self._playback_offset: int = 0
        self._playback_token: str | None = None
        self._restore_from_db()

    def _restore_from_db(self):
        items, state = load_queue()
        if items is not None and state is not None:
            self._queue = items
            self._index = state.get("current_index", 0)
            self._current_video_id = state.get("current_video_id")
            self._looping = state.get("looping", False)
            self._playback_offset = state.get("playback_offset", 0)
            self._playback_token = state.get("playback_token")

    def _save_to_db(self):
        save_queue(self._queue, {
            "current_index": self._index,
            "current_video_id": self._current_video_id,
            "looping": self._looping,
            "playback_offset": self._playback_offset,
            "playback_token": self._playback_token,
        })

    def start_from_query(self, query: str) -> dict:
        song = search_song(query)
        self._current_video_id = song["video_id"]
        self._queue = [song]
        self._index = 0
        self._playback_offset = 0
        record_enqueued(song["video_id"], song["title"], song["artist"])
        self._refill(song["video_id"])
        self._save_to_db()
        return song

    def start_from_video_id(self, video_id: str, title: str = "", artist: str = "") -> dict:
        song = {"video_id": video_id, "title": title, "artist": artist}
        self._current_video_id = video_id
        self._queue = [song]
        self._index = 0
        self._playback_offset = 0
        self._refill(video_id)
        self._save_to_db()
        return song

    def _refill(self, video_id: str):
        try:
            tracks = get_watch_playlist(video_id, limit=settings.queue_refill_amount)
            existing_ids = {t["video_id"] for t in self._queue}
            for t in tracks:
                if t["video_id"] not in existing_ids:
                    self._queue.append(t)
                    existing_ids.add(t["video_id"])
                    record_enqueued(t["video_id"], t.get("title", ""), t.get("artist", ""))
        except Exception:
            pass

    def current(self) -> dict | None:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    def peek_next(self) -> dict | None:
        n = self._index + 1
        if n < len(self._queue):
            return self._queue[n]
        if self._looping and self._queue:
            return self._queue[0]
        if self._current_video_id:
            self._refill(self._current_video_id)
        if n < len(self._queue):
            return self._queue[n]
        return None

    def next(self) -> dict | None:
        if self._looping and self._current_video_id:
            self._playback_offset = 0
            self._save_to_db()
            return self.current()
        self._index += 1
        self._playback_offset = 0
        if self._index >= len(self._queue):
            if self._current_video_id:
                self._refill(self._current_video_id)
            if self._index >= len(self._queue):
                self._save_to_db()
                return None
        track = self._queue[self._index]
        self._current_video_id = track["video_id"]
        if len(self._queue) - self._index <= settings.queue_refill_threshold:
            self._refill(self._current_video_id)
        self._save_to_db()
        return track

    def skip(self) -> dict | None:
        if self._looping:
            self._looping = False
        return self.next()

    def save_offset(self, offset_ms: int):
        self._playback_offset = offset_ms
        self._save_to_db()

    def get_offset(self) -> int:
        return self._playback_offset

    def loop_on(self):
        self._looping = True
        self._save_to_db()

    def loop_off(self):
        self._looping = False
        self._save_to_db()

    def is_looping(self) -> bool:
        return self._looping

    def clear(self):
        self._queue.clear()
        self._index = 0
        self._current_video_id = None
        self._playback_offset = 0
        self._playback_token = None
        clear_queue()

    def add_song(self, song: dict) -> int:
        if not self._queue:
            self._queue = [song]
            self._index = 0
            self._current_video_id = song["video_id"]
            self._playback_offset = 0
            record_enqueued(song["video_id"], song.get("title", ""), song.get("artist", ""))
            self._refill(song["video_id"])
            self._save_to_db()
            return 0
        self._queue.append(song)
        record_enqueued(song["video_id"], song.get("title", ""), song.get("artist", ""))
        self._save_to_db()
        return len(self._queue) - 1

    def set_playback_token(self, token: str):
        self._playback_token = token

    def get_playback_token(self) -> str | None:
        return self._playback_token

    def get_index(self) -> int:
        return self._index

    def get_queue(self) -> dict:
        return {
            "current_index": self._index,
            "total": len(self._queue),
            "looping": self._looping,
            "current_video_id": self._current_video_id,
            "playback_token": self._playback_token,
            "current": self.current(),
            "queue": self._queue,
        }


queue_manager = QueueManager()
