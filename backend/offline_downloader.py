import asyncio
import logging
import os
import re
import sys
import shutil
import subprocess
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

from backend.offline_manager import cache_path_for, offline_path_for, get_task_status

current_proc = None
cancel_requested = False

cancel_app = FastAPI()

@cancel_app.post("/cancel")
async def handle_cancel():
    global current_proc, cancel_requested
    cancel_requested = True
    if current_proc:
        try:
            current_proc.kill()
            await asyncio.wait_for(current_proc.wait(), timeout=5)
        except Exception:
            pass
        current_proc = None
        logger.info("Download cancelled via /cancel endpoint")
    return {"ok": True}

async def run_cancel_server():
    config = uvicorn.Config(cancel_app, host="0.0.0.0", port=8001, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("offline-downloader")

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
MAX_RETRIES = 2
RETRY_DELAYS = [30]

OFFLINE_DIR = Path(os.getenv("OFFLINE_DIR", "/app/data/offline"))
OFFLINE_DIR.mkdir(parents=True, exist_ok=True)


async def fetch_pending(client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(f"{BACKEND_URL}/api/offline/tasks/pending", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("Failed to fetch pending tasks: %s", e)
    return []


async def report_status(client: httpx.AsyncClient, task_id: int, status: str,
                        filepath: str = "", error: str = "",
                        actual_title: str = "", actual_artist: str = ""):
    try:
        await client.post(
            f"{BACKEND_URL}/api/offline/tasks/{task_id}/status",
            json={
                "status": status,
                "filepath": filepath,
                "error": error,
                "actual_title": actual_title,
                "actual_artist": actual_artist,
            },
            timeout=10,
        )
    except Exception as e:
        logger.warning("Failed to report status for task %d: %s", task_id, e)


def file_exists_in_offline(video_id: str) -> Path | None:
    status = get_task_status(video_id)
    if status and status.get("filepath"):
        fp = Path(status["filepath"])
        if fp.exists():
            return fp
    return None


async def process_task(client: httpx.AsyncClient, task: dict):
    tid = task["id"]
    vid = task["video_id"]
    title = task.get("title", "")
    artist = task.get("artist", "")

    logger.info("Processing task %d: %s - %s", tid, artist, title)

    await report_status(client, tid, "downloading")
    await report_progress(client, tid, 0)

    existing = file_exists_in_offline(vid)
    if existing:
        logger.info("File already exists offline: %s", existing.name)
        await report_status(client, tid, "complete",
                            filepath=str(existing),
                            actual_title=title, actual_artist=artist)
        return

    try:
        filepath = await download_song(client, tid, vid, title, artist)
        await report_status(client, tid, "complete",
                            filepath=str(filepath),
                            actual_title=title, actual_artist=artist)
    except Exception as e:
        logger.error("Download failed for %s: %s", vid, e)
        await report_status(client, tid, "failed", error=str(e))


def _parse_progress_line(line: str) -> dict:
    data = {}
    m = re.search(r"(\d+\.?\d*)%", line)
    if m:
        data["progress"] = float(m.group(1))
    m = re.search(r"of\s+([\d.]+)\s*(\S+)", line)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("MiB"):
            data["total_mb"] = round(val * 1.048576, 1)
        elif unit.startswith("KiB"):
            data["total_mb"] = round(val / 1024, 1)
        elif unit.startswith("GiB"):
            data["total_mb"] = round(val * 1073.742, 1)
        else:
            data["total_mb"] = round(val, 1)
    m = re.search(r"at\s+([\d.]+)\s*(\S+)", line)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("MiB"):
            data["speed_mb_s"] = round(val * 1.048576, 2)
        elif unit.startswith("KiB"):
            data["speed_mb_s"] = round(val / 1024, 2)
        else:
            data["speed_mb_s"] = round(val, 2)
    m = re.search(r"ETA\s+(\S+)", line)
    if m:
        data["eta"] = m.group(1)
    return data


async def report_progress(client: httpx.AsyncClient, task_id: int, progress: float,
                          total_mb: float = 0.0, speed_mb_s: float = 0.0, eta: str = ""):
    try:
        await client.post(
            f"{BACKEND_URL}/api/offline/tasks/{task_id}/progress",
            json={"progress": round(progress, 1), "total_mb": total_mb, "speed_mb_s": speed_mb_s, "eta": eta},
            timeout=5,
        )
    except Exception as e:
        logger.warning("Failed to report progress for task %d: %s", task_id, e)


async def download_song(client: httpx.AsyncClient, task_id: int, video_id: str, title: str, artist: str) -> Path:
    cached = cache_path_for(video_id)
    if cached.exists():
        logger.info("Copying from cache: %s", cached)
        dest = offline_path_for(video_id, title, artist)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, dest)
        _embed_metadata(dest, title, artist)
        return dest

    dest = offline_path_for(video_id, title, artist)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.m4a")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--no-playlist",
        "--newline",
        "--embed-metadata",
        "--parse-metadata", f"title:{title}",
        "--parse-metadata", f"artist:{artist}",
        "-o", str(tmp),
        f"https://www.youtube.com/watch?v={video_id}",
    ]

    progress_re = re.compile(r"(\d+\.?\d*)%")
    last_report = 0.0

    for attempt in range(MAX_RETRIES):
        global current_proc, cancel_requested
        if cancel_requested:
            cancel_requested = False
            raise RuntimeError("Cancelled by user")

        logger.info("yt-dlp attempt %d/%d for %s", attempt + 1, MAX_RETRIES, video_id)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        current_proc = proc

        stderr_lines = []
        last_progress = 0.0

        try:
            async with asyncio.timeout(180):
                while True:
                    line_bytes = await proc.stderr.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode(errors="replace").strip()
                    stderr_lines.append(line)

                    m = progress_re.search(line)
                    if m:
                        try:
                            pct = float(m.group(1))
                            last_progress = pct
                            if pct - last_report >= 5 or pct >= 100:
                                last_report = pct
                                extra = _parse_progress_line(line)
                                await report_progress(
                                    client, task_id, pct,
                                    total_mb=extra.get("total_mb", 0),
                                    speed_mb_s=extra.get("speed_mb_s", 0),
                                    eta=extra.get("eta", ""),
                                )
                        except ValueError:
                            pass

                await proc.wait()
        except asyncio.TimeoutError:
            current_proc = None
            proc.kill()
            await proc.wait()
            tmp.unlink(missing_ok=True)
            logger.warning("yt-dlp attempt %d timed out", attempt + 1)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])
            continue

        current_proc = None
        if proc.returncode == 0 and tmp.exists():
            await report_progress(client, task_id, 100)
            _embed_metadata(tmp, title, artist)
            tmp.rename(dest)
            size_kb = dest.stat().st_size / 1024
            logger.info("Downloaded: %s (%.1f KB)", dest.name, size_kb)
            return dest

        current_proc = None
        stderr_text = "\n".join(stderr_lines[-10:])[:500]
        logger.warning("yt-dlp attempt %d failed: %s", attempt + 1, stderr_text)
        tmp.unlink(missing_ok=True)

        if cancel_requested:
            cancel_requested = False
            raise RuntimeError("Cancelled by user")

        if attempt < MAX_RETRIES - 1:
            wait = RETRY_DELAYS[attempt]
            logger.info("Waiting %ds before retry...", wait)
            await asyncio.sleep(wait)

    raise RuntimeError(f"yt-dlp failed after {MAX_RETRIES} attempts")


