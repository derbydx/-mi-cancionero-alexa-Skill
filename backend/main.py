import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

# Ensure backend/ directory is on the path for intra-package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from ask_sdk_webservice_support.verifier import (
    RequestVerifier,
    TimestampVerifier,
    VerificationException,
)

from config import settings
from alexa_handler import handle_alexa_request
from queue_manager import queue_manager
from audio_proxy import stream_audio, _get_duration
from history_manager import init_db, get_history_page, get_all_history, get_total_count, find_duplicates, clean_duplicates
from favorites_manager import init_favorites_db, get_favorites, add_favorite, remove_favorite, is_favorite
from music_service import init_ytmusic, search_song
from auth import init_auth, verify_password, check_token
from queue_db import init_queue_db
from offline_manager import (
    init_offline_db,
    create_offline_task,
    get_pending_tasks,
    update_task_status,
    update_task_progress,
    get_statuses_for_ids,
    list_completed,
    delete_offline,
    get_task_status,
    list_all_tasks,
    retry_task,
    ensure_download_tasks,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Alexa Music Streaming")

_verifiers = [RequestVerifier(), TimestampVerifier()]

# ── Auth middleware ─────────────────────────────────────────────────────────

UNPROTECTED_PATHS = [
    "/alexa", "/proxy/audio/", "/health", "/api/login",
    "/static/", "/privacy", "/terms", "/login",
    "/api/offline/tasks/",
]


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if not settings.app_password:
        return await call_next(request)

    for prefix in UNPROTECTED_PATHS:
        if path.startswith(prefix):
            return await call_next(request)

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("token")

    if check_token(token):
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    return RedirectResponse(url="/login")


@app.on_event("startup")
async def startup():
    init_db()
    init_favorites_db()
    init_queue_db()
    init_offline_db()
    if settings.app_password:
        init_auth(settings.app_password)
        logger.info("Auth initialized with password from env")
    else:
        logger.warning("APP_PASSWORD not set - web interface will have no auth")
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
        req_type = body.get('request', {}).get('type', '')
        logger.info(f"Alexa request type: {req_type}")
        if req_type == "AudioPlayer.PlaybackStarted":
            ctx = body.get('context', {})
            sys = ctx.get('System', {})
            device = sys.get('device', {})
            supported = device.get('supportedInterfaces', {})
            logger.info(f"Device supportedInterfaces: {list(supported.keys())}")
        response = await handle_alexa_request(body)
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


@app.head("/proxy/audio/{video_id}")
async def proxy_audio_head(video_id: str):
    duration = await _get_duration(video_id)
    headers = {}
    if duration:
        headers["Content-Duration"] = str(int(duration))
    return Response(headers=headers)


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


# ── Static files & SPA ──────────────────────────────────────────────────────

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    path = os.path.join(static_dir, "index.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Mi Cancionero</h1><p>PWA no encontrada.</p>")


# ── Auth ─────────────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mi Cancionero - Acceso</title>
<link rel="stylesheet" href="/static/styles.css?v=2">
<style>
  .login-page { display:flex; align-items:center; justify-content:center; height:100%; padding:20px; }
  .login-box { background:var(--surface); padding:32px; border-radius:var(--radius); width:100%; max-width:360px; text-align:center; }
  .login-box h1 { color:var(--primary); font-size:24px; margin-bottom:24px; }
  .login-box input { width:100%; padding:12px 16px; border:1px solid var(--border); border-radius:var(--radius-sm); background:var(--card); color:var(--text); font-size:16px; outline:none; margin-bottom:16px; }
  .login-box input:focus { border-color:var(--primary); }
  .login-box button { width:100%; padding:12px; background:var(--primary); color:#000; border:none; border-radius:var(--radius-sm); font-weight:600; font-size:16px; cursor:pointer; }
  .login-box button:hover { background:var(--primary-dim); }
  .login-box .error { color:var(--danger); font-size:14px; margin-top:12px; display:none; }
</style>
</head>
<body>
<div class="login-page">
  <div class="login-box">
    <h1>Mi Cancionero</h1>
    <input type="password" id="pass" placeholder="Contrasena" autofocus
           onkeydown="if(event.key==='Enter') login()">
    <button onclick="login()">Entrar</button>
    <div class="error" id="error">Contrasena incorrecta</div>
  </div>
</div>
<script>
async function login() {
  const pass = document.getElementById('pass');
  const err = document.getElementById('error');
  err.style.display = 'none';
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pass.value}),
    });
    const data = await res.json();
    if (data.token) {
      document.cookie = 'token=' + data.token + '; path=/; max-age=86400; SameSite=Lax';
      window.location.href = '/';
    } else {
      err.textContent = 'Contrasena incorrecta';
      err.style.display = 'block';
    }
  } catch(e) {
    err.textContent = 'Error de conexion';
    err.style.display = 'block';
  }
}
</script>
</body>
</html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(content=LOGIN_HTML)


