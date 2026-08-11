import json
import secrets
import string
import datetime
from .router import Router
from .db import now_iso
from .security import hash_password
from .errors import bad_request, forbidden, not_found, conflict
from .audit import log
from .routes_auth import public_user
from . import compliance as comp
from . import mailer

router = Router()


def gen_temp_password():
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _email_temp_password(ctx, row, temp_password, is_new_account):
    """Best-effort: email a freshly generated temp password to the account it belongs to.
    Returns whether it actually went out, so the caller can still show it on screen as a
    fallback when email isn't configured or the send fails - nothing here is allowed to
    block the reset/invite itself."""
    to_addr = mailer.notify_address(row)
    if not to_addr:
        return False
    if is_new_account:
        subject = "Your Lighthouse Therapy Hub account"
        intro = "An account was created for you on Lighthouse Therapy Hub."
    else:
        subject = "Your Lighthouse Therapy Hub password was reset"
        intro = "Your Lighthouse Therapy Hub password was reset by a clinic administrator."
    body = (f"{intro}\n\nTemporary password: {temp_password}\n\n"
            f"Sign in with this password, then set your own from My Account.")
    return mailer.send_email(ctx.db, to_addr, subject, body)


# ---------------------------------------------------------------- users ----

@router.get("/api/users")
def list_users(ctx, params, body):
    role_filter = params.get("_qs", {}).get("role")
    if ctx.role == "admin":
        rows = ctx.db.execute("SELECT * FROM users ORDER BY name").fetchall()
    elif ctx.role == "supervising_slp":
        rows = ctx.db.execute(
            "SELECT * FROM users WHERE id=? OR supervising_slp_id=? ORDER BY name",
            (ctx.user_id, ctx.user_id),
        ).fetchall()
    else:
        rows = ctx.db.execute("SELECT * FROM users WHERE id=?", (ctx.user_id,)).fetchall()
    out = [public_user(r) for r in rows]
    if role_filter:
        out = [u for u in out if u["role"] == role_filter]
    return 200, {"users": out}


@router.post("/api/users")
def create_user(ctx, params, body):
    ctx.require_role("admin")
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    role = body.get("role")
    if not name or not email or role not in ("admin", "supervising_slp", "provider"):
        raise bad_request("name, email, and a valid role are required")
    exists = ctx.db.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
    if exists:
        raise conflict("A user with that email already exists")
    temp_password = gen_temp_password()
    pw_hash, pw_salt = hash_password(temp_password)
    is_supervising_slp = 1 if body.get("is_supervising_slp") in (True, "true", "1", 1) else 0
    cur = ctx.db.execute(
        "INSERT INTO users (name,email,role,password_hash,password_salt,is_active,supervising_slp_id,"
        "credentials,license_number,license_expiration,invited_at,created_at,is_supervising_slp) "
        "VALUES (?,?,?,?,?,1,?,?,?,?,?,?,?)",
        (name, email, role, pw_hash, pw_salt, body.get("supervising_slp_id"),
         body.get("credentials"), body.get("license_number"), body.get("license_expiration"),
         now_iso(), now_iso(), is_supervising_slp),
    )
    uid = cur.lastrowid
    log(ctx.db, ctx.user_id, "user_invited", "user", uid, {"email": email, "role": role})
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    resp = public_user(row)
    resp["temporary_password"] = temp_password  # shown once, invite-only account provisioning
    resp["temp_password_emailed"] = _email_temp_password(ctx, row, temp_password, is_new_account=True)
    return 201, {"user": resp}


@router.patch("/api/users/<id>")
def update_user(ctx, params, body):
    ctx.require_role("admin")
    uid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise not_found()
    if "is_supervising_slp" in body:
        body["is_supervising_slp"] = 1 if body["is_supervising_slp"] in (True, "true", "1", 1) else 0
    fields = ["name", "supervising_slp_id", "credentials", "license_number", "license_expiration", "notify_email",
              "is_supervising_slp"]
    updates, values = [], []
    for f in fields:
        if f in body:
            updates.append(f"{f}=?")
            values.append(body[f])
    if updates:
        values.append(uid)
        ctx.db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", values)
        log(ctx.db, ctx.user_id, "user_updated", "user", uid, body)
        ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return 200, {"user": public_user(row)}


