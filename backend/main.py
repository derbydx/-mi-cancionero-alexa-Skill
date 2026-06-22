import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

# Ensure backend/ directory is on the path for intra-package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from ask_sdk_webservice_support.verifier import (
    RequestVerifier,
    TimestampVerifier,
    VerificationException,
)

from config import settings
from alexa_handler import handle_alexa_request
from queue_manager import queue_manager
from audio_proxy import stream_audio
from history_manager import init_db, get_history_page, get_all_history, get_total_count, find_duplicates, clean_duplicates
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


@app.get("/history/duplicates")
async def history_duplicates():
    return find_duplicates()


@app.post("/history/clean-duplicates")
async def history_clean_duplicates():
    removed = clean_duplicates()
    return {"removed": removed}


@app.get("/history/csv")
async def history_csv():
    items = get_all_history()
    lines = ["id,video_id,title,artist,played,queued_at,played_at"]
    for s in items:
        title = s.get("title", "").replace('"', '""')
        artist = s.get("artist", "").replace('"', '""')
        lines.append(f'{s["id"]},{s["video_id"]},"{title}","{artist}",{s["played"]},{s.get("queued_at","")},{s.get("played_at","")}')
    return PlainTextResponse("\n".join(lines), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=historial.csv"})


@app.get("/history", response_class=HTMLResponse)
async def history(page: int = 1, page_size: int = 200):
    data = get_history_page(page, page_size)

    start = (page - 1) * page_size + 1
    end = min(start + len(data["items"]) - 1, data["total"])

    rows = ""
    for s in data["items"]:
        title = s.get("title", "?")
        artist = s.get("artist", "?")
        played = s.get("played", 0)
        badge = '<span class="played">Reproducida</span>' if played else '<span class="queued">En cola</span>'
        played_at = (s.get("played_at") or "")[:19].replace("T", " ") if s.get("played_at") else "-"
        queued_at = (s.get("queued_at") or "")[:19].replace("T", " ") if s.get("queued_at") else "-"
        rows += f"""<tr>
<td class="i">{s["id"]}</td>
<td>{title}</td>
<td>{artist}</td>
<td>{badge}</td>
<td class="ts">{queued_at}</td>
<td class="ts">{played_at}</td>
</tr>"""

    pagination = _build_pagination(page, data["total_pages"], data["total"])

    html = f"""<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historial - Mi Cancionero</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 20px; color: #333; }}
  h1 {{ color: #1a1a2e; display: inline; }}
  .header {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }}
  .counter {{ color: #666; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; position: sticky; top: 0; }}
  td.i {{ color: #999; width: 50px; font-size: 13px; }}
  td.ts {{ font-size: 13px; color: #666; white-space: nowrap; }}
  .played {{ background: #d4edda; color: #155724; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
  .queued {{ background: #fff3cd; color: #856404; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
  .btn {{ padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }}
  .btn-warn {{ background: #dc3545; color: #fff; }}
  .btn-warn:hover {{ background: #c82333; }}
  .btn-outline {{ background: #fff; color: #333; border: 1px solid #ccc; }}
  .btn-outline:hover {{ background: #f0f0f0; }}
  .pagination {{ display: flex; justify-content: center; align-items: center; gap: 8px; margin: 20px 0; flex-wrap: wrap; }}
  .pagination a {{ padding: 6px 12px; border: 1px solid #ddd; border-radius: 4px; color: #1a73e8; text-decoration: none; font-size: 14px; }}
  .pagination a:hover {{ background: #e8f0fe; }}
  .pagination a.active {{ background: #1a73e8; color: #fff; border-color: #1a73e8; }}
  .pagination a.disabled {{ color: #ccc; pointer-events: none; }}
  .toolbar {{ display: flex; gap: 8px; align-items: center; }}
  #dup-result {{ margin: 10px 0; padding: 10px 15px; border-radius: 4px; display: none; }}
  #dup-result.show {{ display: block; }}
  #dup-result.info {{ background: #e8f0fe; border: 1px solid #1a73e8; }}
  #dup-result.warn {{ background: #f8d7da; border: 1px solid #dc3545; }}
  .dup-item {{ padding: 4px 0; font-size: 14px; }}
</style>
</head>
<body>
<div class="header">
  <h1>Historial</h1>
  <div class="toolbar">
    <button class="btn btn-outline" onclick="findDups()">Encontrar duplicados</button>
    <button class="btn btn-warn" onclick="cleanDups()">Limpiar duplicados</button>
    <a href="/history/csv" class="btn btn-outline" style="text-decoration:none;">Exportar CSV</a>
  </div>
</div>
<p class="counter">{start}–{end} de {data["total"]} canciones</p>
<div id="dup-result"></div>
<table>
<thead><tr><th>#</th><th>Titulo</th><th>Artista</th><th>Estado</th><th>Encolada</th><th>Reproducida</th></tr></thead>
<tbody>{rows}</tbody>
</table>
{pagination}
<script>
async function findDups() {{
  const r = document.getElementById("dup-result");
  r.className = "show info";
  r.innerHTML = "Buscando duplicados...";
  try {{
    const res = await fetch("/history/duplicates");
    const dups = await res.json();
    if (dups.length === 0) {{
      r.className = "show info";
      r.innerHTML = "No hay canciones duplicadas.";
      return;
    }}
    let html = `<b>${{dups.length}} canciones duplicadas encontradas:</b><br>`;
    dups.slice(0, 20).forEach(d => {{
      html += `<div class="dup-item">${{d.title}} - ${{d.artist}} <span style="color:#999;font-size:12px;">(${{d.count}} veces, ID ${{d.video_id}})</span></div>`;
    }});
    if (dups.length > 20) html += `<div class="dup-item" style="color:#999;">... y ${{dups.length - 20}} mas</div>`;
    r.className = "show warn";
    r.innerHTML = html;
  }} catch(e) {{
    r.className = "show warn";
    r.innerHTML = "Error al buscar duplicados.";
  }}
}}
async function cleanDups() {{
  if (!confirm("Eliminar todas las canciones duplicadas? Se conservara la primera ocurrencia de cada una.")) return;
  const r = document.getElementById("dup-result");
  r.className = "show info";
  r.innerHTML = "Limpiando duplicados...";
  try {{
    const res = await fetch("/history/clean-duplicates", {{ method: "POST" }});
    const result = await res.json();
    r.className = "show info";
    r.innerHTML = `Se eliminaron ${{result.removed}} entradas duplicadas. Recargando...`;
    setTimeout(() => location.reload(), 1500);
  }} catch(e) {{
    r.className = "show warn";
    r.innerHTML = "Error al limpiar duplicados.";
  }}
}}
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


def _build_pagination(page: int, total_pages: int, total: int) -> str:
    if total_pages <= 1:
        return ""
    parts = []
    prev_class = "disabled" if page <= 1 else ""
    parts.append(f'<a href="?page={page - 1}" class="{prev_class}">Anterior</a>')

    start_p = max(1, page - 2)
    end_p = min(total_pages, page + 2)
    for p in range(start_p, end_p + 1):
        cls = "active" if p == page else ""
        parts.append(f'<a href="?page={p}" class="{cls}">{p}</a>')

    next_class = "disabled" if page >= total_pages else ""
    parts.append(f'<a href="?page={page + 1}" class="{next_class}">Siguiente</a>')

    return f'<div class="pagination">{"".join(parts)}</div>'


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