@app.post("/api/login")
async def api_login(request: Request):
    try:
        body = await request.json()
        password = body.get("password", "")
        token = verify_password(password)
        if token:
            return {"token": token}
        return JSONResponse(status_code=401, content={"error": "Invalid password"})
    except Exception as e:
        logger.error("Login error: %s", e)
        return JSONResponse(status_code=400, content={"error": str(e)})


# ── API: Search ──────────────────────────────────────────────────────────────

@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1)):
    try:
        from music_service import init_ytmusic
        yt = init_ytmusic()
        raw = yt.search(q, filter="songs", limit=10)
        results = []
        for r in raw:
            results.append({
                "video_id": r.get("videoId", ""),
                "title": r.get("title", ""),
                "artist": ", ".join(a.get("name", "") for a in r.get("artists", [])),
                "thumbnail": r.get("thumbnails", [{}])[-1].get("url", ""),
            })
        return results
    except Exception as e:
        logger.error("Search error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── API: Queue ───────────────────────────────────────────────────────────────

@app.get("/api/queue")
async def api_queue():
    return queue_manager.get_queue()


@app.post("/api/queue")
async def api_enqueue(request: Request):
    try:
        body = await request.json()
        song = {
            "video_id": body["video_id"],
            "title": body.get("title", ""),
            "artist": body.get("artist", ""),
            "thumbnail": body.get("thumbnail", ""),
        }
        idx = queue_manager.add_song(song)
        ensure_download_tasks(queue_manager.get_queue()["queue"])
        return {"index": idx, "song": song}
    except Exception as e:
        logger.error("Enqueue error: %s", e)
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/queue/clear")
async def api_clear_queue():
    queue_manager.clear()
    return {"ok": True}


# ── API: Favorites ──────────────────────────────────────────────────────────

@app.get("/api/favorites")
async def api_favorites():
    return get_favorites()


@app.post("/api/favorites")
async def api_add_favorite(request: Request):
    try:
        body = await request.json()
        ok = add_favorite(
            body["video_id"],
            body.get("title", ""),
            body.get("artist", ""),
            body.get("thumbnail", ""),
        )
        return {"ok": ok}
    except Exception as e:
        logger.error("Add favorite error: %s", e)
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.delete("/api/favorites/{video_id}")
async def api_remove_favorite(video_id: str):
    ok = remove_favorite(video_id)
    return {"ok": ok}


@app.get("/api/favorites/check/{video_id}")
async def api_check_favorite(video_id: str):
    return {"favorite": is_favorite(video_id)}


# ── API: Offline / Download tasks ────────────────────────────────────────────


@app.get("/api/offline/tasks/pending")
async def api_offline_pending():
    return get_pending_tasks(limit=5)


@app.post("/api/offline/tasks/{task_id}/status")
async def api_offline_update_status(task_id: int, request: Request):
    try:
        body = await request.json()
        update_task_status(
            task_id,
            body.get("status", "pending"),
            filepath=body.get("filepath", ""),
            error=body.get("error", ""),
            actual_title=body.get("actual_title", ""),
            actual_artist=body.get("actual_artist", ""),
        )
        return {"ok": True}
    except Exception as e:
        logger.error("Offline status update error: %s", e)
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/offline/tasks/{task_id}/progress")
async def api_offline_progress(task_id: int, request: Request):
    try:
        body = await request.json()
        update_task_progress(task_id, float(body.get("progress", 0)))
        return {"ok": True}
    except Exception as e:
        logger.error("Offline progress update error: %s", e)
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/api/offline")
async def api_offline_list():
    return list_completed()


@app.get("/api/offline/check/{video_id}")
async def api_offline_check(video_id: str):
    status = get_task_status(video_id)
    if status:
        return {"video_id": video_id, "status": status["status"], "filepath": status.get("filepath", "")}
    return {"video_id": video_id, "status": "none"}


@app.get("/api/offline/statuses")
async def api_offline_statuses(ids: str = Query("")):
    if not ids.strip():
        return {}
    video_ids = [v.strip() for v in ids.split(",") if v.strip()]
    return get_statuses_for_ids(video_ids)


@app.delete("/api/offline/{video_id}")
async def api_offline_delete(video_id: str):
    removed = delete_offline(video_id)
    return {"ok": True, "file_removed": removed}


@app.get("/api/offline/tasks")
async def api_offline_all_tasks():
    return list_all_tasks()


@app.post("/api/offline/{video_id}/retry")
async def api_offline_retry(video_id: str):
    ok = retry_task(video_id)
    return {"ok": ok}


@app.post("/api/offline/sync")
async def api_offline_sync():
    q = queue_manager.get_queue()
    ensure_download_tasks(q["queue"])
    return {"ok": True, "total": len(q["queue"])}


# ── API: History ─────────────────────────────────────────────────────────────

@app.get("/api/history")
async def api_history(page: int = 1, page_size: int = 200):
    return get_history_page(page, page_size)


@app.get("/health")
async def health():
    return {"status": "ok"}
