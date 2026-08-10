"""In-app alerts (urgent / attention / informational) plus an email outbox that mirrors
what the spec's timing rules would send.

If SMTP is configured (see lighthouse/mailer.py - environment variables or the
Administration screen), `_deliver()` actually sends the email to the recipient's
notification address. If it isn't configured, or the send fails, it falls back to writing
to the notification_log table and printing to the server console instead, so nothing here
requires email to be set up to keep working.
"""
import datetime
import json
from .router import Router
from .db import now_iso
from .errors import forbidden
from . import compliance as comp
from .mailer import send_email, notify_address

router = Router()


def initials(name):
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0].upper() for p in parts[:3]) or "?"


def _deliver(db, category, dedupe_key, recipient_user_id, subject, body):
    """Send (or simulate) an outbound email to a user, deduped by dedupe_key so timing
    rules with re-run checks don't spam the same notification twice."""
    existing = db.execute("SELECT id FROM notification_log WHERE dedupe_key=?", (dedupe_key,)).fetchone()
    if existing:
        return False
    db.execute(
        "INSERT INTO notification_log (category, dedupe_key, recipient_user_id, subject, body, sent_at) "
        "VALUES (?,?,?,?,?,?)",
        (category, dedupe_key, recipient_user_id, subject, body, now_iso()),
    )
    user = db.execute("SELECT * FROM users WHERE id=?", (recipient_user_id,)).fetchone()
    to_addr = notify_address(user)
    sent = send_email(db, to_addr, subject, body) if to_addr else False
    if sent:
        print(f"[email sent] to {to_addr}: {subject}", flush=True)
    else:
        print(f"[simulated email] to user #{recipient_user_id} ({to_addr or 'no address on file'}): {subject} — {body}", flush=True)
    return True


