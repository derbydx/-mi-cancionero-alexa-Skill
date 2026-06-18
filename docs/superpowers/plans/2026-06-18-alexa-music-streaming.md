# Alexa Music Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Servicio de música por voz donde un Echo Dot reproduce música de YouTube Music via un backend local en PC Windows, expuesto con Cloudflare Tunnel.

**Architecture:** FastAPI en Windows recibe intents de Alexa via Cloudflare Tunnel, busca música con ytmusicapi, hace streaming de audio via proxy con yt-dlp. AudioPlayer del Echo Dot consume el stream proxiado. Cola en memoria, sin bases de datos externas.

**Tech Stack:** Python 3.11, FastAPI, ytmusicapi, yt-dlp, httpx, ask-sdk-webservice-support, Cloudflare Tunnel, Alexa Custom Skill (AudioPlayer)

## Global Constraints

- Todas las dependencias de Python pinned en `requirements.txt`
- Sin bases de datos externas (queue en memoria únicamente)
- El proxy de audio debe soportar `Accept-Ranges: bytes` y reenviar header `Range` para seek de Alexa
- Servidor corre en `localhost:8000`, expuesto via Cloudflare Tunnel
- Endpoint Alexa skill: `POST https://tudominio.com/alexa`
- Endpoint audio stream: `GET https://tudominio.com/proxy/audio/{video_id}`
- Idioma: Español (MX/ES) para la skill de Alexa
- Python 3.11+ (no 3.14)
- `load_dotenv()` ejecutado antes de importar `config`
- Lazy URL resolution: `get_streaming_url` se llama en el momento del stream, no al encolar

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/config.py`
- Create: `backend/requirements.txt`
- Create: `.gitignore`
- Create: `.env`

**Interfaces:**
- Consumes: nothing
- Produces: `config.py` con `Settings` dataclass. Otros módulos importan `from config import settings`.

- [ ] **Step 1: Create `.gitignore`**

```
.env
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
.venv/
venv/
headers_auth.json
```

- [ ] **Step 2: Create `backend/requirements.txt`**

```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
ytmusicapi>=1.7.0
yt-dlp>=2024.4.0
httpx>=0.27.0
python-dotenv>=1.0.0
ask-sdk-webservice-support>=1.20.0
```

- [ ] **Step 3: Create `backend/config.py`**

```python
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    yt_music_auth_file: str = field(
        default_factory=lambda: os.getenv(
            "YT_MUSIC_AUTH_FILE",
            os.path.join(os.path.dirname(__file__), "..", "headers_auth.json"),
        )
    )
    proxy_base_url: str = field(default_factory=lambda: os.getenv("PROXY_BASE_URL", "http://localhost:8000"))
    queue_refill_threshold: int = field(default_factory=lambda: int(os.getenv("QUEUE_REFILL_THRESHOLD", "5")))
    queue_refill_amount: int = field(default_factory=lambda: int(os.getenv("QUEUE_REFILL_AMOUNT", "20")))
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    skip_signature_verification: bool = field(
        default_factory=lambda: os.getenv("SKIP_SIGNATURE_VERIFICATION", "false").lower() == "true"
    )


settings = Settings()
```

- [ ] **Step 4: Create `.env`**

```
PROXY_BASE_URL=https://tudominio.com
HOST=0.0.0.0
PORT=8000
SKIP_SIGNATURE_VERIFICATION=true
```

- [ ] **Step 5: Create `backend/__init__.py`**

Archivo vacío.

---

### Task 2: Music service (ytmusicapi integration)

**Files:**
- Create: `backend/music_service.py`

**Interfaces:**
- Consumes: `config.settings.yt_music_auth_file`
- Produces:
  - `init_ytmusic() -> YTMusic` — singleton, llamado en startup
  - `search_song(query: str) -> dict` — retorna `{"video_id", "title", "artist", "thumbnail"}` o lanza `LookupError`
  - `get_watch_playlist(video_id: str, limit: int = 50) -> list[dict]`
  - `async get_streaming_url(video_id: str) -> str` — resuelve URL con yt-dlp via subprocess async

- [ ] **Step 1: Create `backend/music_service.py`**

```python
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
```

---

### Task 3: Queue manager

**Files:**
- Create: `backend/queue_manager.py`

**Interfaces:**
- Consumes: `music_service.search_song()`, `music_service.get_watch_playlist()`
- Produces:
  - `queue_manager` singleton (instancia de `QueueManager`)
  - `queue_manager.start_from_query(query: str) -> dict`
  - `queue_manager.start_from_video_id(video_id, title, artist) -> dict`
  - `queue_manager.current() -> dict | None`
  - `queue_manager.next() -> dict | None`
  - `queue_manager.skip() -> dict | None`
  - `queue_manager.save_offset(offset_ms: int)`
  - `queue_manager.get_offset() -> int`
  - `queue_manager.loop_on()`, `loop_off()`, `is_looping() -> bool`

- [ ] **Step 1: Create `backend/queue_manager.py`**

```python
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


