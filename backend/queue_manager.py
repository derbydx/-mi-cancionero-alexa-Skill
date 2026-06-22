from music_service import search_song, get_watch_playlist
from config import settings


class QueueManager:
    def __init__(self):
        self._queue: list[dict] = []
        self._index: int = 0
        self._current_video_id: str | None = None
        self._looping: bool = False
        self._playback_offset: int = 0

    def start_from_query(self, query: str) -> dict:
        song = search_song(query)
        self._current_video_id = song["video_id"]
        self._queue = [song]
        self._index = 0
        self._playback_offset = 0
        self._refill(song["video_id"])
        return song

    def start_from_video_id(self, video_id: str, title: str = "", artist: str = "") -> dict:
        song = {"video_id": video_id, "title": title, "artist": artist}
        self._current_video_id = video_id
        self._queue = [song]
        self._index = 0
        self._playback_offset = 0
        self._refill(video_id)
        return song

    def _refill(self, video_id: str):
        try:
            tracks = get_watch_playlist(video_id, limit=settings.queue_refill_amount)
            existing_ids = {t["video_id"] for t in self._queue}
            for t in tracks:
                if t["video_id"] not in existing_ids:
                    self._queue.append(t)
                    existing_ids.add(t["video_id"])
        except Exception:
            pass

    def current(self) -> dict | None:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    def next(self) -> dict | None:
        if self._looping and self._current_video_id:
            self._playback_offset = 0
            return self.current()
        self._index += 1
        self._playback_offset = 0
        if self._index >= len(self._queue):
            if self._current_video_id:
                self._refill(self._current_video_id)
            if self._index >= len(self._queue):
                return None
        track = self._queue[self._index]
        self._current_video_id = track["video_id"]
        if len(self._queue) - self._index <= settings.queue_refill_threshold:
            self._refill(self._current_video_id)
        return track

    def skip(self) -> dict | None:
        if self._looping:
            self._looping = False
        return self.next()

    def save_offset(self, offset_ms: int):
        self._playback_offset = offset_ms

    def get_offset(self) -> int:
        return self._playback_offset

    def loop_on(self):
        self._looping = True

    def loop_off(self):
        self._looping = False

    def is_looping(self) -> bool:
        return self._looping


    def get_queue(self) -> dict:
        return {
            "current_index": self._index,
            "total": len(self._queue),
            "looping": self._looping,
            "current_video_id": self._current_video_id,
            "current": self.current(),
            "queue": self._queue,
        }


queue_manager = QueueManager()
