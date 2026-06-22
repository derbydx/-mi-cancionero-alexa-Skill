# Mi Cancionero - Alexa Music Skill

Reproduce musica de YouTube Music en tu Echo Dot usando un skill personalizado de Alexa.

## Arquitectura

```
Echo Dot -> Alexa Skill (Mi Cancionero) -> Cloudflare Tunnel -> FastAPI (Docker, localhost:8000)
                                                                 |- ytmusicapi (busqueda)
                                                                 |- yt-dlp (streaming AAC directo)
                                                                 |- headers_auth.json (auth Google)
```

## Requisitos

- Docker Desktop
- Python 3.14+ (solo para generar headers_auth.json)
- Cuenta de desarrollador Alexa
- Cloudflare Tunnel (cloudflared)
- Dominio propio (ej: mimusica.xyz)

## Instalacion (produccion con Docker)

### 1. Clonar

```bash
git clone <url-del-repo>
cd Alexa-Skill-2
```

### 2. Configurar credenciales

Sigue las instrucciones en `PRIVATE_CONFIG.md` (archivo personal, no incluido en el repo).
Necesitas:

- `.env` con `PROXY_BASE_URL`, `SKIP_SIGNATURE_VERIFICATION=true`
- `headers_auth.json` con cookies de YouTube Music
- Credenciales de Cloudflare Tunnel en `~\.cloudflared\`

### 3. Construir y ejecutar

```bash
docker compose build
docker compose up -d
```

Verificar:

```bash
curl http://localhost:8000/health
```

### 4. Exponer con Cloudflare Tunnel

El `docker-compose.yml` incluye cloudflared configurado para compartir la red con el backend.
El tunnel debe estar creado previamente:

```bash
cloudflared tunnel login
cloudflared tunnel create f82799a9-d722-40c5-9b86-331879e11005
```

### 5. Crear el Skill en Alexa

- Skill tipo "Custom", modelo de interaccion en espanol (MX)
- Nombre de invocacion: "mi cancionero"
- Endpoint: `https://mimusica.xyz/alexa`
- Activar **Audio Player** en Build > Interfaces
- Subir el modelo de interaccion

## Uso

En tu Echo Dot:

- "Alexa, abre mi cancionero"
- "pon musica de bad bunny"
- "siguiente cancion", "pausa", "reanudar"

## Desarrollo local

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Requiere Python 3.14+, entorno virtual, y `pip install -r backend/requirements.txt`.

## Endpoints utiles

| Endpoint | Descripcion |
|----------|-------------|
| `GET /health` | Estado del servidor |
| `GET /queue` | Cola actual de reproduccion (formato HTML) |
| `GET /privacy` | Politica de privacidad |
| `GET /terms` | Terminos de uso |
| `GET /proxy/audio/{video_id}` | Audio directo AAC (usado por el skill) |
| `POST /alexa` | Endpoint del skill de Alexa |

## Recuperacion ante desastres

Si esta PC falla, consulta `RECOVERY_PLAN.md` para instrucciones paso a paso
de como restaurar el backend en otro equipo.

## Archivos sensibles (NO subir a GitHub)

- `.env` - configuracion del servidor
- `headers_auth.json` - cookies de Google autenticadas
- `cloudflared-config.yml` - config local del tunnel
- `PRIVATE_CONFIG.md` - copia de seguridad de tus credenciales
- `.venv/` - entorno virtual

## Licencia

MIT