@router.post("/api/users/<id>/deactivate")
def deactivate_user(ctx, params, body):
    ctx.require_role("admin")
    uid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise not_found()
    if row["role"] == "admin":
        active_admins = ctx.db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()["c"]
        if active_admins <= 1:
            raise forbidden("The final active administrator cannot be removed")
    ctx.db.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
    ctx.db.execute("DELETE FROM sessions_auth WHERE user_id=?", (uid,))
    log(ctx.db, ctx.user_id, "user_deactivated", "user", uid)
    ctx.db.commit()
    return 200, {"ok": True}


@router.post("/api/users/<id>/reactivate")
def reactivate_user(ctx, params, body):
    ctx.require_role("admin")
    uid = int(params["id"])
    ctx.db.execute("UPDATE users SET is_active=1 WHERE id=?", (uid,))
    log(ctx.db, ctx.user_id, "user_reactivated", "user", uid)
    ctx.db.commit()
    return 200, {"ok": True}


@router.delete("/api/users/<id>")
def delete_user(ctx, params, body):
    """Permanently erase a user account - unlike deactivate, the row is actually gone. Only
    allowed when the account has no real service history that would be lost: no student
    currently assigned to them, no attendance they recorded, no sessions scheduled under
    them, no makeup-queue entries, no pending approval request, and (for SLPs) nobody still
    reporting to them. Anyone with real history is blocked with a message pointing to
    Deactivate instead - transfer their caseload first if they still have active students.
    Incidental metadata (login sessions, notification log entries, coverage grants,
    transfers, proposed-but-inactive recurring schedules, audit trail as the actor) is
    cleaned up automatically so it doesn't get in the way with a foreign-key error."""
    ctx.require_role("admin")
    uid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise not_found()

    if row["role"] == "admin":
        active_admins = ctx.db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()["c"]
        if active_admins <= 1 and row["is_active"]:
            raise forbidden("The final active administrator cannot be deleted")

    def count(q, *args):
        return ctx.db.execute(q, args).fetchone()["c"]

    blockers = []
    if count("SELECT COUNT(*) c FROM students WHERE provider_id=? OR supervising_slp_id=?", uid, uid):
        blockers.append("still assigned to a student record")
    if count("SELECT COUNT(*) c FROM attendance WHERE recorded_by=?", uid):
        blockers.append("has recorded attendance")
    if count("SELECT COUNT(*) c FROM sessions_sched WHERE provider_id=?", uid):
        blockers.append("has scheduled session(s)")
    if count("SELECT COUNT(*) c FROM attendance_corrections WHERE changed_by=?", uid):
        blockers.append("has attendance correction history")
    if count("SELECT COUNT(*) c FROM makeup_queue WHERE original_provider_id=? OR responsible_provider_id=?", uid, uid):
        blockers.append("has makeup-queue history")
    if count("SELECT COUNT(*) c FROM approvals WHERE requested_by=? AND status='pending'", uid):
        blockers.append("has a pending approval request")
    if count("SELECT COUNT(*) c FROM users WHERE supervising_slp_id=?", uid):
        blockers.append("still supervises other staff")

    if blockers:
        raise conflict(
            f"Can't permanently delete {row['name']} - this account has real history "
            f"({'; '.join(blockers)}). Deactivate it instead (transfer their caseload first "
            f"if they still have active students) to keep the record intact."
        )

    # No real service history left - safe to fully remove. Clear incidental references first
    # so the final delete doesn't trip a foreign-key constraint.
    ctx.db.execute("DELETE FROM sessions_auth WHERE user_id=?", (uid,))
    ctx.db.execute("DELETE FROM notification_log WHERE recipient_user_id=?", (uid,))
    ctx.db.execute("DELETE FROM audit_log WHERE actor_id=?", (uid,))
    ctx.db.execute("UPDATE approvals SET decided_by=NULL WHERE decided_by=?", (uid,))
    ctx.db.execute("DELETE FROM recurring_schedules WHERE provider_id=? OR proposed_by=?", (uid, uid))
    ctx.db.execute(
        "DELETE FROM temporary_coverage WHERE covering_provider_id=? OR original_provider_id=? OR authorized_by=?",
        (uid, uid, uid),
    )
    ctx.db.execute(
        "DELETE FROM student_transfers WHERE from_provider_id=? OR to_provider_id=? OR requested_by=?",
        (uid, uid, uid),
    )
    ctx.db.execute("UPDATE target_adjustments SET created_by=NULL WHERE created_by=?", (uid,))
    ctx.db.execute("UPDATE import_batches SET uploaded_by=NULL WHERE uploaded_by=?", (uid,))
    ctx.db.execute("UPDATE import_batches SET decided_by=NULL WHERE decided_by=?", (uid,))

    name, email, role = row["name"], row["email"], row["role"]
    ctx.db.execute("DELETE FROM users WHERE id=?", (uid,))
    log(ctx.db, ctx.user_id, "user_deleted", "user", uid, {"name": name, "email": email, "role": role})
    ctx.db.commit()
    return 200, {"ok": True}


