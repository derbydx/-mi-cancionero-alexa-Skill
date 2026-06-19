# Mi Cancionero - Alexa Music Skill

Reproduce música de YouTube Music en tu Echo Dot usando un skill personalizado de Alexa.

## Arquitectura

```
Echo Dot → Alexa Skill (Mi Cancionero) → Cloudflare Tunnel → FastAPI (localhost:8000)
                                                                ├── ytmusicapi (búsqueda)
                                                                ├── yt-dlp + ffmpeg (streaming)
                                                                └── headers_auth.json (auth Google)
```

## Requisitos

- Python 3.14+
- Node.js (para yt-dlp)
- FFmpeg (en PATH)
- Cuenta de desarrollador Alexa (https://developer.amazon.com/alexa)
- Cloudflare Tunnel (cloudflared)
- Dominio propio (ej: mimusica.xyz)

## Instalación

### 1. Clonar y entorno virtual

```bash
git clone https://github.com/tu-usuario/mi-cancionero-alexa-Skill.git
cd mi-cancionero-alexa-Skill
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows
pip install -r backend\requirements.txt
```

### 2. Autenticación YouTube Music

```bash
cd D:\Alexa-Skill-2
.\.venv\Scripts\Activate.ps1
python -c "from ytmusicapi import setup; setup(filepath='headers_auth.json')"
```

Seguí las instrucciones para pegar los headers de music.youtube.com (incluye cookie, x-goog-authuser, authorization).

### 3. Configurar .env

```bash
cp .env.example .env
```

Editar `.env` con tu dominio real y configuracion.

### 4. Exponer con Cloudflare Tunnel

Configurar cloudflared para apuntar tu dominio a localhost:8000.

### 5. Crear el Skill en Alexa

- Skill tipo "Custom", modelo de interacción en español (MX)
- Nombre de invocación: "mi cancionero"
- Endpoint: `https://tu-dominio.xyz/alexa`
- Activar **Audio Player** en Build > Interfaces
- Subir el modelo de interacción

## Uso

En tu Echo Dot:

- "Alexa, abre mi cancionero"
- "pon musica de bad bunny"
- "siguiente cancion", "pausa", "reanudar"

## Desarrollo

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

El servidor se recarga automáticamente al cambiar código.

## Archivos sensibles (NO subir a GitHub)

- `.env` - configuración del servidor
- `headers_auth.json` - cookies de Google autenticadas
- `cloudflared-config.yml` - ID del tunnel
- `.venv/` - entorno virtual

## Licencia

MIT
