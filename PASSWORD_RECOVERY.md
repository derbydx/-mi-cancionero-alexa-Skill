# Recuperacion de acceso - Mi Cancionero

Si no puedes iniciar sesion en `https://mimusica.xyz/app-music/`, usa uno de estos metodos en orden.

---

## Metodo 1: Recovery code (recomendado)

Cada vez que el backend se inicia, genera un recovery code de un solo uso. Se guarda en dos lugares:

**A) Archivo persistente en el servidor:**

```powershell
cat D:\Alexa-Skill-2\data\recovery_code.txt
```

Veras algo como:

```
Recovery code (one-time use): xxxxxx
```

Copia ese codigo, ve a la pantalla de login y pegarlo como contrasena. Funciona una sola vez.

**B) Logs de Docker (si el archivo no existe):**

```powershell
docker compose logs backend | Select-String "RECOVERY CODE"
```

Mismo proceso: copia el codigo, usalo como contrasena en el login.

---

## Metodo 2: Generar un nuevo recovery code

Si el recovery code anterior ya se uso o no aparece en los logs:

```powershell
docker compose up -d --build backend
docker compose up -d cloudflared
docker compose logs backend | Select-String "RECOVERY CODE"
```

El backend se reinicia y genera un recovery code nuevo.

---

## Metodo 3: Cambiar la contrasena manualmente

Si los metodos anteriores no funcionan:

1. Abre el archivo `.env` en el servidor:

```powershell
notepad D:\Alexa-Skill-2\.env
```

2. Cambia la linea `APP_PASSWORD`:

```
APP_PASSWORD=TuNuevaContrasenaAqui
```

3. Reconstruye y reinicia el backend:

```powershell
docker compose up -d --build backend
docker compose up -d cloudflared
```

4. Inicia sesion con `TuNuevaContrasenaAqui`.

---

## Como funciona el rate limiting

Para evitar fuerza bruta, el sistema bloquea temporalmente por IP:

| Intentos fallidos | Consecuencia |
|---|---|
| 1-2 | 1 segundo de espera |
| 3-4 | 5 segundos de espera |
| 5+ en 15 minutos | IP bloqueada 30 minutos |

Si ves error `429 Too Many Requests`, espera 30 minutos o reinicia el backend.

---

## Notas importantes

- El recovery code es de **un solo uso**. Una vez usado, se invalida.
- Al usar el recovery code, se cierran todas las sesiones activas (tokens anteriores invalidados).
- Si el backend se reinicia, se genera un recovery code **nuevo** y el anterior deja de funcionar (aunque el archivo en disco quede desactualizado).
- No hay forma de recuperar acceso sin acceso fisico o SSH al servidor.
