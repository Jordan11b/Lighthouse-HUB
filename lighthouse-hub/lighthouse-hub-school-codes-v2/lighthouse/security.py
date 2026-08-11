"""Password hashing, session tokens, and TOTP-based MFA.

Standard-library only (hashlib, hmac, secrets, base64, struct, time).
Implements the real algorithms (PBKDF2-HMAC-SHA256 for passwords, RFC 6238
TOTP for MFA) rather than stubs, with zero third-party dependencies.
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time


PBKDF2_ITERATIONS = 260_000


def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return base64.b64encode(dk).decode(), base64.b64encode(salt).decode()


def verify_password(password, stored_hash_b64, salt_b64):
    salt = base64.b64decode(salt_b64)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(base64.b64encode(dk).decode(), stored_hash_b64)


def new_session_token():
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Emailed one-time login codes (replaces authenticator-app MFA - simpler for
# non-technical staff, and doesn't need a setup step since it's sent to the
# email address already on file for the account).
# ---------------------------------------------------------------------------

def generate_email_code():
    """A 6-digit numeric code, cryptographically random (not just random.randint)."""
    return str(secrets.randbelow(1_000_000)).zfill(6)


def hash_code(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_code(code, stored_hash):
    if not code or not stored_hash:
        return False
    return hmac.compare_digest(hash_code(str(code)), stored_hash)


# ---------------------------------------------------------------------------
# TOTP (RFC 6238) built on hmac/hashlib only - no third-party otp library.
# ---------------------------------------------------------------------------

def generate_totp_secret():
    """Base32 secret, suitable for entry into any authenticator app."""
    raw = os.urandom(20)
    return base64.b32encode(raw).decode("utf-8").rstrip("=")


def _hotp(secret_b32, counter, digits=6):
    key = base64.b32decode(secret_b32 + "=" * ((8 - len(secret_b32) % 8) % 8))
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code_int = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code_int).zfill(digits)


def totp_now(secret_b32, step=30, digits=6, at=None):
    counter = int((at if at is not None else time.time()) // step)
    return _hotp(secret_b32, counter, digits)


def verify_totp(secret_b32, code, step=30, digits=6, window=2):
    if not code or not str(code).isdigit():
        return False
    now = time.time()
    for offset in range(-window, window + 1):
        if hmac.compare_digest(totp_now(secret_b32, step, digits, at=now + offset * step), str(code)):
            return True
    return False
