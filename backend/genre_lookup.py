import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

GENRE_CACHE: dict[str, str] = {}


async def lookup_genre(artist: str, title: str) -> str:
    if not artist or not title:
        return "Unknown"
    cache_key = f"{artist.lower().strip()}|{title.lower().strip()}"
    cached = GENRE_CACHE.get(cache_key)
    if cached:
        return cached

    genre = await _try_deezer(artist, title)
    if not genre:
        genre = await _try_musicbrainz(artist, title)
    if not genre:
        genre = "Unknown"

    GENRE_CACHE[cache_key] = genre
    return genre


async def _try_deezer(artist: str, title: str) -> str | None:
    query = f'artist:"{artist}" track:"{title}"'
    url = f"https://api.deezer.com/search?q={quote(query)}&limit=1"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers={"Accept": "application/json"}, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("data"):
                    track = data["data"][0]
                    album_id = track.get("album", {}).get("id")
                    if album_id:
                        ar = await client.get(
                            f"https://api.deezer.com/album/{album_id}",
                            timeout=5,
                        )
                        if ar.status_code == 200:
                            album_data = ar.json()
                            genres = album_data.get("genres", {}).get("data", [])
                            if genres:
                                g = genres[0].get("name", "")
                                if g:
                                    logger.info("Deezer genre for %s - %s: %s", artist, title, g)
                                    return g
        except Exception as e:
            logger.debug("Deezer lookup failed for %s - %s: %s", artist, title, e)
    return None


async def _try_musicbrainz(artist: str, title: str) -> str | None:
    query = f'artist:{artist.replace(chr(34), "")} AND recording:{title.replace(chr(34), "")}'
    url = f"https://musicbrainz.org/ws/2/recording/?query={quote(query)}&fmt=json&limit=1"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(
                url,
                headers={"Accept": "application/json", "User-Agent": "AlexaMusicSkill/1.0 ( derbydx@hotmail.com )"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                recordings = data.get("recordings", [])
                if recordings:
                    tags = recordings[0].get("tags", [])
                    tag_counts: dict[str, int] = {}
                    for t in tags:
                        name = t.get("name", "")
                        count = t.get("count", 0)
                        if name:
                            tag_counts[name] = tag_counts.get(name, 0) + count
                    if tag_counts:
                        best = max(tag_counts, key=tag_counts.get)
                        logger.info("MusicBrainz genre for %s - %s: %s", artist, title, best)
                        return best
        except Exception as e:
            logger.debug("MusicBrainz lookup failed for %s - %s: %s", artist, title, e)
    return None
