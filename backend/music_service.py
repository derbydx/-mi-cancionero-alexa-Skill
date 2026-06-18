import asyncio
from pathlib import Path

from ytmusicapi import YTMusic

from config import settings

_ytmusic: YTMusic | None = None


def init_ytmusic() -> YTMusic:
    global _ytmusic
    if _ytmusic is not None:
        return _ytmusic
    auth_file = Path(settings.yt_music_auth_file)
    if auth_file.exists():
        _ytmusic = YTMusic(str(auth_file))
    else:
        _ytmusic = YTMusic()
    return _ytmusic


def search_song(query: str) -> dict:
    yt = init_ytmusic()
    results = yt.search(query, filter="songs", limit=5)
    if not results:
        raise LookupError(f"No se encontro ninguna cancion para: {query}")
    best = results[0]
    return {
        "video_id": best["videoId"],
        "title": best.get("title", ""),
        "artist": ", ".join(a.get("name", "") for a in best.get("artists", [])),
        "thumbnail": best.get("thumbnails", [{}])[-1].get("url", ""),
    }


def get_watch_playlist(video_id: str, limit: int = 50) -> list[dict]:
    yt = init_ytmusic()
    playlist = yt.get_watch_playlist(videoId=video_id, limit=limit)
    tracks = playlist.get("tracks", [])
    result = []
    for t in tracks:
        vid = t.get("videoId")
        if not vid:
            continue
        result.append({
            "video_id": vid,
            "title": t.get("title", ""),
            "artist": ", ".join(a.get("name", "") for a in t.get("artists", [])),
        })
    return result


async def get_streaming_url(video_id: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "-g",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        f"https://www.youtube.com/watch?v={video_id}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp fallo: {stderr.decode().strip()}")
    url = stdout.decode().strip()
    if not url:
        raise RuntimeError("yt-dlp no devolvio una URL")
    return url
