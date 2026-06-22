import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

# Ensure backend/ directory is on the path for intra-package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from ask_sdk_webservice_support.verifier import (
    RequestVerifier,
    TimestampVerifier,
    VerificationException,
)

from config import settings
from alexa_handler import handle_alexa_request
from queue_manager import queue_manager
from audio_proxy import stream_audio
from history_manager import init_db, get_history
from music_service import init_ytmusic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Alexa Music Streaming")

_verifiers = [RequestVerifier(), TimestampVerifier()]


@app.on_event("startup")
async def startup():
    init_db()
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


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    path = os.path.join(os.path.dirname(__file__), "static", "privacy.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/terms", response_class=HTMLResponse)
async def terms():
    path = os.path.join(os.path.dirname(__file__), "static", "terms.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/queue/json")
async def queue_json():
    return queue_manager.get_queue()


@app.get("/history", response_class=HTMLResponse)
async def history(limit: int = 500):
    items = get_history(limit)
    rows = ""
    for i, s in enumerate(items):
        title = s.get("title", "?")
        artist = s.get("artist", "?")
        played = s.get("played", 0)
        badge = '<span class="played">Reproducida</span>' if played else '<span class="queued">En cola</span>'
        played_at = (s.get("played_at") or "")[:19].replace("T", " ") if s.get("played_at") else "-"
        queued_at = (s.get("queued_at") or "")[:19].replace("T", " ") if s.get("queued_at") else "-"
        rows += f"""<tr>
<td class="i">{i + 1}</td>
<td>{title}</td>
<td>{artist}</td>
<td>{badge}</td>
<td class="ts">{queued_at}</td>
<td class="ts">{played_at}</td>
</tr>"""
    html = f"""<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historial - Mi Cancionero</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 30px auto; padding: 0 20px; color: #333; }}
  h1 {{ color: #1a1a2e; }}
  .meta {{ color: #666; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; position: sticky; top: 0; }}
  td.i {{ color: #999; width: 40px; }}
  td.ts {{ font-size: 13px; color: #666; white-space: nowrap; }}
  .played {{ background: #d4edda; color: #155724; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
  .queued {{ background: #fff3cd; color: #856404; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
</style>
</head>
<body>
<h1>Historial</h1>
<p class="meta">{len(items)} canciones registradas</p>
<table>
<thead><tr><th>#</th><th>Titulo</th><th>Artista</th><th>Estado</th><th>Encolada</th><th>Reproducida</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/queue", response_class=HTMLResponse)
async def queue():
    q = queue_manager.get_queue()
    rows = ""
    for i, s in enumerate(q["queue"]):
        vid = s["video_id"]
        title = s.get("title", "?")
        artist = s.get("artist", "?")
        url = f"{settings.proxy_base_url}/proxy/audio/{vid}"
        cls = " current" if i == q["current_index"] else ""
        rows += f"""<tr class="{cls}">
<td class="i">{i + 1}</td>
<td><a href="{url}" target="_blank">{title}</a></td>
<td>{artist}</td>
<td><code>{vid}</code></td>
</tr>"""
    loop_badge = ' <span class="loop">🔁 Bucle activado</span>' if q["looping"] else ""
    html = f"""<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cola - Mi Cancionero</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 30px auto; padding: 0 20px; color: #333; }}
  h1 {{ color: #1a1a2e; }}
  .meta {{ color: #666; margin-bottom: 20px; }}
  .loop {{ background: #fff3cd; padding: 3px 10px; border-radius: 4px; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; position: sticky; top: 0; }}
  tr.current {{ background: #e3f2fd; font-weight: bold; }}
  td.i {{ color: #999; width: 40px; }}
  code {{ font-size: 12px; color: #999; }}
  a {{ color: #1a73e8; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>Cola de reproduccion{loop_badge}</h1>
<p class="meta">{q["total"]} canciones · Actual: {q["current_index"] + 1} de {q["total"]}</p>
<table>
<thead><tr><th>#</th><th>Titulo</th><th>Artista</th><th>ID</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/health")
async def health():
    return {"status": "ok"}