@router.post("/api/users/<id>/reset-password")
def reset_password(ctx, params, body):
    ctx.require_role("admin")
    uid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise not_found()
    temp_password = gen_temp_password()
    pw_hash, pw_salt = hash_password(temp_password)
    ctx.db.execute(
        "UPDATE users SET password_hash=?, password_salt=?, mfa_secret=NULL, mfa_enabled=0 WHERE id=?",
        (pw_hash, pw_salt, uid),
    )
    ctx.db.execute("DELETE FROM sessions_auth WHERE user_id=?", (uid,))
    log(ctx.db, ctx.user_id, "user_password_reset", "user", uid)
    ctx.db.commit()
    emailed = _email_temp_password(ctx, row, temp_password, is_new_account=False)
    return 200, {"temporary_password": temp_password, "temp_password_emailed": emailed}


@router.post("/api/auth/me/notify-email")
def update_notify_email(ctx, params, body):
    """Self-service: let a signed-in user point their notifications (including MFA sign-in
    codes) at a different address than the one they log in with - e.g. a personal inbox
    instead of a shared/work one. Login itself always still uses the account email."""
    if not ctx.user:
        raise forbidden()
    notify_email = (body.get("notify_email") or "").strip() or None
    ctx.db.execute("UPDATE users SET notify_email=? WHERE id=?", (notify_email, ctx.user_id))
    log(ctx.db, ctx.user_id, "notify_email_updated", "user", ctx.user_id, {"notify_email": notify_email})
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (ctx.user_id,)).fetchone()
    return 200, {"user": public_user(row)}


@router.post("/api/auth/me/change-email")
def change_email(ctx, params, body):
    """Self-service: change the email address used to log in (and, unless a separate
    notification email is set, where MFA codes and alerts go). Requires the current
    password as confirmation, same as changing the password."""
    from .security import verify_password as vp
    if not ctx.user:
        raise forbidden()
    current_password = body.get("current_password") or ""
    new_email = (body.get("new_email") or "").strip().lower()
    if not new_email or "@" not in new_email:
        raise bad_request("Enter a valid email address")
    if not vp(current_password, ctx.user["password_hash"], ctx.user["password_salt"]):
        raise forbidden("Current password is incorrect")
    exists = ctx.db.execute(
        "SELECT id FROM users WHERE lower(email)=? AND id<>?", (new_email, ctx.user_id)
    ).fetchone()
    if exists:
        raise conflict("Another account already uses that email")
    ctx.db.execute("UPDATE users SET email=? WHERE id=?", (new_email, ctx.user_id))
    log(ctx.db, ctx.user_id, "email_changed", "user", ctx.user_id, {"new_email": new_email})
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM users WHERE id=?", (ctx.user_id,)).fetchone()
    return 200, {"user": public_user(row)}


@router.post("/api/auth/change-password")
def change_password(ctx, params, body):
    from .security import verify_password as vp
    if not ctx.user:
        raise forbidden()
    current = body.get("current_password") or ""
    new = body.get("new_password") or ""
    if len(new) < 8:
        raise bad_request("New password must be at least 8 characters")
    if not vp(current, ctx.user["password_hash"], ctx.user["password_salt"]):
        raise forbidden("Current password is incorrect")
    pw_hash, pw_salt = hash_password(new)
    ctx.db.execute("UPDATE users SET password_hash=?, password_salt=? WHERE id=?", (pw_hash, pw_salt, ctx.user_id))
    log(ctx.db, ctx.user_id, "password_changed", "user", ctx.user_id)
    ctx.db.commit()
    return 200, {"ok": True}


# --------------------------------------------------------------- schools ---

