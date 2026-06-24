# Web Player - Mi Cancionero

Reproductor de musica independiente en el navegador, en el mismo backend pero con cola propia, sin tocar el skill de Alexa.

## Arquitectura

```
backend/
├── web_player.py            ← Router nuevo + WebQueueManager + DB propia
├── static/web-player/       ← HTML+CSS+JS (todo en uno)
├── main.py                  ← +1 import, +1 include_router, +2 rutas en UNPROTECTED_PATHS
├── music_service.py         ← Reusado sin cambios (init_ytmusic())
├── favorites_manager.py     ← Reusado sin cambios
├── auth.py                  ← Reusado sin cambios
└── data/web_queue.db        ← SQLite independiente
```

- `web_player.py` usa `init_ytmusic()` directamente (no modifica music_service.py)
- `web_queue.db` tiene dos tablas: `web_queue_items` (posicion, video_id, title, artist, thumbnail, duration) y `web_queue_state` (current_index, token)
- Cloudflared no se toca. Mismo contenedor, mismo puerto.

## Cambios minimos a archivos existentes

**main.py** (3 cambios, ~5 lineas):
1. Agregar `"/web-player/"` y `"/web-player/static/"` a UNPROTECTED_PATHS
2. `from web_player import web_router`
3. `app.include_router(web_router)`

**landing.html**: Agregar tarjeta "Web Player" con icono `fa-headphones` apuntando a `/web-player/`.

## API

| Metodo | Ruta | Descripcion |
|---|---|---|
| GET | `/web-player/api/search?q=...` | Busca canciones, devuelve hasta 5 resultados |
| GET | `/web-player/api/queue` | Cola completa + indice actual |
| POST | `/web-player/api/queue` | Agrega cancion al final. Body: `{video_id, title, artist, thumbnail}` |
| POST | `/web-player/api/queue/play/{index}` | Establece indice actual |
| POST | `/web-player/api/queue/next` | Avanza indice, devuelve cancion o null |
| POST | `/web-player/api/queue/prev` | Retrocede indice, devuelve cancion o null |
| POST | `/web-player/api/queue/reorder` | Reordenar. Body: `{from, to}` |
| DELETE | `/web-player/api/queue/{id}` | Elimina item de la cola |
| GET | `/web-player/api/favorites` | Favoritos (compartidos con el skill) |
| POST | `/web-player/api/favorites/toggle/{video_id}` | Agrega/quita favorito |

Todas protegidas por auth (cookie token), excepto la raiz `/web-player/` y `/web-player/static/`.

Audio servido por endpoint existente: `/proxy/audio/{video_id}` (range requests, M4A, sin cambios).

## Cola (WebQueueManager)

Clase propia en web_player.py. Persiste en `web_queue.db` via SQLite.

- **add_song()**: inserta al final. Si la cola estaba vacia, setea indice=0.
- **play(index)**: setea current_index. Devuelve la cancion.
- **next()**: index+1. Si no hay siguiente, devuelve null. Gatilla refill si remaining <= 5.
- **prev()**: index-1. Si es el primero, devuelve el mismo (no rebobina).
- **reorder(from, to)**: mueve en la lista y re-indexa posiciones en DB.
- **remove(id)**: elimina. Ajusta current_index si afecta.

**Refill automatico**: Cuando remaining <= 5, llama `get_watch_playlist(video_id, limit=20)` desde YT Music, filtra duplicados por `video_id`, agrega al final. Usa el `video_id` de la cancion actual (o la ultima reproducida).

La DB se guarda en cada mutacion (add, remove, reorder, play, next, prev).

## Frontend

Un unico archivo: `static/web-player/index.html` con HTML+CSS+JS inline.

**Layout:**

```
┌──────────────────────────────────────────────┐
│  🔍 Buscar canciones...           [Buscar]   │
├──────────────────────────────────────────────┤
│  Resultados (aparecen al buscar):            │
│  ┌────────────────────────────────────────┐  │
│  │ Portada | Artist - Title      [+ Cola] │  │
│  │ Portada | Artist - Title      [+ Cola] │  │
│  └────────────────────────────────────────┘  │
├──────────────────────────────────────────────┤
│  Cola (arrastrar para reordenar):            │
│  ┌────────────────────────────────────────┐  │
│  │ = 1. Artist - Title    ▶ │ ♥ │ ✕ │  │  │
│  │ = 2. Artist - Title      │ ♥ │ ✕ │  │  │
│  └────────────────────────────────────────┘  │
├─────────── Player bar (fijo abajo) ──────────┤
│  ⏮ ⏸ ⏭    0:42 / 3:15  ████████░░░░  ♥     │
│  Bohemian Rhapsody - Queen                   │
└──────────────────────────────────────────────┘
```