def _embed_metadata(filepath: Path, title: str, artist: str):
    try:
        from mutagen.mp4 import MP4
        mp4 = MP4(str(filepath))
        mp4["\xa9nam"] = [title]
        mp4["\xa9ART"] = [artist]
        mp4.save()
        logger.info("Metadata embedded: %s - %s", artist, title)
    except ImportError:
        logger.warning("mutagen not available, skipping metadata embed")
    except Exception as e:
        logger.warning("Failed to embed metadata: %s", e)


async def check_paused(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get(f"{BACKEND_URL}/api/offline/downloader/paused", timeout=10)
        if r.status_code == 200:
            return r.json().get("paused", True)
    except Exception as e:
        logger.warning("Failed to check paused status: %s", e)
    return True


async def set_paused(client: httpx.AsyncClient, paused: bool):
    try:
        await client.post(
            f"{BACKEND_URL}/api/offline/downloader/paused",
            json={"paused": paused},
            timeout=10,
        )
    except Exception as e:
        logger.warning("Failed to set paused status: %s", e)


async def reset_stuck_tasks(client: httpx.AsyncClient):
    try:
        r = await client.get(f"{BACKEND_URL}/api/offline/tasks/stuck", timeout=10)
        data = r.json()
        if data.get("reset", 0) > 0:
            logger.info("Reset %d stuck tasks to failed", data["reset"])
    except Exception as e:
        logger.warning("Failed to reset stuck tasks: %s", e)

async def main_loop():
    logger.info("Offline downloader started. Polling %s every %ds", BACKEND_URL, POLL_INTERVAL)
    async with httpx.AsyncClient() as client:
        await reset_stuck_tasks(client)
        while True:
            try:
                paused = await check_paused(client)
                if paused:
                    await asyncio.sleep(30)
                    continue

                tasks = await fetch_pending(client)
                for task in tasks:
                    await process_task(client, task)
                    await asyncio.sleep(1)

                if not tasks:
                    await set_paused(client, True)
            except Exception as e:
                logger.error("Unexpected error in main loop: %s", e)
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    async def run_all():
        await asyncio.gather(main_loop(), run_cancel_server())

    asyncio.run(run_all())
