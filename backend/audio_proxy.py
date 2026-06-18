import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse

from music_service import get_streaming_url


async def _stream_from_url(url: str, range_header: str | None = None):
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if range_header:
        request_headers["Range"] = range_header

    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("GET", url, headers=request_headers) as response:
            async for chunk in response.aiter_bytes(chunk_size=65536):
                yield chunk


async def stream_audio(video_id: str, request: Request) -> StreamingResponse:
    range_header = request.headers.get("range")
    audio_url = await get_streaming_url(video_id)
    status_code = 206 if range_header else 200
    return StreamingResponse(
        _stream_from_url(audio_url, range_header),
        status_code=status_code,
        media_type="audio/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        },
    )
