from __future__ import annotations

from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Signed cookie for session (stateless)
serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="water_compat_sid")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def sign_session(payload: dict) -> str:
    return serializer.dumps(payload)


def verify_session(token: str, max_age_seconds: int | None = None) -> dict | None:
    try:
        return serializer.loads(token, max_age=max_age_seconds or settings.SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