def school_public(row, ctx):
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    return d


@router.get("/api/schools")
def list_schools(ctx, params, body):
    rows = ctx.db.execute("SELECT * FROM schools ORDER BY name").fetchall()
    return 200, {"schools": [school_public(r, ctx) for r in rows]}


@router.post("/api/schools")
def create_school(ctx, params, body):
    ctx.require_role("admin")
    name = (body.get("name") or "").strip()
    if not name:
        raise bad_request("name is required")
    cur = ctx.db.execute(
        "INSERT INTO schools (name,code,address,contact_name,contact_phone,contact_email,hours,is_active) "
        "VALUES (?,?,?,?,?,?,?,1)",
        (name, (body.get("code") or "").strip() or None, body.get("address"), body.get("contact_name"),
         body.get("contact_phone"), body.get("contact_email"), body.get("hours")),
    )
    sid = cur.lastrowid
    log(ctx.db, ctx.user_id, "school_created", "school", sid, {"name": name})
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    return 201, {"school": school_public(row, ctx)}


@router.patch("/api/schools/<id>")
def update_school(ctx, params, body):
    ctx.require_role("admin")
    sid = int(params["id"])
    fields = ["name", "code", "address", "contact_name", "contact_phone", "contact_email", "hours", "is_active"]
    updates, values = [], []
    for f in fields:
        if f in body:
            updates.append(f"{f}=?")
            values.append(body[f])
    if updates:
        values.append(sid)
        ctx.db.execute(f"UPDATE schools SET {', '.join(updates)} WHERE id=?", values)
        log(ctx.db, ctx.user_id, "school_updated", "school", sid, body)
        ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not row:
        raise not_found()
    return 200, {"school": school_public(row, ctx)}


@router.get("/api/schools/<id>/closures")
def list_closures(ctx, params, body):
    rows = ctx.db.execute(
        "SELECT * FROM school_closures WHERE school_id=? ORDER BY closure_date", (params["id"],)
    ).fetchall()
    return 200, {"closures": [dict(r) for r in rows]}