def compute_live_alerts(db):
    today = datetime.date.today()
    urgent, attention, informational = [], [], []

    # Urgent: expired IEP / eligibility dates, unresolved conflict overrides, data problems.
    expired = db.execute(
        "SELECT id, name, iep_date, eligibility_date FROM students WHERE status='active' AND "
        "((iep_date IS NOT NULL AND iep_date < ?) OR (eligibility_date IS NOT NULL AND eligibility_date < ?))",
        (today.isoformat(), today.isoformat()),
    ).fetchall()
    for s in expired:
        urgent.append({
            "type": "expired_iep_eligibility", "student_id": s["id"],
            "message": f"{s['name']}: IEP/eligibility date has passed and needs review.",
        })

    conflicts = db.execute(
        "SELECT id, session_date, provider_id FROM sessions_sched WHERE status='awaiting_approval'"
    ).fetchall()
    for c in conflicts:
        urgent.append({
            "type": "conflict_pending", "session_id": c["id"],
            "message": f"Scheduling conflict on {c['session_date']} is awaiting an approval decision.",
        })

    orphan_students = db.execute("SELECT id, name FROM students WHERE status='active' AND provider_id IS NULL").fetchall()
    for s in orphan_students:
        urgent.append({"type": "data_problem", "student_id": s["id"], "message": f"{s['name']} has no assigned provider."})

    # Attention: students behind pace, unresolved makeups, pending approvals.
    students = db.execute("SELECT * FROM students WHERE status='active'").fetchall()
    year, month = today.year, today.month
    for s in students:
        std, target, active_days, dim, is_p = comp.prorated_target(s["sessions_per_week"], s["service_start"], s["service_end"], year, month)
        month_prefix = f"{year:04d}-{month:02d}"
        completed = db.execute(
            "SELECT COUNT(*) c FROM attendance a JOIN sessions_sched sc ON a.session_id=sc.id "
            "WHERE a.student_id=? AND substr(sc.session_date,1,7)=? AND a.result='completed'",
            (s["id"], month_prefix),
        ).fetchone()["c"]
        elapsed = comp.elapsed_active_days(s["service_start"], s["service_end"], year, month)
        status = comp.pace_status(completed, target, active_days, elapsed)
        if status == "behind":
            attention.append({"type": "behind_pace", "student_id": s["id"], "message": f"{s['name']} is behind pace this month ({completed}/{target})."})

    makeups = db.execute("SELECT * FROM makeup_queue WHERE status='open'").fetchall()
    for m in makeups:
        age = (today - datetime.date.fromisoformat(m["missed_date"])).days
        attention.append({"type": "unresolved_makeup", "makeup_id": m["id"], "message": f"Makeup owed since {m['missed_date']} ({age} days)."})

    approvals = db.execute("SELECT * FROM approvals WHERE status='pending'").fetchall()
    for a in approvals:
        attention.append({"type": "pending_approval", "approval_id": a["id"], "message": f"{a['type'].replace('_',' ').title()} awaiting a decision."})

    horizon = (today + datetime.timedelta(days=90)).isoformat()
    upcoming = db.execute(
        "SELECT id, name, iep_date, eligibility_date FROM students WHERE status='active' AND "
        "((iep_date IS NOT NULL AND iep_date BETWEEN ? AND ?) OR (eligibility_date IS NOT NULL AND eligibility_date BETWEEN ? AND ?))",
        (today.isoformat(), horizon, today.isoformat(), horizon),
    ).fetchall()
    for s in upcoming:
        attention.append({"type": "upcoming_iep", "student_id": s["id"], "message": f"{s['name']}: IEP/eligibility date coming up ({s['iep_date'] or s['eligibility_date']})."})

    lic_horizon = (today + datetime.timedelta(days=90)).isoformat()
    providers = db.execute(
        "SELECT id, name, license_expiration FROM users WHERE role='provider' AND is_active=1 AND "
        "license_expiration IS NOT NULL AND license_expiration BETWEEN ? AND ?",
        (today.isoformat(), lic_horizon),
    ).fetchall()
    for p in providers:
        attention.append({"type": "license_expiring", "provider_id": p["id"], "message": f"{p['name']}'s license expires {p['license_expiration']}."})

    recent_cutoff = (today - datetime.timedelta(days=7)).isoformat()
    provider_added = db.execute(
        "SELECT al.entity_id AS student_id, al.created_at, u.name AS added_by "
        "FROM audit_log al JOIN users u ON u.id=al.actor_id "
        "WHERE al.action='student_created' AND u.role='provider' AND al.created_at >= ? "
        "ORDER BY al.created_at DESC",
        (recent_cutoff,),
    ).fetchall()
    for a in provider_added:
        s = db.execute("SELECT id, name FROM students WHERE id=?", (a["student_id"],)).fetchone()
        if s:
            attention.append({
                "type": "provider_added_student", "student_id": s["id"],
                "message": f"{s['name']} was added by {a['added_by']} — needs review.",
            })

    # Informational: recent approval decisions, recent imports.
    recent_decisions = db.execute(
        "SELECT * FROM approvals WHERE status!='pending' AND decided_at >= ? ORDER BY decided_at DESC LIMIT 15",
        ((today - datetime.timedelta(days=2)).isoformat(),),
    ).fetchall()
    for a in recent_decisions:
        informational.append({"type": "approval_decided", "approval_id": a["id"], "message": f"{a['type'].replace('_',' ').title()} was {a['status']}."})

    recent_imports = db.execute("SELECT * FROM import_batches ORDER BY created_at DESC LIMIT 10").fetchall()
    for i in recent_imports:
        informational.append({"type": "import", "import_id": i["id"], "message": f"Roster import '{i['filename'] or 'upload'}' is {i['status']} ({i['row_count']} rows)."})

    return {"urgent": urgent, "attention": attention, "informational": informational}


@router.get("/api/alerts")
def get_alerts(ctx, params, body):
    data = compute_live_alerts(ctx.db)
    if ctx.role == "provider":
        visible = set(ctx.visible_provider_ids())
        def keep(item):
            if "student_id" in item:
                row = ctx.db.execute("SELECT provider_id FROM students WHERE id=?", (item["student_id"],)).fetchone()
                return row and row["provider_id"] in visible
            if "provider_id" in item:
                return item["provider_id"] in visible
            return True
        data = {k: [i for i in v if keep(i)] for k, v in data.items()}
    return 200, data


