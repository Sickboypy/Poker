import hashlib
import secrets

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session as DbSession

from .database import SessionLocal
from .models import Session as SessionModel, User

ITERATIONS = 200_000


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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: DbSession = Depends(get_db),
    mf_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    token = mf_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if token:
        session = db.get(SessionModel, token)
        if session:
            user = db.get(User, session.user_id)
            if user:
                return user

    raise HTTPException(401, "Necesitás iniciar sesión")
