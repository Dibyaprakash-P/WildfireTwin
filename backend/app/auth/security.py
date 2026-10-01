"""Password hashing (Argon2id), OTP hashing and JWT handling."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend.app.config import get_settings

_ph = PasswordHasher()  # argon2-cffi defaults: Argon2id, RFC 9106 low-memory profile


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(email: str, code: str, salt: str) -> str:
    """HMAC-SHA256 keyed by the server secret and a per-verification salt; the OTP is never stored."""
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{salt}|{email}|{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(email: str, code: str, salt: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(email, code, salt), stored_hash)


def create_access_token(user_id: str, email: str) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.jwt_expire_minutes)
    token = jwt.encode({"sub": user_id, "email": email, "iat": now, "exp": exp, "typ": "access"},
                       s.jwt_secret, algorithm=s.jwt_algorithm)
    return token, s.jwt_expire_minutes * 60


def decode_access_token(token: str) -> dict:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]})
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload
