# Plan de Recuperacion - Mi Cancionero

Como restaurar el backend de Mi Cancionero en una PC nueva desde cero.

## Requisitos previos

- Git
- Docker Desktop (con WSL2 o Hyper-V en Windows)
- Python 3.14+
- Node.js (para yt-dlp, aunque Docker lo incluye)
- Cuenta en Cloudflare con el dominio configurado
- **`PRIVATE_CONFIG.md`** (archivo personal que NO esta en el repo, guardalo en un gestor de contraseñas)

## Paso 1: Clonar el repositorio

```bash
git clone <url-del-repo>
cd Alexa-Skill-2
```

## Paso 2: Restaurar configuracion privada

Sigue las instrucciones en `PRIVATE_CONFIG.md` (archivo que debes tener guardado aparte) para:

1. Crear `.env` en la raiz del proyecto
2. Generar o copiar `headers_auth.json`
3. Copiar el archivo de credenciales de Cloudflare a `~\.cloudflared\`

## Paso 3: Autenticar YouTube Music

Si no tienes el `headers_auth.json` guardado, genera uno nuevo:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install ytmusicapi
python -c "from ytmusicapi import setup; setup(filepath='headers_auth.json')"
```

Sigue las instrucciones en pantalla para pegar los headers desde Chrome DevTools.

## Paso 4: Verificar Cloudflare Tunnel

Asegurate de que el tunnel existe y las credenciales estan en su lugar:

```bash
cloudflared tunnel list
```

Si el tunnel no aparece, crealo:

```bash
cloudflared tunnel login
cloudflared tunnel create f82799a9-d722-40c5-9b86-331879e11005
```

## Paso 5: Construir y ejecutar con Docker

```bash
docker compose build
docker compose up -d
```

Verifica que ambos contenedores esten funcionando:

```bash
docker compose ps
```

## Paso 6: Probar el endpoint

```bash
curl http://localhost:8000/health
curl https://mimusica.xyz/health
```

## Paso 7: Configurar inicio automatico (opcional)

1. Abre Docker Desktop -> Settings -> General -> "Start Docker Desktop when you sign in to your computer"
2. Opcional: crea un acceso directo a `docker compose up -d` en la carpeta de inicio de Windows.

## Solucion de problemas

### El tunnel responde 502

```bash
docker compose restart
```

### Error "headers_auth.json not found"

Verifica que el archivo existe en la raiz del proyecto y que `.env` tiene la ruta correcta o usa la variable `YT_MUSIC_AUTH_FILE`.

### Error de autenticacion de YouTube

Regenera `headers_auth.json` con el comando del Paso 3. Las cookies de Google expiran periodicamente.

### Docker no encuentra el archivo de credenciales

Verifica que la ruta en `docker-compose.yml` (linea 19) apunte al archivo JSON correcto de Cloudflare.