@router.post("/api/schools/<id>/closures")
def add_closure(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    sid = int(params["id"])
    date = body.get("date")
    if not date:
        raise bad_request("date is required")
    cur = ctx.db.execute(
        "INSERT INTO school_closures (school_id, closure_date, reason) VALUES (?,?,?)",
        (sid, date, body.get("reason")),
    )
    log(ctx.db, ctx.user_id, "closure_added", "school", sid, {"date": date})
    ctx.db.commit()
    return 201, {"id": cur.lastrowid}


# -------------------------------------------------------------- students ---

def student_visible_to(ctx, student_row):
    if ctx.role == "admin":
        return True
    if ctx.role == "supervising_slp":
        return student_row["supervising_slp_id"] == ctx.user_id or _provider_reports_to(ctx, student_row["provider_id"])
    if ctx.role == "provider":
        return student_row["provider_id"] in ctx.visible_provider_ids()
    return False


def _provider_reports_to(ctx, provider_id):
    if provider_id is None:
        return False
    row = ctx.db.execute("SELECT supervising_slp_id FROM users WHERE id=?", (provider_id,)).fetchone()
    return bool(row and row["supervising_slp_id"] == ctx.user_id)


def student_public(row):
    d = dict(row)
    d["is_group"] = d["group_individual"] == "group"
    return d


@router.get("/api/students")
def list_students(ctx, params, body):
    qs = params.get("_qs", {})
    rows = ctx.db.execute("SELECT * FROM students ORDER BY name").fetchall()
    rows = [r for r in rows if student_visible_to(ctx, r)]
    if qs.get("school_id"):
        rows = [r for r in rows if str(r["school_id"]) == str(qs["school_id"])]
    if qs.get("provider_id"):
        rows = [r for r in rows if str(r["provider_id"]) == str(qs["provider_id"])]
    if qs.get("status") == "all":
        pass  # every status, including archived - used by the "merge" / dedupe workflow
    elif qs.get("status"):
        rows = [r for r in rows if r["status"] == qs["status"]]
    else:
        rows = [r for r in rows if r["status"] != "archived"]
    return 200, {"students": [student_public(r) for r in rows]}


@router.post("/api/students")
def create_student(ctx, params, body):
    # Providers may add students too (e.g. a new referral they're first to hear about), but
    # unlike admins/supervising SLPs they can't hand the record to another provider or SLP -
    # it's pinned to themselves, and the clinic is notified so it gets reviewed.
    ctx.require_role("admin", "supervising_slp", "provider")
    name = (body.get("name") or "").strip()
    school_id = body.get("school_id")
    if not name or not school_id:
        raise bad_request("name and school_id are required")

    if ctx.role == "provider":
        provider_id = ctx.user_id
        supervising_slp_id = ctx.user["supervising_slp_id"]
    else:
        provider_id = body.get("provider_id")
        supervising_slp_id = body.get("supervising_slp_id") or (ctx.user_id if ctx.role == "supervising_slp" else None)

    cur = ctx.db.execute(
        "INSERT INTO students (student_ext_id,name,school_id,grade,disability,eligibility_date,iep_date,"
        "service_start,service_end,provider_id,supervising_slp_id,sessions_per_week,duration_minutes,"
        "group_individual,status,comments,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.get("student_ext_id"), name, school_id, body.get("grade"), body.get("disability"),
         body.get("eligibility_date"), body.get("iep_date"), body.get("service_start"), body.get("service_end"),
         provider_id, supervising_slp_id,
         body.get("sessions_per_week", 1), body.get("duration_minutes", 30),
         body.get("group_individual", "individual"), body.get("status", "active"), body.get("comments"),
         now_iso()),
    )
    sid = cur.lastrowid
    log(ctx.db, ctx.user_id, "student_created", "student", sid, {"name": name, "added_by_role": ctx.role})
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()

    if ctx.role == "provider":
        from .routes_alerts import _deliver, initials
        school = ctx.db.execute("SELECT name FROM schools WHERE id=?", (school_id,)).fetchone()
        recipients = [r["id"] for r in ctx.db.execute("SELECT id FROM users WHERE role='admin' AND is_active=1").fetchall()]
        if supervising_slp_id:
            recipients.append(supervising_slp_id)
        for rid in recipients:
            _deliver(
                ctx.db, "attention", f"new_student:{sid}:{rid}", rid,
                f"New student added by {ctx.user['name']}",
                f"{initials(name)} was added at {school['name'] if school else 'a school'} by "
                f"{ctx.user['name']} and may need review.",
            )
        ctx.db.commit()

    return 201, {"student": student_public(row)}


@router.get("/api/students/<id>")
def get_student(ctx, params, body):
    row = ctx.db.execute("SELECT * FROM students WHERE id=?", (params["id"],)).fetchone()
    if not row or not student_visible_to(ctx, row):
        raise not_found()
    qs = params.get("_qs", {})
    today = datetime.date.today()
    year = int(qs.get("year", today.year))
    months_view = []
    for m in range(1, 13):
        std, prorated, active_days, dim, is_p = comp.prorated_target(
            row["sessions_per_week"], row["service_start"], row["service_end"], year, m
        )
        override = ctx.db.execute(
            "SELECT adjusted_target, reason FROM target_adjustments WHERE student_id=? AND year_month=?",
            (row["id"], f"{year:04d}-{m:02d}"),
        ).fetchone()
        target = override["adjusted_target"] if override else prorated
        month_prefix = f"{year:04d}-{m:02d}"
        att_rows = ctx.db.execute(
            "SELECT a.result FROM attendance a JOIN sessions_sched s ON a.session_id=s.id "
            "WHERE a.student_id=? AND substr(s.session_date,1,7)=?",
            (row["id"], month_prefix),
        ).fetchall()
        completed = sum(1 for a in att_rows if comp.counts_toward_completed(a["result"]))
        excused = sum(1 for a in att_rows if comp.is_school_controlled(a["result"]))
        makeup_needed = sum(1 for a in att_rows if comp.requires_makeup(a["result"]))
        cancelled = sum(1 for a in att_rows if a["result"] in ("provider_absent", "provider_cancelled"))
        sched_rows = ctx.db.execute(
            "SELECT s.status FROM sessions_sched s JOIN session_students ss ON ss.session_id=s.id "
            "WHERE ss.student_id=? AND substr(s.session_date,1,7)=?",
            (row["id"], month_prefix),
        ).fetchall()
        scheduled = sum(1 for s in sched_rows if s["status"] in ("scheduled", "awaiting_approval"))
        makeup_scheduled = sum(1 for s in sched_rows if s["status"] == "makeup_scheduled")
        remaining = max(0, target - completed)
        pct = round(100 * completed / target, 1) if target > 0 else 100.0
        is_current_month = (year, m) == (today.year, today.month)
        is_future_month = (year, m) > (today.year, today.month)
        if is_future_month:
            status = "not_yet_due"
        elif is_current_month:
            elapsed = comp.elapsed_active_days(row["service_start"], row["service_end"], year, m)
            status = comp.pace_status(completed, target, active_days, elapsed)
        else:
            status = comp.compliance_status(completed, target)
        months_view.append({
            "month": month_prefix, "standard_target": std, "target": target, "is_prorated": is_p,
            "active_days": active_days, "days_in_month": dim,
            "scheduled": scheduled, "completed": completed, "excused": excused,
            "cancelled_by_provider": cancelled, "makeup_needed": makeup_needed,
            "makeup_scheduled": makeup_scheduled, "remaining": remaining, "compliance_pct": pct,
            "status": status,
        })
    transfers = ctx.db.execute(
        "SELECT * FROM student_transfers WHERE student_id=? ORDER BY effective_date DESC", (row["id"],)
    ).fetchall()
    upcoming = ctx.db.execute(
        "SELECT s.session_date, s.start_time, s.duration_minutes, s.status, s.id "
        "FROM sessions_sched s JOIN session_students ss ON ss.session_id=s.id "
        "WHERE ss.student_id=? AND s.session_date>=? ORDER BY s.session_date, s.start_time LIMIT 20",
        (row["id"], today.isoformat()),
    ).fetchall()
    return 200, {
        "student": student_public(row),
        "months": months_view,
        "transfers": [dict(t) for t in transfers],
        "upcoming_sessions": [dict(u) for u in upcoming],
    }


