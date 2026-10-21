"""Password hashing, signed bearer tokens and role checks. Deliberately small: enough
authentication and tenant isolation for an MVP, not an enterprise permissions framework."""
import hashlib
import hmac
import os
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

ROLE_RANK = {"viewer": 0, "operator": 1, "owner": 2}


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str

    def can(self, minimum: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[minimum]


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        expected = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(expected.hex(), digest_hex)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="dastavez-auth")


def issue_token(principal: Principal) -> str:
    return _serializer().dumps({"u": principal.user_id, "t": principal.tenant_id, "r": principal.role})


def read_token(token: str) -> Principal | None:
    try:
        data = _serializer().loads(token, max_age=get_settings().token_ttl_seconds)
        return Principal(user_id=data["u"], tenant_id=data["t"], role=data["r"])
    except (BadSignature, SignatureExpired, KeyError):
        return None
