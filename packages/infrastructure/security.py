import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from cryptography.fernet import Fernet
from packages.domain.errors import DomainError


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def fingerprint(value) -> str:
    return digest(canonical(value))


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise DomainError("PASSWORD_LENGTH", 422)
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.b64encode(salt + key).decode()


def verify_password(password: str, encoded: str) -> bool:
    if not 1 <= len(password) <= 128:
        return False
    try:
        raw = base64.b64decode(encoded, validate=True)
        key = hashlib.scrypt(password.encode(), salt=raw[:16], n=16384, r=8, p=1)
        return hmac.compare_digest(key, raw[16:])
    except (ValueError, TypeError):
        return False


class Cipher:
    def __init__(self, key: str):
        self.fernet = Fernet(key.encode())

    def encrypt(self, value) -> str:
        return self.fernet.encrypt(canonical(value).encode()).decode()

    def decrypt(self, value: str):
        return json.loads(self.fernet.decrypt(value.encode()))


class RateLimiter:
    """Memory is for single-process demo/tests; Redis errors fail closed."""
    def __init__(self, settings):
        self.counts = {}
        self.lock = threading.Lock()
        self.client = None
        if settings.rate_limit_backend == "redis":
            import redis
            self.client = redis.Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)

    def hit(self, identity: str, limit: int, window: int = 60):
        bucket = int(time.time()) // window
        key = f"saup:rate:{digest(identity)}:{bucket}"
        if self.client is not None:
            try:
                count = self.client.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", 1, key, window + 1)
            except Exception as exc:
                raise DomainError("RATE_LIMIT_BACKEND_UNAVAILABLE", 503) from exc
        else:
            with self.lock:
                self.counts = {k: v for k, v in self.counts.items() if v[0] >= bucket}
                count = self.counts.get(key, (bucket, 0))[1] + 1
                self.counts[key] = (bucket, count)
        if count > limit:
            raise DomainError("RATE_LIMITED", 429)
