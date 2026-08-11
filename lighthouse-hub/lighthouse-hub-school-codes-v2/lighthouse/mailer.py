"""Real outbound email via smtplib (Python standard library - no third-party mail SDK).

Configuration comes from environment variables first (the recommended path for a real
deployment - e.g. Render's Environment tab - since that keeps the password out of the
database entirely), falling back to the Administration > Settings screen for convenience
when running locally. If neither is set, send_email() just returns False and every caller
falls back to the existing simulated outbox (console print + notification_log) - nothing
breaks, nothing is required to keep using the app exactly as before.
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText

SENSITIVE_SETTINGS = {"smtp_password"}
MASKED_VALUE = "••••••••"  # bullets, shown instead of the real password

ENV_MAP = {
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_username": "SMTP_USERNAME",
    "smtp_password": "SMTP_PASSWORD",
    "smtp_from_email": "SMTP_FROM_EMAIL",
    "smtp_use_tls": "SMTP_USE_TLS",
}


def _settings_dict(db):
    return {r["key"]: r["value"] for r in db.execute("SELECT * FROM settings").fetchall()}


def env_overridden_keys():
    """Which settings keys currently have an environment variable set, taking priority
    over whatever's saved in the Administration screen. Used by the UI so an admin editing
    settings locally isn't confused about why their change didn't seem to do anything."""
    return [k for k, env_key in ENV_MAP.items() if os.environ.get(env_key)]


def get_smtp_config(db):
    settings = _settings_dict(db)

    def val(key):
        return os.environ.get(ENV_MAP[key]) or settings.get(key)

    host = val("smtp_host")
    if not host:
        return None
    username = val("smtp_username") or ""
    return {
        "host": host,
        "port": int(val("smtp_port") or 587),
        "username": username,
        "password": val("smtp_password") or "",
        "from_email": val("smtp_from_email") or username,
        "use_tls": str(val("smtp_use_tls") or "true").lower() not in ("false", "0", "no"),
    }


def is_configured(db):
    return get_smtp_config(db) is not None


def send_email(db, to_email, subject, body):
    """Returns True if it actually sent, False if not configured or delivery failed.
    Callers should treat False as "fall back to the simulated outbox" - a bad SMTP config
    should never be able to block someone from logging in or an alert from being recorded."""
    if not to_email:
        return False
    config = get_smtp_config(db)
    if not config:
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = config["from_email"] or config["username"] or "no-reply@lighthouse.example"
        msg["To"] = to_email
        if config["port"] == 465:
            with smtplib.SMTP_SSL(config["host"], config["port"], context=ssl.create_default_context(), timeout=10) as server:
                if config["username"]:
                    server.login(config["username"], config["password"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
                if config["use_tls"]:
                    server.starttls(context=ssl.create_default_context())
                if config["username"]:
                    server.login(config["username"], config["password"])
                server.send_message(msg)
        return True
    except Exception as e:
        print(f"[email] real send to {to_email} failed ({e!r}) - falling back to the simulated outbox", flush=True)
        return False


def notify_address(user_row):
    """Where this user's notifications should actually go: their configured override
    (set on My Account or by an admin), or their account/login email if they haven't set
    one. Login itself always uses the account email regardless of this."""
    if not user_row:
        return None
    try:
        override = user_row["notify_email"]
    except (KeyError, IndexError):
        override = None
    addr = (override or user_row["email"] or "").strip()
    return addr or None
