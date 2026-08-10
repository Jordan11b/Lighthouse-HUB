import datetime
from .router import Router
from .db import now_iso
from .security import verify_password, hash_password, new_session_token, generate_email_code, hash_code, verify_code
from .errors import bad_request, unauthorized, forbidden
from .audit import log

router = Router()

# Multi-factor authentication is part of the spec's "invite-only accounts, MFA, and
# complete audit history" security principle. It's implemented as a 6-digit code emailed
# at login (see EMAIL_CODE_* below) rather than an authenticator app - no separate setup
# step, since it just goes to the email address already on the account. It's switched off
# here to make local click-through testing easier while other features are being reviewed.
# Flip this back to True before this goes anywhere near real student data.
MFA_REQUIRED = True

EMAIL_CODE_TTL_MINUTES = 10
EMAIL_CODE_MAX_ATTEMPTS = 5


def _issue_and_send_code(ctx_db, token, user):
    """Generate a fresh login code, store its hash against the session, and send it to the
    user's notification address (their configured override, or their account email) if
    SMTP is configured (see lighthouse/mailer.py). If it isn't configured, or the send
    fails, the code is printed to the server console instead so local testing still works
    without email set up. Deliberately NOT reusing the shared _deliver() helper from
    routes_alerts.py here - that writes the full message into notification_log, which
    admins/supervising SLPs can browse on the Alerts page, and a live login code isn't
    something other staff should be able to read there. The log entry below records that a
    code was sent, without the code itself."""
    from .mailer import send_email, notify_address
    code = generate_email_code()
    expires_dt = datetime.datetime.utcnow() + datetime.timedelta(minutes=EMAIL_CODE_TTL_MINUTES)
    # Same timespec as now_iso() so the two strings compare correctly lexicographically.
    expires = expires_dt.isoformat(timespec="seconds") + "Z"
    ctx_db.execute(
        "UPDATE sessions_auth SET mfa_code_hash=?, mfa_code_expires=?, mfa_attempts=0 WHERE token=?",
        (hash_code(code), expires, token),
    )
    # dedupe_key must be unique per row (notification_log has a UNIQUE constraint on it) -
    # include the code's own hash as a nonce so back-to-back resends in the same second
    # can't collide.
    ctx_db.execute(
        "INSERT INTO notification_log (category, dedupe_key, recipient_user_id, subject, body, sent_at) "
        "VALUES (?,?,?,?,?,?)",
        ("security", f"mfa_code:{token}:{hash_code(code)[:12]}", user["id"], "Sign-in code sent",
         "A 6-digit sign-in code was emailed for this login attempt. (Not shown here for security.)",
         now_iso()),
    )
    to_addr = notify_address(user)
    subject = "Your Lighthouse Therapy Hub sign-in code"
    body = (f"Your sign-in code is {code}. It expires in {EMAIL_CODE_TTL_MINUTES} minutes. "
            f"If you didn't just try to sign in, you can ignore this.")
    sent = send_email(ctx_db, to_addr, subject, body) if to_addr else False
    if sent:
        print(f"[email sent] sign-in code to {to_addr}", flush=True)
    else:
        # flush=True: stdout is block-buffered when it's not a live terminal (e.g.
        # redirected to a log file, or a host's log collector), so without this the code
        # might not actually show up until something else fills the buffer.
        print(f"[simulated email] to {to_addr or user['email']}: your Lighthouse Therapy Hub sign-in code is "
              f"{code} (expires in {EMAIL_CODE_TTL_MINUTES} minutes)", flush=True)


def public_user(row):
    return {
        "id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"],
        "is_active": bool(row["is_active"]), "mfa_enabled": bool(row["mfa_enabled"]),
        "notify_email": row["notify_email"] if "notify_email" in row.keys() else None,
        "is_supervising_slp": bool(row["is_supervising_slp"]) if "is_supervising_slp" in row.keys() else False,
        "supervising_slp_id": row["supervising_slp_id"], "credentials": row["credentials"],
        "license_number": row["license_number"], "license_expiration": row["license_expiration"],
    }


