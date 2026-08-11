import json
import datetime
from .router import Router
from .db import now_iso
from .errors import bad_request, forbidden, not_found
from .audit import log
from .routes_schedule import _create_session_row, _has_conflict, session_public

router = Router()


def makeup_public(row, ctx):
    d = dict(row)
    missed = datetime.date.fromisoformat(row["missed_date"])
    d["age_days"] = (datetime.date.today() - missed).days
    student = ctx.db.execute("SELECT name FROM students WHERE id=?", (row["student_id"],)).fetchone()
    school = ctx.db.execute("SELECT name FROM schools WHERE id=?", (row["school_id"],)).fetchone()
    responsible = ctx.db.execute("SELECT name FROM users WHERE id=?", (row["responsible_provider_id"],)).fetchone()
    d["student_name"] = student["name"] if student else None
    d["school_name"] = school["name"] if school else None
    d["responsible_provider_name"] = responsible["name"] if responsible else None
    return d


@router.get("/api/makeups")
def list_makeups(ctx, params, body):
    qs = params.get("_qs", {})
    q = "SELECT * FROM makeup_queue WHERE 1=1"
    args = []
    if qs.get("status"):
        q += " AND status=?"
        args.append(qs["status"])
    if ctx.role == "provider":
        visible = ctx.visible_provider_ids()
        if not visible:
            return 200, {"makeups": []}
        q += f" AND responsible_provider_id IN ({','.join('?' * len(visible))})"
        args += visible
    q += " ORDER BY missed_date"
    rows = ctx.db.execute(q, args).fetchall()
    return 200, {"makeups": [makeup_public(r, ctx) for r in rows]}


@router.patch("/api/makeups/<id>")
def reassign_makeup(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    mid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM makeup_queue WHERE id=?", (mid,)).fetchone()
    if not row:
        raise not_found()
    fields = ["responsible_provider_id", "proposed_makeup_date"]
    updates, values = [], []
    for f in fields:
        if f in body:
            updates.append(f"{f}=?")
            values.append(body[f])
    if updates:
        values.append(mid)
        ctx.db.execute(f"UPDATE makeup_queue SET {', '.join(updates)} WHERE id=?", values)
        log(ctx.db, ctx.user_id, "makeup_reassigned", "makeup_queue", mid, body)
        ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM makeup_queue WHERE id=?", (mid,)).fetchone()
    return 200, {"makeup": makeup_public(row, ctx)}


@router.post("/api/makeups/<id>/schedule")
def schedule_makeup(ctx, params, body):
    mid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM makeup_queue WHERE id=?", (mid,)).fetchone()
    if not row:
        raise not_found()
    if ctx.role == "provider" and row["responsible_provider_id"] not in ctx.visible_provider_ids():
        raise forbidden()
    date = body.get("date")
    start_time = body.get("start_time")
    duration = int(body.get("duration_minutes", 30))
    if not date or not start_time:
        raise bad_request("date and start_time are required")
    if _has_conflict(ctx.db, row["responsible_provider_id"], date, start_time, duration):
        raise bad_request("That time conflicts with another appointment for this provider")
    school_id = row["school_id"]
    session_id = _create_session_row(
        ctx.db, row["responsible_provider_id"], school_id, date, start_time, duration, "individual",
        [row["student_id"]], "makeup_scheduled", ctx.user_id,
    )
    ctx.db.execute(
        "UPDATE makeup_queue SET status='scheduled', proposed_makeup_date=? WHERE id=?", (date, mid)
    )
    ctx.db.execute("UPDATE makeup_queue SET completed_session_id=? WHERE id=?", (session_id, mid))
    log(ctx.db, ctx.user_id, "makeup_scheduled", "makeup_queue", mid, {"session_id": session_id})
    ctx.db.commit()
    srow = ctx.db.execute("SELECT * FROM sessions_sched WHERE id=?", (session_id,)).fetchone()
    return 201, {"session": session_public(ctx.db, srow)}


@router.post("/api/makeups/<id>/exception")
def request_makeup_exception(ctx, params, body):
    mid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM makeup_queue WHERE id=?", (mid,)).fetchone()
    if not row:
        raise not_found()
    reason = body.get("reason")
    if not reason:
        raise bad_request("reason is required")
    ctx.db.execute(
        "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
        "requested_by, status, created_at) VALUES ('makeup_exception','makeup_queue',?,?,?,?,?,?,?)",
        (mid, json.dumps({"status": row["status"]}), json.dumps({"status": "excused_exception"}), reason,
         ctx.user_id, "pending", now_iso()),
    )
    log(ctx.db, ctx.user_id, "makeup_exception_requested", "makeup_queue", mid, {"reason": reason})
    ctx.db.commit()
    return 201, {"ok": True}
