from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

from backend.app.config import get_settings

PW = "fire-Sim2026"


def _db():
    s = get_settings()
    return MongoClient(s.mongodb_uri)[s.mongodb_db]


def test_invalid_email(client):
    r = client.post("/api/auth/signup", json={"email": "not-an-email", "password": PW, "confirm_password": PW})
    assert r.status_code == 400 and r.json()["error"]["message"] == "Invalid email address."


def test_password_mismatch(client):
    r = client.post("/api/auth/signup", json={"email": "a@example.org", "password": PW, "confirm_password": PW + "x"})
    assert r.json()["error"]["code"] == "password_mismatch"


def test_signup_otp_login_flow(client, outbox):
    email = "analyst@example.org"
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "confirm_password": PW})
    assert r.status_code == 200 and r.json()["status"] == "otp_sent"
    v = _db().email_verifications.find_one({"email": email})
    code = outbox.last_code(email)
    assert code not in str(v) and "password" not in v       # OTP and password never stored in plaintext
    assert v["password_hash"].startswith("$argon2id$")
    bad = "000000" if code != "000000" else "111111"
    r = client.post("/api/auth/verify-otp", json={"email": email, "code": bad})
    assert r.status_code == 400 and r.json()["error"]["details"]["attempts_left"] == 4
    r = client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert r.status_code == 200 and r.json()["message"] == "Signup successful."
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == email
    r = client.post("/api/auth/login", json={"email": email, "password": "wrong-pass1"})
    assert r.status_code == 401 and r.json()["error"]["message"] == "Incorrect email or password."
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200 and r.json()["access_token"]
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "confirm_password": PW})
    assert r.json()["error"]["code"] == "account_exists"


def test_login_unknown_account(client):
    r = client.post("/api/auth/login", json={"email": "nobody@example.org", "password": PW})
    assert r.status_code == 404 and r.json()["error"]["message"] == "No account found. Please sign up first."


def test_otp_expiry_and_attempt_limit(client, outbox):
    email = "expiry@example.org"
    client.post("/api/auth/signup", json={"email": email, "password": PW, "confirm_password": PW})
    code = outbox.last_code(email)
    _db().email_verifications.update_one({"email": email}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    r = client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert r.json()["error"]["code"] == "otp_expired"
    _db().email_verifications.update_one({"email": email}, {"$set": {"expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
                                                                      "attempts": 5}})
    r = client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert r.json()["error"]["code"] == "too_many_attempts"


def test_resend_cooldown(client, outbox):
    email = "resend@example.org"
    client.post("/api/auth/signup", json={"email": email, "password": PW, "confirm_password": PW})
    r = client.post("/api/auth/resend-otp", json={"email": email})
    assert r.status_code == 429 and r.json()["error"]["code"] == "resend_cooldown"
    _db().email_verifications.update_one({"email": email}, {"$set": {"resend_available_at": datetime.now(timezone.utc)}})
    first = outbox.last_code(email)
    r = client.post("/api/auth/resend-otp", json={"email": email})
    assert r.status_code == 200
    second = outbox.last_code(email)
    r = client.post("/api/auth/verify-otp", json={"email": email, "code": second})
    assert r.status_code == 200 or first == second


def test_google_not_configured(client):
    r = client.post("/api/auth/google", json={"credential": "x" * 20})
    assert r.status_code == 503 and r.json()["error"]["code"] == "google_not_configured"


def test_protected_endpoint_requires_auth(client):
    r = client.post("/api/predictions", json={"fire_id": "FE-XXXX"})
    assert r.status_code == 401
