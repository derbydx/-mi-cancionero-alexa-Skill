import asyncio
import logging
import urllib.request

from fastapi import Request
from fastapi.responses import StreamingResponse, Response

from music_service import get_streaming_url

logger = logging.getLogger(__name__)


def _fetch_audio(audio_url: str, range_header: str | None):
    req = urllib.request.Request(audio_url)
    if range_header:
        req.add_header("Range", range_header)
    resp = urllib.request.urlopen(req, timeout=30)
    content_type = resp.headers.get("Content-Type", "audio/mp4")
    content_length = resp.headers.get("Content-Length")
    status = 206 if (range_header and resp.headers.get("Content-Range")) else 200

    def stream():
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            yield chunk

    return stream(), content_type, content_length, status


async def stream_audio(video_id: str, request: Request) -> Response:
    logger.info(f"Resolviendo URL para {video_id}")
    try:
        audio_url = await asyncio.wait_for(get_streaming_url(video_id), timeout=30)
    except asyncio.TimeoutError:
        return Response(status_code=504, media_type="text/plain",
                        content="Timeout obteniendo el flujo de audio")

    range_header = request.headers.get("range")
    loop = asyncio.get_running_loop()

    try:
        stream_iter, content_type, content_length, status_code = (
            await loop.run_in_executor(None, _fetch_audio, audio_url, range_header)
        )
    except Exception as e:
        logger.error(f"Error obteniendo audio de YouTube: {e}")
        return Response(status_code=502, media_type="text/plain",
                        content="Error obteniendo el flujo de audio")

    resp_headers = {"Cache-Control": "no-cache"}
    if content_length:
        resp_headers["Content-Length"] = content_length

    async def _stream():
        try:
            for chunk in stream_iter:
                yield chunk
                await asyncio.sleep(0)
        except Exception:
            logger.exception("Error en stream de audio")

    return StreamingResponse(
        _stream(),
        status_code=status_code,
        media_type=content_type,
        headers=resp_headers,
    )
