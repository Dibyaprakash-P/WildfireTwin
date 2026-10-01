"""Authentication dependencies."""

from __future__ import annotations

import jwt
from bson import ObjectId
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.auth.security import decode_access_token
from backend.app.db import get_db
from backend.app.utils.errors import APIError

_bearer = HTTPBearer(auto_error=False)


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if creds is None or creds.scheme.lower() != "bearer":
        raise APIError(401, "not_authenticated", "Sign in required.")
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise APIError(401, "token_expired", "Session expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise APIError(401, "invalid_token", "Invalid session token.")
    try:
        user = await get_db().users.find_one({"_id": ObjectId(payload["sub"])})
    except Exception:
        user = None
    if not user:
        raise APIError(401, "invalid_token", "Invalid session token.")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def user_out(u: dict) -> dict:
    return {"id": str(u["_id"]), "email": u["email"], "auth_providers": u.get("auth_providers", []),
            "created_at": u["created_at"].isoformat()}
