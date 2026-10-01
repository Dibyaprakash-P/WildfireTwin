"""/api/auth — email + password with OTP verification, and Google Sign-In."""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request
from pymongo.errors import DuplicateKeyError

from backend.app.auth.deps import client_ip, current_user, user_out
from backend.app.auth.security import create_access_token, generate_otp, hash_otp, hash_password, otp_matches, verify_password
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.schemas.auth import EmailOnly, GoogleLoginRequest, LoginRequest, SignupRequest, VerifyOtpRequest
from backend.app.services.email import EmailNotConfigured, get_email_service, mask_email
from backend.app.utils.errors import APIError
from backend.app.utils.events import emit
from backend.app.utils.ratelimit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])

PASSWORD_MIN = 8


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise APIError(400, "invalid_email", "Invalid email address.")


def check_password_policy(pw: str) -> None:
    if len(pw) < PASSWORD_MIN:
        raise APIError(400, "weak_password", f"Password must be at least {PASSWORD_MIN} characters.")
    if pw.isdigit() or pw.isalpha():
        raise APIError(400, "weak_password", "Password must contain both letters and numbers or symbols.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _send_otp(email: str, code: str) -> None:
    try:
        await get_email_service().send_verification_otp(email, code)
    except EmailNotConfigured as exc:
        raise APIError(503, "email_not_configured", "Email service is not configured.", str(exc))
    except Exception:
        await emit("auth", f"verification email to {mask_email(email)} failed", "ERROR")
        raise APIError(502, "email_failed", "Could not send verification email. Please try again.")


def _token_response(user: dict, message: str | None = None) -> dict:
    token, exp = create_access_token(str(user["_id"]), user["email"])
    return {"access_token": token, "token_type": "bearer", "expires_in": exp, "user": user_out(user), "message": message}


@router.post("/signup")
async def signup(req: SignupRequest, request: Request):
    s = get_settings()
    email = normalize_email(req.email)
    limiter.check(f"signup:{client_ip(request)}", 10, 3600)
    if req.password != req.confirm_password:
        raise APIError(400, "password_mismatch", "Passwords do not match.")
    check_password_policy(req.password)
    db = get_db()
    if await db.users.find_one({"email": email}):
        raise APIError(409, "account_exists", "An account with this email already exists. Please sign in.")
    code, salt = generate_otp(), secrets.token_hex(8)
    now = _now()
    pw_hash = await asyncio.to_thread(hash_password, req.password)
    await db.email_verifications.replace_one({"email": email}, {
        "email": email, "password_hash": pw_hash, "otp_hash": hash_otp(email, code, salt), "otp_salt": salt,
        "expires_at": now + timedelta(seconds=s.otp_ttl_seconds), "attempts": 0, "resends": 0,
        "resend_available_at": now + timedelta(seconds=s.otp_resend_cooldown_seconds),
        "created_at": now, "purge_at": now + timedelta(hours=24),
    }, upsert=True)
    await _send_otp(email, code)
    await emit("auth", f"verification code issued for {mask_email(email)}")
    return {"status": "otp_sent", "email": email, "expires_in": s.otp_ttl_seconds,
            "resend_in": s.otp_resend_cooldown_seconds, "message": "Verification code sent to your email."}


@router.post("/verify-otp")
async def verify_otp(req: VerifyOtpRequest, request: Request):
    s = get_settings()
    email = normalize_email(req.email)
    limiter.check(f"verify:{client_ip(request)}", 30, 900)
    db = get_db()
    v = await db.email_verifications.find_one({"email": email})
    if not v:
        raise APIError(404, "no_pending_verification", "No pending verification for this email. Please sign up again.")
    if v["attempts"] >= s.otp_max_attempts:
        raise APIError(429, "too_many_attempts", "Too many incorrect attempts. Request a new code.")
    if _now() > v["expires_at"]:
        raise APIError(410, "otp_expired", "Verification code expired. Request a new code.")
    if not otp_matches(email, req.code, v["otp_salt"], v["otp_hash"]):
        await db.email_verifications.update_one({"_id": v["_id"]}, {"$inc": {"attempts": 1}})
        left = s.otp_max_attempts - v["attempts"] - 1
        raise APIError(400, "otp_invalid", "Incorrect verification code.", {"attempts_left": max(left, 0)})
    user = {"email": email, "password_hash": v["password_hash"], "auth_providers": ["password"],
            "email_verified": True, "created_at": _now()}
    try:
        res = await db.users.insert_one(user)
    except DuplicateKeyError:
        raise APIError(409, "account_exists", "An account with this email already exists. Please sign in.")
    user["_id"] = res.inserted_id
    await db.email_verifications.delete_one({"_id": v["_id"]})
    await emit("auth", f"account verified and created for {mask_email(email)}")
    return _token_response(user, "Signup successful.")


@router.post("/resend-otp")
async def resend_otp(req: EmailOnly, request: Request):
    s = get_settings()
    email = normalize_email(req.email)
    limiter.check(f"resend:{client_ip(request)}", 10, 3600)
    db = get_db()
    v = await db.email_verifications.find_one({"email": email})
    if not v:
        raise APIError(404, "no_pending_verification", "No pending verification for this email. Please sign up again.")
    now = _now()
    if now < v["resend_available_at"]:
        wait = int((v["resend_available_at"] - now).total_seconds()) + 1
        raise APIError(429, "resend_cooldown", f"Please wait {wait}s before requesting a new code.", {"retry_after_s": wait})
    if v.get("resends", 0) >= s.otp_max_resends:
        raise APIError(429, "too_many_resends", "Too many codes requested. Please sign up again later.")
    code, salt = generate_otp(), secrets.token_hex(8)
    await db.email_verifications.update_one({"_id": v["_id"]}, {"$set": {
        "otp_hash": hash_otp(email, code, salt), "otp_salt": salt, "attempts": 0,
        "expires_at": now + timedelta(seconds=s.otp_ttl_seconds),
        "resend_available_at": now + timedelta(seconds=s.otp_resend_cooldown_seconds)}, "$inc": {"resends": 1}})
    await _send_otp(email, code)
    await emit("auth", f"verification code re-issued for {mask_email(email)}")
    return {"status": "otp_sent", "email": email, "expires_in": s.otp_ttl_seconds,
            "resend_in": s.otp_resend_cooldown_seconds, "message": "A new verification code was sent."}


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    email = normalize_email(req.email)
    limiter.check(f"login:{client_ip(request)}", 20, 900)
    limiter.check(f"login-email:{email}", 10, 900)
    user = await get_db().users.find_one({"email": email})
    if not user:
        raise APIError(404, "account_not_found", "No account found. Please sign up first.")
    ok = await asyncio.to_thread(verify_password, req.password, user.get("password_hash"))
    if not ok:
        raise APIError(401, "invalid_credentials", "Incorrect email or password.")
    await emit("auth", f"sign-in {mask_email(email)}")
    return _token_response(user)


@router.get("/google/config")
async def google_config():
    cid = get_settings().google_client_id
    return {"configured": bool(cid), "client_id": cid or None}


@router.post("/google")
async def google_login(req: GoogleLoginRequest, request: Request):
    s = get_settings()
    if not s.google_client_id:
        raise APIError(503, "google_not_configured", "Google Sign-In is not configured on this server (GOOGLE_CLIENT_ID).")
    limiter.check(f"google:{client_ip(request)}", 20, 900)
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token
    try:
        info = await asyncio.to_thread(id_token.verify_oauth2_token, req.credential, g_requests.Request(), s.google_client_id)
    except ValueError:
        raise APIError(401, "google_invalid", "Google sign-in could not be verified.")
    if not info.get("email") or not info.get("email_verified"):
        raise APIError(401, "google_unverified", "Google account email is not verified.")
    email = info["email"].lower()
    db = get_db()
    user = await db.users.find_one({"email": email})
    if user:
        await db.users.update_one({"_id": user["_id"]}, {"$addToSet": {"auth_providers": "google"},
                                                         "$set": {"google_sub": info["sub"]}})
        user = await db.users.find_one({"_id": user["_id"]})
    else:
        user = {"email": email, "auth_providers": ["google"], "google_sub": info["sub"], "email_verified": True,
                "created_at": _now()}
        user["_id"] = (await db.users.insert_one(user)).inserted_id
    await emit("auth", f"google sign-in {mask_email(email)}")
    return _token_response(user)


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user_out(user)
