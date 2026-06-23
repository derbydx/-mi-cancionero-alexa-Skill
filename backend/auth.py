import hashlib
import secrets
import logging
import time

logger = logging.getLogger(__name__)

_tokens: dict[str, float] = {}
_token_cleanup_interval = 300
_last_cleanup = 0.0


def init_auth(password: str):
    global _password_hash
    _password_hash = hashlib.sha256(password.encode()).hexdigest()
    logger.info("Auth initialized")


def verify_password(password: str) -> str | None:
    if hashlib.sha256(password.encode()).hexdigest() == _password_hash:
        token = secrets.token_urlsafe(32)
        _tokens[token] = time.time()
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
