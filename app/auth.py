import hashlib
import secrets

from fastapi import Cookie, Depends, Header, HTTPException

from .store import Store

ITERATIONS = 200_000

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), ITERATIONS
    ).hex()
    return f"pbkdf2${ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return secrets.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def get_current_user(
    store: Store = Depends(get_store),
    mf_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    token = mf_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if token:
        user = store.get_session_user(token)
        if user:
            return user

    raise HTTPException(401, "Necesitás iniciar sesión")