queue_manager = QueueManager()
```

---

### Task 4: Audio proxy

**Files:**
- Create: `backend/audio_proxy.py`

**Interfaces:**
- Consumes: `music_service.get_streaming_url()` (async)
- Produces: `async stream_audio(video_id: str, request: Request) -> StreamingResponse`

- [ ] **Step 1: Create `backend/audio_proxy.py`**

```python
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
```

---

### Task 5: Alexa handler

**Files:**
- Create: `backend/alexa_handler.py`

**Interfaces:**
- Consumes: `queue_manager` singleton, `config.settings.proxy_base_url`
- Produces:
  - `handle_alexa_request(body: dict) -> dict`
  - `build_play_directive(url: str, token: str, offset: int = 0) -> dict`
  - `build_speech_response(text: str) -> dict`

- [ ] **Step 1: Create `backend/alexa_handler.py`**

```python
import uuid

from queue_manager import queue_manager
from config import settings


def handle_alexa_request(body: dict) -> dict:
    request = body.get("request", {})
    request_type = request.get("type", "")
    intent = request.get("intent", {})

    if request_type == "LaunchRequest":
        return build_speech_response("Di el nombre de una cancion o artista para comenzar.")
    elif request_type == "IntentRequest":
        return _handle_intent(intent)
    elif request_type.startswith("AudioPlayer."):
        return _handle_audio_player(request_type, request)
    else:
        return build_speech_response("No entiendo ese comando.")


def _handle_intent(intent: dict) -> dict:
    name = intent.get("name", "")

    if name == "BuscarMusicaIntent":
        slots = intent.get("slots", {})
        artista = slots.get("artista", {}).get("value", "")
        cancion = slots.get("cancion", {}).get("value", "")
        query = f"{artista} {cancion}".strip()
        if not query:
            return build_speech_response("Por favor, dime que cancion o artista quieres escuchar.")
        try:
            song = queue_manager.start_from_query(query)
            url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
            token = str(uuid.uuid4())
            return build_play_directive(url, token, 0)
        except LookupError:
            return build_speech_response(f"No encontre ninguna cancion para {query}.")
        except Exception:
            return build_speech_response("Hubo un error al buscar la musica.")

    elif name == "AMAZON.NextIntent":
        song = queue_manager.skip()
        if song is None:
            return build_speech_response("No hay mas canciones en la cola.")
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        return build_play_directive(url, str(uuid.uuid4()), 0)

    elif name == "AMAZON.PauseIntent":
        return {"version": "1.0", "response": {"directives": [{"type": "AudioPlayer.Stop"}], "shouldEndSession": True}}

    elif name == "AMAZON.ResumeIntent":
        current = queue_manager.current()
        if current is None:
            return build_speech_response("No hay musica reproduciendose.")
        url = f"{settings.proxy_base_url}/proxy/audio/{current['video_id']}"
        offset = queue_manager.get_offset()
        return build_play_directive(url, str(uuid.uuid4()), offset)

    elif name == "AMAZON.StopIntent":
        return {"version": "1.0", "response": {"directives": [{"type": "AudioPlayer.Stop"}], "shouldEndSession": True}}

    elif name == "AMAZON.LoopOnIntent":
        queue_manager.loop_on()
        return build_speech_response("Repeticion activada.")

    elif name == "AMAZON.LoopOffIntent":
        queue_manager.loop_off()
        return build_speech_response("Repeticion desactivada.")

    elif name == "AMAZON.StartOverIntent":
        current = queue_manager.current()
        if current is None:
            return build_speech_response("No hay musica reproduciendose.")
        url = f"{settings.proxy_base_url}/proxy/audio/{current['video_id']}"
        return build_play_directive(url, str(uuid.uuid4()), 0)

    else:
        return build_speech_response("No entiendo ese comando.")


def _handle_audio_player(request_type: str, request: dict) -> dict:
    token = request.get("token", "")
    offset = request.get("offsetInMilliseconds", 0)

    if request_type == "AudioPlayer.PlaybackNearlyFinished":
        song = queue_manager.next()
        if song is None:
            return {"version": "1.0", "response": {}}
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        return {
            "version": "1.0",
            "response": {
                "directives": [{
                    "type": "AudioPlayer.Play",
                    "playBehavior": "ENQUEUE",
                    "audioItem": {
                        "stream": {
                            "url": url,
                            "token": str(uuid.uuid4()),
                            "expectedPreviousToken": token,
                            "offsetInMilliseconds": 0,
                        }
                    },
                }]
            },
        }

    elif request_type == "AudioPlayer.PlaybackStopped":
        queue_manager.save_offset(offset)
        return {"version": "1.0", "response": {}}

    elif request_type in (
        "AudioPlayer.PlaybackStarted",
        "AudioPlayer.PlaybackFinished",
    ):
        return {"version": "1.0", "response": {}}

    elif request_type == "AudioPlayer.PlaybackFailed":
        song = queue_manager.skip()
        if song is None:
            return {"version": "1.0", "response": {}}
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        return build_play_directive(url, str(uuid.uuid4()), 0)

    return {"version": "1.0", "response": {}}


