import asyncio
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.getenv("AUDIO_CACHE_DIR", "/tmp/alexa_audio_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_MAX_AGE_SECONDS = int(os.getenv("AUDIO_CACHE_MAX_AGE", 3600))
CACHE_MAX_FILES = int(os.getenv("AUDIO_CACHE_MAX_FILES", 20))

_download_locks: dict[str, asyncio.Lock] = {}
_locks_mutex = asyncio.Lock()
_duration_cache: dict[str, float] = {}


def _cache_path(video_id: str) -> Path:
    safe = hashlib.sha1(video_id.encode()).hexdigest()[:12]
    return CACHE_DIR / f"{safe}_{video_id}.m4a"


async def _get_lock(video_id: str) -> asyncio.Lock:
    async with _locks_mutex:
        if video_id not in _download_locks:
            _download_locks[video_id] = asyncio.Lock()
        return _download_locks[video_id]


def _evict_old_files() -> None:
    files = sorted(CACHE_DIR.glob("*.m4a"), key=lambda f: f.stat().st_mtime)
    now = time.time()
    for f in files:
        if now - f.stat().st_mtime > CACHE_MAX_AGE_SECONDS:
            f.unlink(missing_ok=True)
            logger.debug("Cache evicted (age): %s", f.name)
    files = sorted(CACHE_DIR.glob("*.m4a"), key=lambda f: f.stat().st_mtime)
    while len(files) > CACHE_MAX_FILES:
        files.pop(0).unlink(missing_ok=True)
        logger.debug("Cache evicted (limit): %s", files)


async def _ensure_cached(video_id: str) -> Path:
    path = _cache_path(video_id)
    lock = await _get_lock(video_id)

    async with lock:
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age < CACHE_MAX_AGE_SECONDS:
                logger.info("Cache HIT: %s (%.0fs old)", video_id, age)
                return path
            path.unlink(missing_ok=True)
            logger.info("Cache EXPIRED: %s", video_id)

        logger.info("Cache MISS — downloading: %s", video_id)
        _evict_old_files()

        tmp_path = path.with_suffix(".tmp")
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio",
            "--no-playlist",
            "-o", str(tmp_path),
            f"https://www.youtube.com/watch?v={video_id}",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            err = stderr.decode(errors="replace")
            logger.error("yt-dlp failed for %s: %s", video_id, err)
            raise RuntimeError(f"yt-dlp error: {err[:200]}")

        if not tmp_path.exists():
            raise RuntimeError("yt-dlp did not produce output file")

        tmp_path.rename(path)
        size_kb = path.stat().st_size / 1024
        logger.info("Download complete: %s (%.1f KB)", video_id, size_kb)
        return path


async def _get_duration(video_id: str) -> float | None:
    if video_id in _duration_cache:
        logger.debug("Duration cache HIT: %s = %.1fs", video_id, _duration_cache[video_id])
        return _duration_cache[video_id]

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--print", "duration",
        "--no-playlist",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    for attempt in range(2):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                duration = float(stdout.decode().strip())
                _duration_cache[video_id] = duration
                return duration
        except Exception:
            pass
    logger.warning("Could not get duration for %s", video_id)
    return None


async def stream_audio(video_id: str, request: Request) -> Response:
    try:
        cache_file = await _ensure_cached(video_id)
    except Exception as e:
        logger.error("Error getting audio %s: %s", video_id, e)
        return Response(status_code=502, content=str(e))

    file_size = cache_file.stat().st_size
    duration = await _get_duration(video_id)

    range_header = request.headers.get("range", "")
    start, end = 0, file_size - 1

    if range_header:
        try:
            range_val = range_header.replace("bytes=", "")
            parts = range_val.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            end = min(end, file_size - 1)
        except Exception:
            return Response(status_code=416)

    content_length = end - start + 1

    with open(cache_file, "rb") as f:
        f.seek(start)
        data = f.read(content_length)

    headers = {
        "Content-Length": str(content_length),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Type": "audio/mp4",
        "Cache-Control": "no-cache",
    }
    if duration:
        headers["Content-Duration"] = str(int(duration))
        headers["X-Content-Duration"] = str(duration)

    status_code = 206 if range_header else 200
    logger.info(
        "Serving %s: %s bytes %d-%d/%d (status=%d)",
        video_id, content_length, start, end, file_size, status_code,
    )
    return Response(content=data, status_code=status_code, headers=headers)
