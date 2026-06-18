# Task 1: Project scaffold and configuration

This is the first task of the Alexa Music Streaming project. Creates the foundation files.

## Files to create

- `backend/__init__.py` — empty package marker
- `backend/config.py` — Settings dataclass from .env
- `backend/requirements.txt` — pinned Python dependencies
- `.gitignore` — standard ignores
- `.env` — environment variables for local dev

## Config content

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

## Requirements

```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
ytmusicapi>=1.7.0
yt-dlp>=2024.4.0
httpx>=0.27.0
python-dotenv>=1.0.0
ask-sdk-webservice-support>=1.20.0
```

## .gitignore

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

## .env

```
PROXY_BASE_URL=https://tudominio.com
HOST=0.0.0.0
PORT=8000
SKIP_SIGNATURE_VERIFICATION=true
```

## Commit

After creating all files, stage and commit with message: `feat: project scaffold with config and dependencies`