@router.patch("/api/students/<id>")
def update_student(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    sid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not row or not student_visible_to(ctx, row):
        raise not_found()
    fields = ["student_ext_id", "name", "school_id", "grade", "disability", "eligibility_date", "iep_date",
              "service_start", "service_end", "sessions_per_week", "duration_minutes",
              "group_individual", "status", "comments"]
    updates, values = [], []
    for f in fields:
        if f in body:
            updates.append(f"{f}=?")
            values.append(body[f])
    if updates:
        # Saving the record counts as "reviewed" - clear any "needs review" note left by a
        # roster import, whether or not this particular save touched the field it flagged.
        updates.append("import_flags=NULL")
        values.append(sid)
        ctx.db.execute(f"UPDATE students SET {', '.join(updates)} WHERE id=?", values)
        log(ctx.db, ctx.user_id, "student_updated", "student", sid, body)
        ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    return 200, {"student": student_public(row)}


def _transfer_one_student(ctx, row, to_provider_id, to_school_id, effective_date, reason):
    """Shared by the single-student transfer endpoint and bulk caseload transfer below."""
    sid = row["id"]
    ctx.db.execute(
        "INSERT INTO student_transfers (student_id,from_provider_id,to_provider_id,from_school_id,to_school_id,"
        "effective_date,reason,requested_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, row["provider_id"], to_provider_id, row["school_id"], to_school_id, effective_date, reason,
         ctx.user_id, now_iso()),
    )
    # Future sessions under the old assignment enter a review state.
    future = ctx.db.execute(
        "SELECT s.id FROM sessions_sched s JOIN session_students ss ON ss.session_id=s.id "
        "WHERE ss.student_id=? AND s.session_date>=? AND s.status='scheduled'",
        (sid, effective_date),
    ).fetchall()
    for f in future:
        ctx.db.execute("UPDATE sessions_sched SET status='awaiting_approval' WHERE id=?", (f["id"],))
        ctx.db.execute(
            "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
            "requested_by, status, created_at) VALUES ('transfer','sessions_sched',?,?,?,?,?,?,?)",
            (f["id"], json.dumps({"provider_id": row["provider_id"], "school_id": row["school_id"]}),
             json.dumps({"provider_id": to_provider_id, "school_id": to_school_id}),
             f"Student transfer: {reason}", ctx.user_id, "pending", now_iso()),
        )
    if to_provider_id:
        ctx.db.execute("UPDATE students SET provider_id=? WHERE id=?", (to_provider_id, sid))
    if to_school_id:
        ctx.db.execute("UPDATE students SET school_id=? WHERE id=?", (to_school_id, sid))
    log(ctx.db, ctx.user_id, "student_transferred", "student", sid,
        {"to_provider_id": to_provider_id, "to_school_id": to_school_id, "reason": reason})
    return len(future)


