import json
import datetime
from .router import Router
from .db import now_iso
from .errors import bad_request, forbidden, not_found
from .audit import log
from .routes_schedule import generate_sessions_for_recurring, _has_conflict

router = Router()


def approval_public(row, ctx):
    d = dict(row)
    requester = ctx.db.execute("SELECT name FROM users WHERE id=?", (row["requested_by"],)).fetchone()
    d["requested_by_name"] = requester["name"] if requester else None
    for f in ("original_info", "proposed_change"):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except (TypeError, ValueError):
                pass
    return d


@router.get("/api/approvals")
def list_approvals(ctx, params, body):
    qs = params.get("_qs", {})
    status = qs.get("status", "pending")
    q = "SELECT * FROM approvals WHERE 1=1"
    args = []
    if status != "all":
        q += " AND status=?"
        args.append(status)
    if qs.get("mine") == "1":
        q += " AND requested_by=?"
        args.append(ctx.user_id)
    elif ctx.role == "provider":
        q += " AND requested_by=?"
        args.append(ctx.user_id)
    q += " ORDER BY created_at DESC"
    rows = ctx.db.execute(q, args).fetchall()
    return 200, {"approvals": [approval_public(r, ctx) for r in rows]}


def _apply_recurring_schedule(ctx, approval, approve):
    rid = approval["entity_id"]
    if approve:
        ctx.db.execute("UPDATE recurring_schedules SET status='active' WHERE id=?", (rid,))
        row = ctx.db.execute("SELECT * FROM recurring_schedules WHERE id=?", (rid,)).fetchone()
        generate_sessions_for_recurring(ctx.db, row, approval["decided_by"] or approval["requested_by"])
    else:
        ctx.db.execute("UPDATE recurring_schedules SET status='rejected' WHERE id=?", (rid,))


def _apply_cross_week_move(ctx, approval, approve):
    sid = approval["entity_id"]
    proposed = json.loads(approval["proposed_change"])
    if approve:
        if _has_conflict(ctx.db, ctx.db.execute("SELECT provider_id FROM sessions_sched WHERE id=?", (sid,)).fetchone()["provider_id"],
                          proposed["date"], proposed["start_time"],
                          ctx.db.execute("SELECT duration_minutes FROM sessions_sched WHERE id=?", (sid,)).fetchone()["duration_minutes"],
                          exclude_session_id=sid):
            raise bad_request("Cannot approve: the proposed time now conflicts with another appointment")
        ctx.db.execute(
            "UPDATE sessions_sched SET session_date=?, start_time=?, status='scheduled' WHERE id=?",
            (proposed["date"], proposed["start_time"], sid),
        )
    else:
        ctx.db.execute("UPDATE sessions_sched SET status='scheduled' WHERE id=?", (sid,))


def _apply_conflict_override(ctx, approval, approve):
    sid = approval["entity_id"]
    if approve:
        ctx.db.execute(
            "UPDATE sessions_sched SET status='scheduled', conflict_override_reason=? WHERE id=?",
            (approval["reason"], sid),
        )
    else:
        ctx.db.execute("UPDATE sessions_sched SET status='cancelled' WHERE id=?", (sid,))


def _apply_target_adjustment(ctx, approval, approve):
    payload = json.loads(approval["proposed_change"])
    if approve:
        ctx.db.execute(
            "INSERT INTO target_adjustments (student_id, year_month, adjusted_target, reason, created_by, created_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(student_id, year_month) DO UPDATE SET adjusted_target=excluded.adjusted_target, reason=excluded.reason",
            (payload["student_id"], payload["year_month"], payload["adjusted_target"], approval["reason"],
             approval["requested_by"], now_iso()),
        )


def _apply_transfer(ctx, approval, approve):
    sid = approval["entity_id"]
    proposed = json.loads(approval["proposed_change"])
    if approve:
        updates = []
        values = []
        if proposed.get("provider_id"):
            updates.append("provider_id=?")
            values.append(proposed["provider_id"])
        if proposed.get("school_id"):
            updates.append("school_id=?")
            values.append(proposed["school_id"])
        if updates:
            values.append(sid)
            ctx.db.execute(f"UPDATE sessions_sched SET {', '.join(updates)}, status='scheduled' WHERE id=?", values)
        else:
            ctx.db.execute("UPDATE sessions_sched SET status='scheduled' WHERE id=?", (sid,))
    else:
        ctx.db.execute("UPDATE sessions_sched SET status='cancelled' WHERE id=?", (sid,))


def _apply_late_attendance_correction(ctx, approval, approve):
    aid = approval["entity_id"]
    if approve:
        payload = json.loads(approval["proposed_change"])
        old = ctx.db.execute("SELECT * FROM attendance WHERE id=?", (aid,)).fetchone()
        ctx.db.execute(
            "INSERT INTO attendance_corrections (attendance_id, field, old_value, new_value, reason, changed_by, changed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (aid, "result", old["result"], payload.get("result"), approval["reason"], approval["decided_by"], now_iso()),
        )
        ctx.db.execute(
            "UPDATE attendance SET result=?, actual_time=?, actual_duration_minutes=?, admin_comment=? WHERE id=?",
            (payload.get("result"), payload.get("actual_time"), payload.get("actual_duration_minutes"),
             payload.get("admin_comment"), aid),
        )


def _apply_makeup_exception(ctx, approval, approve):
    mid = approval["entity_id"]
    if approve:
        ctx.db.execute("UPDATE makeup_queue SET status='excused_exception' WHERE id=?", (mid,))


APPLIERS = {
    "recurring_schedule": _apply_recurring_schedule,
    "cross_week_move": _apply_cross_week_move,
    "conflict_override": _apply_conflict_override,
    "target_adjustment": _apply_target_adjustment,
    "transfer": _apply_transfer,
    "late_attendance_correction": _apply_late_attendance_correction,
    "makeup_exception": _apply_makeup_exception,
    "emergency_change_review": lambda ctx, approval, approve: None,
}


@router.post("/api/approvals/<id>/decide")
def decide_approval(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    aid = int(params["id"])
    row = ctx.db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
    if not row:
        raise not_found()
    if row["status"] != "pending":
        raise bad_request("This request has already been decided")
    if row["requested_by"] == ctx.user_id:
        raise forbidden("You cannot approve your own request")

    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be 'approve' or 'reject'")
    approve = decision == "approve"

    applier = APPLIERS.get(row["type"])
    if applier:
        applier(ctx, row, approve)

    ctx.db.execute(
        "UPDATE approvals SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
        ("approved" if approve else "rejected", ctx.user_id, now_iso(), body.get("note"), aid),
    )
    log(ctx.db, ctx.user_id, f"approval_{decision}d", "approvals", aid, {"type": row["type"]})
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
    return 200, {"approval": approval_public(row, ctx)}


@router.post("/api/target-adjustments")
def request_target_adjustment(ctx, params, body):
    for f in ("student_id", "year_month", "adjusted_target", "reason"):
        if body.get(f) is None:
            raise bad_request(f"{f} is required")
    ctx.db.execute(
        "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
        "requested_by, status, created_at) VALUES ('target_adjustment','target_adjustments',?,?,?,?,?,?,?)",
        (body["student_id"], None, json.dumps(body), body["reason"], ctx.user_id, "pending", now_iso()),
    )
    log(ctx.db, ctx.user_id, "target_adjustment_requested", "students", body["student_id"], body)
    ctx.db.commit()
    return 201, {"ok": True}