def build_play_directive(url: str, token: str, offset: int = 0) -> dict:
    return {
        "version": "1.0",
        "response": {
            "directives": [{
                "type": "AudioPlayer.Play",
                "playBehavior": "REPLACE_ALL",
                "audioItem": {
                    "stream": {
                        "url": url,
                        "token": token,
                        "expectedPreviousToken": None,
                        "offsetInMilliseconds": offset,
                    }
                },
            }],
            "shouldEndSession": True,
        },
    }


def build_speech_response(text: str) -> dict:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": False,
        },
    }
```

---

### Task 6: FastAPI application (main.py)

**Files:**
- Create: `backend/main.py`

**Interfaces:**
- Consumes: `handle_alexa_request`, `stream_audio`, `init_ytmusic`, `settings`
- Produces: servidor FastAPI con endpoints `POST /alexa`, `GET /proxy/audio/{video_id}`, `GET /health`

- [ ] **Step 1: Create `backend/main.py`**

```python
import logging

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ask_sdk_webservice_support.verifier import (
    RequestVerifier,
    TimestampVerifier,
    VerificationException,
)

from config import settings
from alexa_handler import handle_alexa_request
from audio_proxy import stream_audio
from music_service import init_ytmusic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Alexa Music Streaming")

_verifiers = [RequestVerifier(), TimestampVerifier()]


@app.on_event("startup")
async def startup():
    try:
        init_ytmusic()
        logger.info("YTMusic initialized")
    except Exception as e:
        logger.warning(f"YTMusic init warning: {e}")


@app.post("/alexa")
async def alexa_endpoint(request: Request):
    body_bytes = await request.body()
    if not settings.skip_signature_verification:
        try:
            for verifier in _verifiers:
                verifier.verify(
                    dict(request.headers),
                    body_bytes.decode("utf-8"),
                    body_bytes.decode("utf-8"),
                )
        except VerificationException as e:
            logger.warning(f"Firma de Alexa invalida: {e}")
            return JSONResponse(status_code=400, content={"error": "Invalid signature"})
    else:
        logger.debug("Verificacion de firma DESACTIVADA (modo desarrollo)")

    try:
        body = await request.json()
        logger.info(f"Alexa request type: {body.get('request', {}).get('type')}")
        response = handle_alexa_request(body)
        return JSONResponse(content=response)
    except Exception as e:
        logger.error(f"Error handling Alexa request: {e}")
        return JSONResponse(content={
            "version": "1.0",
            "response": {
                "outputSpeech": {"type": "PlainText", "text": "Hubo un error."},
                "shouldEndSession": True,
            }
        })


@app.get("/proxy/audio/{video_id}")
async def proxy_audio(video_id: str, request: Request):
    return await stream_audio(video_id, request)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

### Task 7: Install dependencies and test locally

**Files:** ninguno (operacional)

- [ ] **Step 1: Verify Python version**
- [ ] **Step 2: Create venv + install deps**
- [ ] **Step 3: Start server**
- [ ] **Step 4: Test health endpoint**
- [ ] **Step 5: Test LaunchRequest**
- [ ] **Step 6: Auth ytmusicapi**
- [ ] **Step 7: Verify search works**

---

### Task 8: Alexa skill configuration

**Files:** ninguno (configuración cloud)

- [ ] **Step 1: Create Custom Skill on developer.amazon.com**
- [ ] **Step 2: Paste interaction model in JSON Editor**
- [ ] **Step 3: Save Model + Build Model**
- [ ] **Step 4: Set endpoint to `https://tudominio.com/alexa`**
- [ ] **Step 5: Enable Audio Player interface**
- [ ] **Step 6: Update .env for production**

---

### Task 9: Cloudflare Tunnel

**Files:**
- Create: `cloudflared-config.yml`

- [ ] **Step 1: Authenticate cloudflared**
- [ ] **Step 2: Create tunnel**
- [ ] **Step 3: Route DNS**
- [ ] **Step 4: Create config yml**
- [ ] **Step 5: Run tunnel**
- [ ] **Step 6: Verify tunnel**

---

### Task 10: End-to-end test

- [ ] **Step 1: Start both services**
- [ ] **Step 2: Test in Alexa Simulator**
- [ ] **Step 3: Test with physical Echo Dot**
- [ ] **Step 4: Verify each voice command**

---

### Task 11: Auto-start scripts (optional)

**Files:**
- Create: `start-server.ps1`
- Create: `start-tunnel.ps1`

- [ ] **Step 1: Create start scripts**
- [ ] **Step 2: Install NSSM services (optional)**
