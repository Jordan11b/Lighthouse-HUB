import datetime
from .router import Router
from .db import now_iso
from .errors import forbidden, bad_request
from . import compliance as comp
from .pdf_writer import build_table_pdf
from . import mailer

router = Router()


@router.get("/api/audit")
def list_audit(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    qs = params.get("_qs", {})
    q = "SELECT al.*, u.name as actor_name FROM audit_log al LEFT JOIN users u ON u.id=al.actor_id WHERE 1=1"
    args = []
    if qs.get("entity_type"):
        q += " AND al.entity_type=?"
        args.append(qs["entity_type"])
    if qs.get("entity_id"):
        q += " AND al.entity_id=?"
        args.append(qs["entity_id"])
    q += " ORDER BY al.id DESC LIMIT 300"
    rows = ctx.db.execute(q, args).fetchall()
    return 200, {"audit_log": [dict(r) for r in rows]}


@router.get("/api/reports/compliance")
def compliance_report(ctx, params, body):
    qs = params.get("_qs", {})
    now = datetime.date.today()
    year = int(qs.get("year", now.year))
    month = int(qs.get("month", now.month))
    from .routes_people import student_visible_to
    students = ctx.db.execute("SELECT * FROM students WHERE status='active' ORDER BY name").fetchall()
    students = [s for s in students if student_visible_to(ctx, s)]
    if qs.get("school_id"):
        students = [s for s in students if str(s["school_id"]) == str(qs["school_id"])]

    out = []
    for s in students:
        std, prorated, active_days, dim, is_p = comp.prorated_target(
            s["sessions_per_week"], s["service_start"], s["service_end"], year, month
        )
        month_prefix = f"{year:04d}-{month:02d}"
        completed = ctx.db.execute(
            "SELECT COUNT(*) c FROM attendance a JOIN sessions_sched sc ON a.session_id=sc.id "
            "WHERE a.student_id=? AND substr(sc.session_date,1,7)=? AND a.result='completed'",
            (s["id"], month_prefix),
        ).fetchone()["c"]
        provider = ctx.db.execute("SELECT name FROM users WHERE id=?", (s["provider_id"],)).fetchone()
        school = ctx.db.execute("SELECT name FROM schools WHERE id=?", (s["school_id"],)).fetchone()
        is_current = (year, month) == (now.year, now.month)
        if is_current:
            elapsed = comp.elapsed_active_days(s["service_start"], s["service_end"], year, month)
            status = comp.pace_status(completed, prorated, active_days, elapsed)
        else:
            status = comp.compliance_status(completed, prorated)
        out.append({
            "student_id": s["id"], "student_name": s["name"],
            "school_name": school["name"] if school else None,
            "provider_name": provider["name"] if provider else None,
            "target": prorated, "completed": completed,
            "compliance_pct": round(100 * completed / prorated, 1) if prorated else 100.0,
            "status": status,
        })
    return 200, {"month": f"{year:04d}-{month:02d}", "rows": out}


@router.get("/api/reports/compliance.pdf")
def compliance_report_pdf(ctx, params, body):
    qs = params.get("_qs", {})
    now = datetime.date.today()
    year = int(qs.get("year", now.year))
    month = int(qs.get("month", now.month))
    status, payload = compliance_report(ctx, params, body)
    rows = payload["rows"]
    headers = ["Student", "School", "Provider", "Target", "Completed", "% of target", "Status"]
    col_widths = [130, 110, 110, 50, 70, 70, 60]
    table_rows = [
        [r["student_name"], r["school_name"] or "-", r["provider_name"] or "-", r["target"],
         r["completed"], f"{r['compliance_pct']}%", r["status"].replace("_", " ")]
        for r in rows
    ]
    subtitle = f"{payload['month']} - Lighthouse Therapy Hub"
    pdf_bytes = build_table_pdf("Monthly Service Compliance", subtitle, headers, table_rows, col_widths)
    return 200, {
        "__binary__": pdf_bytes, "__content_type__": "application/pdf",
        "__filename__": f"compliance-{payload['month']}.pdf",
    }


@router.get("/api/settings")
def get_settings(ctx, params, body):
    rows = ctx.db.execute("SELECT * FROM settings").fetchall()
    out = {r["key"]: r["value"] for r in rows}
    # Never hand the real SMTP password back to the browser - show a mask if one is saved,
    # blank if not. update_settings below treats the mask as "leave it alone".
    if out.get("smtp_password"):
        out["smtp_password"] = mailer.MASKED_VALUE
    return 200, {"settings": out, "env_overridden": mailer.env_overridden_keys(),
                 "email_configured": mailer.is_configured(ctx.db)}


@router.post("/api/settings")
def update_settings(ctx, params, body):
    ctx.require_role("admin")
    for k, v in body.items():
        if k in mailer.SENSITIVE_SETTINGS and v == mailer.MASKED_VALUE:
            continue  # unchanged - the browser just echoed the mask back
        ctx.db.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, str(v)),
        )
    ctx.db.commit()
    return 200, {"ok": True}


@router.post("/api/settings/test-email")
def test_email(ctx, params, body):
    """Send a real test email to the requesting admin's own notification address, so they
    can confirm SMTP settings actually work from inside the app instead of guessing from
    server logs."""
    ctx.require_role("admin")
    if not mailer.is_configured(ctx.db):
        raise bad_request("Email isn't configured yet - fill in the SMTP fields (or set the SMTP_* "
                           "environment variables) and save first.")
    to_addr = mailer.notify_address(ctx.user)
    if not to_addr:
        raise bad_request("Your account doesn't have an email address on file.")
    sent = mailer.send_email(
        ctx.db, to_addr, "Lighthouse Therapy Hub test email",
        f"This is a test email from Lighthouse Therapy Hub, sent {now_iso()}. "
        f"If you got this, outbound email is working.",
    )
    if not sent:
        raise bad_request("Couldn't send - check the SMTP host/port/username/password and try again. "
                           "See the server console for the specific error.")
    return 200, {"ok": True, "sent_to": to_addr}