@router.get("/api/alerts/log")
def get_alert_log(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    rows = ctx.db.execute("SELECT * FROM notification_log ORDER BY sent_at DESC LIMIT 200").fetchall()
    return 200, {"log": [dict(r) for r in rows]}


@router.post("/api/alerts/run-check")
def run_check(ctx, params, body):
    ctx.require_role("admin")
    today = datetime.date.today()
    sent = 0
    windows = (90, 60, 30, 14)

    students = ctx.db.execute("SELECT * FROM students WHERE status='active'").fetchall()
    for s in students:
        for field in ("iep_date", "eligibility_date"):
            d = s[field]
            if not d:
                continue
            days_out = (datetime.date.fromisoformat(d) - today).days
            if days_out in windows:
                recipients = [rid for rid in (s["provider_id"], s["supervising_slp_id"]) if rid]
                for rid in recipients:
                    key = f"{field}:{s['id']}:{days_out}"
                    if _deliver(ctx.db, "attention", key, rid,
                                f"{initials(s['name'])} — {field.replace('_',' ')} in {days_out} days",
                                f"Student {initials(s['name'])}'s {field.replace('_',' ')} is {days_out} days away. No diagnosis or record details included."):
                        sent += 1

    providers = ctx.db.execute("SELECT * FROM users WHERE role='provider' AND is_active=1 AND license_expiration IS NOT NULL").fetchall()
    admins = ctx.db.execute("SELECT id FROM users WHERE role='admin' AND is_active=1").fetchall()
    for p in providers:
        days_out = (datetime.date.fromisoformat(p["license_expiration"]) - today).days
        if days_out in (90, 60, 30):
            for rid in [p["id"]] + [a["id"] for a in admins]:
                key = f"license:{p['id']}:{days_out}"
                if _deliver(ctx.db, "attention", key, rid, f"License expiring in {days_out} days",
                            f"{p['name']}'s license expires in {days_out} days."):
                    sent += 1

    iso_year, iso_week, _ = today.isocalendar()
    week_key = f"{iso_year}-W{iso_week}"
    makeups = ctx.db.execute("SELECT * FROM makeup_queue WHERE status='open'").fetchall()
    for m in makeups:
        recipients = [rid for rid in (m["responsible_provider_id"],) if rid] + [a["id"] for a in admins]
        for rid in recipients:
            key = f"makeup_weekly:{m['id']}:{week_key}"
            if _deliver(ctx.db, "attention", key, rid, "Unresolved makeup", f"Makeup for {initials((ctx.db.execute('SELECT name FROM students WHERE id=?',(m['student_id'],)).fetchone() or {'name':''})['name'])} is still open."):
                sent += 1

    year, month = today.year, today.month
    for s in students:
        std, target, active_days, dim, is_p = comp.prorated_target(s["sessions_per_week"], s["service_start"], s["service_end"], year, month)
        month_prefix = f"{year:04d}-{month:02d}"
        completed = ctx.db.execute(
            "SELECT COUNT(*) c FROM attendance a JOIN sessions_sched sc ON a.session_id=sc.id "
            "WHERE a.student_id=? AND substr(sc.session_date,1,7)=? AND a.result='completed'",
            (s["id"], month_prefix),
        ).fetchone()["c"]
        elapsed = comp.elapsed_active_days(s["service_start"], s["service_end"], year, month)
        status = comp.pace_status(completed, target, active_days, elapsed)
        if status in ("behind", "at_risk") and s["provider_id"]:
            key = f"pace_weekly:{s['id']}:{week_key}"
            if _deliver(ctx.db, "attention", key, s["provider_id"], f"{initials(s['name'])} behind pace",
                        f"{initials(s['name'])} is {status.replace('_',' ')} this month ({completed}/{target})."):
                sent += 1

    ctx.db.commit()
    return 200, {"notifications_sent": sent}
