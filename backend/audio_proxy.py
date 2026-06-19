import asyncio
import logging

from fastapi import Request
from fastapi.responses import StreamingResponse

from music_service import get_streaming_url

logger = logging.getLogger(__name__)


async def _ffmpeg_stream(audio_url: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", audio_url,
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        "-f", "mp3",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

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
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    return read_output(), proc


async def stream_audio(video_id: str, request: Request) -> StreamingResponse:
    audio_url = await get_streaming_url(video_id)
    logger.info(f"Iniciando ffmpeg para {video_id}")

    stream_gen, proc = await _ffmpeg_stream(audio_url)

    async def _stream():
        stderr_task = None

        async def _drain_stderr():
            remaining = await proc.stderr.read()
            if remaining:
                logger.debug(f"ffmpeg stderr: {remaining.decode(errors='replace')[:200]}")

        try:
            async for chunk in stream_gen:
                yield chunk
        except Exception:
            logger.exception("Error en stream de audio")
            proc.kill()
        finally:
            stderr_task = asyncio.create_task(_drain_stderr())

    return StreamingResponse(
        _stream(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
        },
    )