@router.post("/api/auth/login")
def login(ctx, params, body):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        raise bad_request("Email and password required")

    row = ctx.db.execute("SELECT * FROM users WHERE lower(email)=?", (email,)).fetchone()
    if not row or not row["is_active"]:
        raise unauthorized("Invalid email or password")
    if not row["password_hash"] or not verify_password(password, row["password_hash"], row["password_salt"]):
        log(ctx.db, row["id"] if row else None, "login_failed", "user", row["id"] if row else None)
        ctx.db.commit()
        raise unauthorized("Invalid email or password")

    token = new_session_token()
    mfa_verified_on_create = 0 if MFA_REQUIRED else 1
    ctx.db.execute(
        "INSERT INTO sessions_auth (token, user_id, created_at, last_activity, mfa_verified) VALUES (?,?,?,?,?)",
        (token, row["id"], now_iso(), now_iso(), mfa_verified_on_create),
    )

    if not MFA_REQUIRED:
        log(ctx.db, row["id"], "login_ok_mfa_disabled", "user", row["id"])
        ctx.db.commit()
        return 200, {"token": token, "mfa_required": False}

    log(ctx.db, row["id"], "login_password_ok", "user", row["id"])
    ctx.db.commit()
    _issue_and_send_code(ctx.db, token, row)
    ctx.db.commit()
    return 200, {"token": token, "mfa_required": True}


@router.post("/api/auth/mfa/verify")
def mfa_verify(ctx, params, body):
    token = body.get("token") or ""
    code = str(body.get("code") or "").strip()
    srow = ctx.db.execute("SELECT * FROM sessions_auth WHERE token=?", (token,)).fetchone()
    if not srow:
        raise unauthorized("Session expired, please log in again")
    user = ctx.db.execute("SELECT * FROM users WHERE id=?", (srow["user_id"],)).fetchone()
    if not user:
        raise unauthorized("Session expired, please log in again")

    if srow["mfa_attempts"] >= EMAIL_CODE_MAX_ATTEMPTS:
        raise forbidden("Too many incorrect attempts. Request a new code.")

    expired = not srow["mfa_code_expires"] or srow["mfa_code_expires"] < (now_iso())
    if expired or not verify_code(code, srow["mfa_code_hash"]):
        ctx.db.execute("UPDATE sessions_auth SET mfa_attempts=mfa_attempts+1 WHERE token=?", (token,))
        log(ctx.db, user["id"], "mfa_failed", "user", user["id"])
        ctx.db.commit()
        if expired:
            raise unauthorized("That code has expired. Request a new one.")
        raise unauthorized("Incorrect code")

    ctx.db.execute(
        "UPDATE sessions_auth SET mfa_verified=1, last_activity=?, mfa_code_hash=NULL, mfa_code_expires=NULL "
        "WHERE token=?", (now_iso(), token),
    )
    log(ctx.db, user["id"], "mfa_verified", "user", user["id"])
    ctx.db.commit()
    return 200, {"user": public_user(user)}


@router.post("/api/auth/mfa/resend")
def mfa_resend(ctx, params, body):
    token = body.get("token") or ""
    srow = ctx.db.execute("SELECT * FROM sessions_auth WHERE token=?", (token,)).fetchone()
    if not srow:
        raise unauthorized("Session expired, please log in again")
    if srow["mfa_verified"]:
        return 200, {"ok": True}
    user = ctx.db.execute("SELECT * FROM users WHERE id=?", (srow["user_id"],)).fetchone()
    if not user:
        raise unauthorized("Session expired, please log in again")
    _issue_and_send_code(ctx.db, token, user)
    log(ctx.db, user["id"], "mfa_code_resent", "user", user["id"])
    ctx.db.commit()
    return 200, {"ok": True}


@router.post("/api/auth/logout")
def logout(ctx, params, body):
    if ctx.session_token:
        ctx.db.execute("DELETE FROM sessions_auth WHERE token=?", (ctx.session_token,))
        ctx.db.commit()
    return 200, {"ok": True}


@router.get("/api/auth/me")
def me(ctx, params, body):
    if not ctx.user:
        raise unauthorized()
    return 200, {"user": public_user(ctx.user)}