**Funcionalidades:**
- Busqueda: enter o click en boton. Resultados con portada + boton "+" para agregar a cola.
- Cola: click en item = reproducir desde ahi. Drag & drop para reordenar (HTML5 DnD, sin librerias). Icono de play en el item actual. Boton ♥ para favorito. Boton ✕ para quitar de cola.
- Player bar fija abajo: play/pause, prev/next, barra de progreso clickeable, tiempo transcurrido/total, ♥ favorito.
- Al terminar una cancion: auto-avanza a la siguiente. Si la cola termina, se detiene.
- Keyboard: espacio = play/pause (nativo del `<audio>`), no reinventar.
- Sin librerias externas. FontAwesome 6 para iconos (misma CDN que el PWA).
- Vanilla JS, sin framework.

**Estado local:** La cola se refresca via `GET /web-player/api/queue` al cargar y despues de cada mutacion. No hay estado duplicado en localStorage (la DB es la fuente de verdad).

## Auth

Mismo sistema que el PWA existente:
- `/web-player/` y `/web-player/static/` en UNPROTECTED_PATHS (carga el HTML sin auth)
- `/web-player/api/*` protegido por cookie `token`
- Si no hay token, el frontend redirige a `/app-music/login`

## Rendering de audio

- Elemento `<audio>` en el HTML, oculto o transparente.
- Fuente: `<source src="/proxy/audio/{video_id}" type="audio/mp4">`
- Eventos: timeupdate para progreso, ended para next, error para skip.
- Volumen: control nativo del browser o slider si es necesario.

## Consideraciones

- **Ancho de banda**: Cada reproduccion consume ~3MB del VPS. El cache `/app/data/cache` ayuda en reproducciones repetidas. Sin costo adicional de Cloudflare (Tunnel egress es gratis).
- **YT Music API**: `search()` y `get_watch_playlist()` sin auth. Si fallan, el refill simplemente no ocurre (la cola se acaba y para).
- **Errores de audio**: Si `/proxy/audio/` falla (yt-dlp timeout, YouTube bloquea), el frontend salta a la siguiente cancion automaticamente.
- **Duplicados**: `get_watch_playlist()` filtra por `video_id` antes de insertar. La cola no permite duplicados consecutivos (no agrega si el ultimo item tiene el mismo video_id).

## Archivos modificados vs creados

| Accion | Archivo | Cambio |
|---|---|---|
| Crear | `backend/web_player.py` | Router + WebQueueManager (240 lineas aprox) |
| Crear | `backend/static/web-player/index.html` | Frontend completo (400 lineas aprox) |
| Editar | `backend/main.py` | +5 lineas (import, router, UNPROTECTED) |
| Editar | `backend/static/landing.html` | +1 tarjeta web-player |

## Cookie path compartido

El login actual setea la cookie con `path=/app-music`, lo que impide que `/web-player/api/*` la reciba. Se cambia a `path=/` en el frontend de login (LOGIN_HTML en main.py) para que el token sea valido en todas las subaplicaciones. El middleware de auth ya usa `request.cookies.get("token")` sin validar path, asi que no requiere cambios.

Autores: al iniciar sesion desde cualquier app, la cookie se envia a todas.

## Auto-play al agregar primera cancion

Cuando la cola esta vacia y el usuario agrega una cancion (desde resultados de busqueda), el frontend inicia reproduccion inmediatamente. El servidor marca `current_index=0` al agregar el primer item, y el frontend responde creando el `<audio>` y llamando `.play()`.

## Refill: remaining contados desde current_index

El trigger "remaining <= 5" cuenta los items DESPUES del `current_index`. Si la cola tiene 20 items y current_index=10, hay 9 remaining. Si current_index=15 y quedan 4, se gatilla refill.

## Drag reorder sin soporte táctil

HTML5 DnD nativo no funciona bien en dispositivos tactiles. Para mantener minimalista, el reordenamiento es solo con mouse/raton (drag & drop). En dispositivos moviles, los botones ✕ y ▶ permiten gestionar la cola sin arrastrar.

Sin cambios en: `alexa_handler.py`, `queue_manager.py`, `offline_*`, `app.js`, `index.html` (PWA), `auth.py`, `favorites_manager.py`, `music_service.py`.
