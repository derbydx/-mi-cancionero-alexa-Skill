import hashlib
import secrets
import logging
import time
import os

import bcrypt

logger = logging.getLogger(__name__)

_tokens: dict[str, float] = {}
_token_cleanup_interval = 300
_last_cleanup = 0.0

# Recovery code
_recovery_code: str | None = None
_recovery_used: bool = False
RECOVERY_FILE = "/app/data/recovery_code.txt"

# ── Rate limiter ──────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self):
        self._attempts: dict[str, list[float]] = {}
        self._blocked: dict[str, float] = {}

    def check(self, ip: str) -> bool:
        now = time.time()
        self._blocked = {k: v for k, v in self._blocked.items() if now < v}
        if ip in self._blocked:
            remaining = int(self._blocked[ip] - now)
            logger.warning("Rate limit hit for %s, blocked %ds remaining", ip, remaining)
            return False
        attempts = [t for t in self._attempts.get(ip, []) if now - t < 900]
        count = len(attempts)
        if count >= 5:
            self._blocked[ip] = now + 1800
            logger.warning("Rate limit: %s blocked 30min (%d attempts)", ip, count)
            return False
        elif count >= 3:
            time.sleep(5)
        elif count >= 1:
            time.sleep(1)
        return True

    def record_failure(self, ip: str):
        now = time.time()
        self._attempts.setdefault(ip, [])
        self._attempts[ip] = [t for t in self._attempts[ip] if now - t < 900]
        self._attempts[ip].append(now)

    def record_success(self, ip: str):
        self._attempts.pop(ip, None)
        self._blocked.pop(ip, None)

rate_limiter = RateLimiter()

# ── Auth core ─────────────────────────────────────────────────────────────

def init_auth(password: str):
    global _password_hash, _recovery_code, _recovery_used
    _password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    _recovery_code = secrets.token_urlsafe(32)
    _recovery_used = False

    logger.warning("=" * 60)
    logger.warning("RECOVERY CODE (one-time use): %s", _recovery_code)
    logger.warning("Save this code. If you forget your password, use it to log in.")
    logger.warning("=" * 60)

    try:
        os.makedirs(os.path.dirname(RECOVERY_FILE), exist_ok=True)
        with open(RECOVERY_FILE, "w") as f:
            f.write(f"Recovery code (one-time use): {_recovery_code}\n")
            f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("\nTo use: go to /app-music/login and enter this code as the password.\n")
            f.write("The code works only once. After using it, restart the backend to generate a new one.\n")
        logger.info("Recovery code saved to %s", RECOVERY_FILE)
    except Exception as e:
        logger.error("Failed to save recovery code: %s", e)

    logger.info("Auth initialized")


def verify_password(password: str, ip: str | None = None) -> str | None:
    global _recovery_code, _recovery_used

    if _recovery_code and not _recovery_used and password == _recovery_code:
        _recovery_used = True
        _recovery_code = None
        logger.warning("Recovery code used from IP %s", ip or "unknown")
        _tokens.clear()
        token = secrets.token_urlsafe(32)
        _tokens[token] = time.time()
        if ip:
            rate_limiter.record_success(ip)
        return token

    if bcrypt.checkpw(password.encode(), _password_hash.encode()):
        token = secrets.token_urlsafe(32)
        _tokens[token] = time.time()
        if ip:
            rate_limiter.record_success(ip)
        return token

    return None


def check_token(token: str | None) -> bool:
    if not token:
        return False
    if token in _tokens:
        _cleanup()
        return True
    return False


def _cleanup():
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _token_cleanup_interval:
        return
    _last_cleanup = now
    expired = [t for t, ts in _tokens.items() if now - ts > 86400]
    for t in expired:
        del _tokens[t]
    if expired:
        logger.debug("Cleaned %d expired tokens", len(expired))
