"""AUTHENTICATION - password hashing and JWT tokens (HS256), using only the standard library.

Login returns a signed token. The browser sends it with every request
(Authorization: Bearer <token>) and the API rejects requests without a valid one.
"""
import base64
import hashlib
import hmac
import json
import os
import time

SECRET = os.environ.get("SMS_SECRET", "change-this-secret-in-production")
TOKEN_HOURS = 8


def hash_password(password, salt=None):
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    salt = stored.split("$")[0]
    return hmac.compare_digest(hash_password(password, salt), stored)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(message):
    return _b64(hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).digest())


def create_token(user):
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({
        "sub": user["email"], "name": user["name"], "role": user["role"],
        "exp": int(time.time()) + TOKEN_HOURS * 3600,
    }).encode())
    return f"{header}.{payload}.{_sign(header + '.' + payload)}"


def verify_token(token):
    try:
        header, payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(header + "." + payload)):
            return None
        data = json.loads(_unb64(payload))
        return data if data["exp"] > time.time() else None
    except Exception:
        return None
