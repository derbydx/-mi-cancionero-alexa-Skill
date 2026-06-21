import asyncio
import logging

from fastapi import Request
from fastapi.responses import StreamingResponse

from music_service import get_streaming_url

logger = logging.getLogger(__name__)


async def _ffmpeg_stream(audio_url: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", audio_url,
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        "-f", "mp3",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _drain_stderr():
        while True:
            chunk = await proc.stderr.read(65536)
            if not chunk:
                break

    stderr_drainer = asyncio.create_task(_drain_stderr())

    async def read_output():
        try:
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        except asyncio.CancelledError:
            proc.kill()
            raise
        finally:
            stderr_drainer.cancel()
            if proc.returncode is None:
                proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    return read_output(), proc


async def stream_audio(video_id: str, request: Request) -> StreamingResponse:
    logger.info(f"Resolviendo URL para {video_id}")
    try:
        audio_url = await asyncio.wait_for(get_streaming_url(video_id), timeout=30)
    except asyncio.TimeoutError:
        logger.error(f"Timeout obteniendo URL para {video_id}")
        return StreamingResponse(
            content="Timeout obteniendo el flujo de audio",
            status_code=504,
            media_type="text/plain",
        )

    logger.info(f"Iniciando ffmpeg para {video_id}")

    try:
        stream_gen, proc = await asyncio.wait_for(_ffmpeg_stream(audio_url), timeout=30)
    except asyncio.TimeoutError:
        logger.error(f"Timeout iniciando ffmpeg para {video_id}")
        return StreamingResponse(
            content="Timeout iniciando conversion de audio",
            status_code=504,
            media_type="text/plain",
        )

    async def _stream():
        try:
            async for chunk in stream_gen:
                yield chunk
        except Exception:
            logger.exception("Error en stream de audio")

    return StreamingResponse(
        _stream(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
        },
    )