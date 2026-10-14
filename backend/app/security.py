"""Sesi HMAC + verifikasi password + anti brute-force.

Format token sesi SAMA PERSIS dengan dashboard versi lama
(base64 payload {"exp":...} + "." + HMAC-SHA256 hex) sehingga cookie
yang sudah terbit tetap berlaku setelah migrasi stack.
"""
import base64
import hashlib
import hmac
import json
import threading
import time

from fastapi import HTTPException, Request

from .config import CFG

COOKIE_NAME = "rn_dash"
SESSION_DAYS = 7


def verify_password(password, stored):
    try:
        algo, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def make_session(secret):
    exp = int(time.time()) + SESSION_DAYS * 24 * 3600
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode()
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig


def check_session(secret, token):
    if not token or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    expect = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        return int(data.get("exp", 0)) > int(time.time())
    except Exception:
        return False


FAILS = {}
FAILS_LOCK = threading.Lock()


def brute_check(ip):
    now = time.time()
    with FAILS_LOCK:
        lst = [t for t in FAILS.get(ip, []) if now - t < 600]
        FAILS[ip] = lst
        return len(lst) >= 5


def brute_record(ip):
    with FAILS_LOCK:
        FAILS.setdefault(ip, []).append(time.time())


def brute_clear(ip):
    with FAILS_LOCK:
        FAILS.pop(ip, None)


def client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "-")


def is_authed(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    return check_session(CFG["SESSION_SECRET"], token)


def require_auth(request: Request):
    if not is_authed(request):
        raise HTTPException(status_code=401, detail="belum login")
