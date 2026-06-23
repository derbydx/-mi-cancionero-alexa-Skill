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
    app_password: str = field(default_factory=lambda: os.getenv("APP_PASSWORD", ""))

settings = Settings()
