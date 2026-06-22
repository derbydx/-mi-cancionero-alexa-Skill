import asyncio
import logging
import sys

from fastapi import Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)


async def stream_audio(video_id: str, request: Request) -> Response:
    logger.info(f"Descargando audio con yt-dlp para {video_id}")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "-o", "-",
        f"https://www.youtube.com/watch?v={video_id}",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        logger.error(f"Timeout descargando {video_id}")
        return Response(status_code=504, media_type="text/plain",
                        content="Timeout descargando el flujo de audio")

    if proc.returncode != 0:
        logger.error(f"yt-dlp fallo: {stderr.decode()[:500]}")
        return Response(status_code=502, media_type="text/plain",
                        content="Error obteniendo el flujo de audio")

    data = stdout
    logger.info(f"Audio {video_id}: {len(data)} bytes")
    return Response(
        content=data,
        status_code=200,
        media_type="audio/mp4",
        headers={"Cache-Control": "no-cache", "Content-Length": str(len(data))},
    )