@router.post("/api/students/<id>/transfer")
def transfer_student(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    sid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not row:
        raise not_found()
    effective_date = body.get("effective_date") or now_iso()[:10]
    to_provider_id = body.get("to_provider_id")
    to_school_id = body.get("to_school_id")
    reason = body.get("reason") or ""
    future_count = _transfer_one_student(ctx, row, to_provider_id, to_school_id, effective_date, reason)
    ctx.db.commit()
    return 200, {"ok": True, "future_sessions_needing_review": future_count}


@router.post("/api/users/<id>/bulk-transfer-caseload")
def bulk_transfer_caseload(ctx, params, body):
    """Reassign a departing provider's entire active caseload to another provider in one action,
    instead of transferring students one at a time (e.g. when a provider leaves mid-year)."""
    ctx.require_role("admin", "supervising_slp")
    from_provider_id = int(params["id"])
    to_provider_id = body.get("to_provider_id")
    if not to_provider_id:
        raise bad_request("to_provider_id is required")
    to_provider_id = int(to_provider_id)
    if to_provider_id == from_provider_id:
        raise bad_request("Choose a different provider to receive the caseload")
    to_row = ctx.db.execute("SELECT * FROM users WHERE id=? AND role='provider'", (to_provider_id,)).fetchone()
    if not to_row:
        raise not_found("Receiving provider not found")
    effective_date = body.get("effective_date") or now_iso()[:10]
    reason = body.get("reason") or "Bulk caseload transfer"

    students = ctx.db.execute(
        "SELECT * FROM students WHERE provider_id=? AND status='active'", (from_provider_id,)
    ).fetchall()
    total_future = 0
    for row in students:
        total_future += _transfer_one_student(ctx, row, to_provider_id, row["school_id"], effective_date, reason)
    log(ctx.db, ctx.user_id, "provider_caseload_bulk_transferred", "user", from_provider_id,
        {"to_provider_id": to_provider_id, "students_moved": len(students), "reason": reason})
    ctx.db.commit()
    return 200, {
        "ok": True,
        "students_moved": len(students),
        "future_sessions_needing_review": total_future,
    }


@router.post("/api/students/<id>/merge")
def merge_students(ctx, params, body):
    """Merge a duplicate student record into this one (the survivor). Moves attendance,
    schedule, makeup, and transfer history over, then archives the duplicate instead of
    deleting it, so nothing is lost if the merge needs to be reviewed later."""
    ctx.require_role("admin", "supervising_slp")
    primary_id = int(params["id"])
    dup_id = body.get("duplicate_student_id")
    if not dup_id:
        raise bad_request("duplicate_student_id is required")
    dup_id = int(dup_id)
    if dup_id == primary_id:
        raise bad_request("Can't merge a student into itself")

    primary = ctx.db.execute("SELECT * FROM students WHERE id=?", (primary_id,)).fetchone()
    dup = ctx.db.execute("SELECT * FROM students WHERE id=?", (dup_id,)).fetchone()
    if not primary or not dup:
        raise not_found("Student not found")
    reason = body.get("reason") or ""

    # session_students: move the duplicate's sessions over, unless the survivor is already
    # in that same session (e.g. both records got scheduled into the same group by mistake),
    # in which case just drop the duplicate row rather than creating a second entry.
    moved_sessions = 0
    dropped_sessions = 0
    for r in ctx.db.execute("SELECT * FROM session_students WHERE student_id=?", (dup_id,)).fetchall():
        exists = ctx.db.execute(
            "SELECT id FROM session_students WHERE session_id=? AND student_id=?", (r["session_id"], primary_id)
        ).fetchone()
        if exists:
            ctx.db.execute("DELETE FROM session_students WHERE id=?", (r["id"],))
            dropped_sessions += 1
        else:
            ctx.db.execute("UPDATE session_students SET student_id=? WHERE id=?", (primary_id, r["id"]))
            moved_sessions += 1

    # attendance: same idea - a real UNIQUE(session_id, student_id) constraint means we must
    # resolve conflicts. The survivor's existing record wins; the duplicate's is dropped.
    moved_attendance = 0
    dropped_attendance = 0
    for r in ctx.db.execute("SELECT * FROM attendance WHERE student_id=?", (dup_id,)).fetchall():
        exists = ctx.db.execute(
            "SELECT id FROM attendance WHERE session_id=? AND student_id=?", (r["session_id"], primary_id)
        ).fetchone()
        if exists:
            ctx.db.execute("DELETE FROM attendance WHERE id=?", (r["id"],))
            dropped_attendance += 1
        else:
            ctx.db.execute("UPDATE attendance SET student_id=? WHERE id=?", (primary_id, r["id"]))
            moved_attendance += 1

    # makeup_queue and student_transfers have no uniqueness constraint on student_id - safe
    # to move wholesale, they're just history.
    ctx.db.execute("UPDATE makeup_queue SET student_id=? WHERE student_id=?", (primary_id, dup_id))
    ctx.db.execute("UPDATE student_transfers SET student_id=? WHERE student_id=?", (primary_id, dup_id))
    ctx.db.execute("UPDATE recurring_schedules SET student_id=? WHERE student_id=?", (primary_id, dup_id))

    # target_adjustments: UNIQUE(student_id, year_month) - survivor's override wins on conflict.
    moved_targets = 0
    for r in ctx.db.execute("SELECT * FROM target_adjustments WHERE student_id=?", (dup_id,)).fetchall():
        exists = ctx.db.execute(
            "SELECT id FROM target_adjustments WHERE student_id=? AND year_month=?", (primary_id, r["year_month"])
        ).fetchone()
        if exists:
            ctx.db.execute("DELETE FROM target_adjustments WHERE id=?", (r["id"],))
        else:
            ctx.db.execute("UPDATE target_adjustments SET student_id=? WHERE id=?", (primary_id, r["id"]))
            moved_targets += 1

    merge_note = f"Merged into student #{primary_id} ({primary['name']}) on {now_iso()[:10]} by {ctx.user['name']}."
    if reason:
        merge_note += f" Reason: {reason}"
    new_comments = f"{dup['comments']}\n{merge_note}" if dup["comments"] else merge_note
    ctx.db.execute("UPDATE students SET status='archived', comments=? WHERE id=?", (new_comments, dup_id))

    log(ctx.db, ctx.user_id, "students_merged", "student", primary_id, {
        "duplicate_student_id": dup_id, "moved_sessions": moved_sessions, "dropped_sessions": dropped_sessions,
        "moved_attendance": moved_attendance, "dropped_attendance": dropped_attendance, "reason": reason,
    })
    ctx.db.commit()
    return 200, {
        "ok": True,
        "moved_sessions": moved_sessions, "dropped_duplicate_sessions": dropped_sessions,
        "moved_attendance": moved_attendance, "dropped_duplicate_attendance": dropped_attendance,
        "moved_target_adjustments": moved_targets,
    }


# ---------------------------------------------------------- temp coverage --

@router.get("/api/coverage")
def list_coverage(ctx, params, body):
    if ctx.role == "provider":
        rows = ctx.db.execute(
            "SELECT * FROM temporary_coverage WHERE covering_provider_id=? OR original_provider_id=? "
            "ORDER BY start_date DESC", (ctx.user_id, ctx.user_id),
        ).fetchall()
    else:
        rows = ctx.db.execute("SELECT * FROM temporary_coverage ORDER BY start_date DESC").fetchall()
    return 200, {"coverage": [dict(r) for r in rows]}


@router.post("/api/coverage")
def create_coverage(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    required = ["covering_provider_id", "original_provider_id", "start_date", "end_date", "reason"]
    for f in required:
        if not body.get(f):
            raise bad_request(f"{f} is required")
    cur = ctx.db.execute(
        "INSERT INTO temporary_coverage (covering_provider_id, original_provider_id, start_date, end_date, "
        "reason, authorized_by, created_at) VALUES (?,?,?,?,?,?,?)",
        (body["covering_provider_id"], body["original_provider_id"], body["start_date"], body["end_date"],
         body["reason"], ctx.user_id, now_iso()),
    )
    log(ctx.db, ctx.user_id, "coverage_granted", "temporary_coverage", cur.lastrowid, body)
    ctx.db.commit()
    return 201, {"id": cur.lastrowid}
