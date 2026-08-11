import json
import datetime
from .router import Router
from .db import now_iso
from .errors import bad_request, forbidden, not_found, conflict
from .audit import log
from . import compliance as comp

router = Router()

VALID_RESULTS = {
    "completed", "student_absent", "student_refused", "provider_absent", "provider_cancelled",
    "school_closed", "school_testing", "field_trip", "assembly", "school_directed_unavailability",
    "rescheduled", "other_excused",
}


def attendance_public(row):
    return dict(row)


def _push_to_makeup_queue(ctx, attendance_row, session_row):
    ctx.db.execute(
        "INSERT INTO makeup_queue (attendance_id, student_id, school_id, original_provider_id, "
        "responsible_provider_id, reason, missed_date, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (attendance_row["id"], attendance_row["student_id"], session_row["school_id"], session_row["provider_id"],
         session_row["provider_id"], attendance_row["result"], session_row["session_date"], "open", now_iso()),
    )


@router.post("/api/attendance")
def record_attendance(ctx, params, body):
    session_id = body.get("session_id")
    student_id = body.get("student_id")
    result = body.get("result")
    if not session_id or not student_id or result not in VALID_RESULTS:
        raise bad_request("session_id, student_id, and a valid result are required")

    session = ctx.db.execute("SELECT * FROM sessions_sched WHERE id=?", (session_id,)).fetchone()
    if not session:
        raise not_found("Session not found")
    if ctx.role == "provider" and session["provider_id"] not in ctx.visible_provider_ids():
        raise forbidden("Not your assigned session")

    existing = ctx.db.execute(
        "SELECT * FROM attendance WHERE session_id=? AND student_id=?", (session_id, student_id)
    ).fetchone()

    is_past = session["session_date"] < now_iso()[:10]
    makeup_required = 1 if comp.requires_makeup(result) else 0
    makeup_status = "needed" if makeup_required else "not_applicable"

    if existing:
        locked = bool(existing["locked"])
        if locked and ctx.role == "provider":
            raise forbidden("This session date has passed; only an administrator or supervising SLP can correct it")
        if locked and ctx.role in ("admin", "supervising_slp"):
            # Late correction goes through the approvals queue rather than applying instantly.
            ctx.db.execute(
                "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
                "requested_by, status, created_at) VALUES ('late_attendance_correction','attendance',?,?,?,?,?,?,?)",
                (existing["id"], json.dumps({"result": existing["result"], "actual_duration_minutes": existing["actual_duration_minutes"]}),
                 json.dumps({"result": result, "actual_time": body.get("actual_time"),
                             "actual_duration_minutes": body.get("actual_duration_minutes"),
                             "admin_comment": body.get("admin_comment")}),
                 body.get("reason", "Historical attendance correction"), ctx.user_id, "pending", now_iso()),
            )
            log(ctx.db, ctx.user_id, "attendance_correction_requested", "attendance", existing["id"], body)
            ctx.db.commit()
            return 202, {"pending_approval": True}
        # Someone else already recorded a *different* result for this same student/session today.
        # This mostly happens under overlapping temporary coverage, where both the assigned
        # provider and the covering provider can see and record the same session - without this
        # check, whoever saves second silently overwrites the first with no warning. Require an
        # explicit confirmation instead of a silent overwrite (the caller resubmits with
        # confirm_conflict: true once the person has actually looked at what's being replaced).
        if (not locked and existing["recorded_by"] and existing["recorded_by"] != ctx.user_id
                and existing["result"] != result and not body.get("confirm_conflict")):
            recorder = ctx.db.execute("SELECT name FROM users WHERE id=?", (existing["recorded_by"],)).fetchone()
            raise conflict(
                f"{recorder['name'] if recorder else 'Someone else'} already recorded this student's "
                f"attendance for this session as \"{existing['result']}\". Confirm to overwrite it "
                f"with \"{result}\".",
                {"requires_confirmation": True, "existing_result": existing["result"],
                 "existing_recorded_by": recorder["name"] if recorder else None},
            )
        # Same-day edit by provider (or admin/SLP editing a not-yet-locked record): apply directly, keep history.
        ctx.db.execute(
            "INSERT INTO attendance_corrections (attendance_id, field, old_value, new_value, reason, changed_by, changed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (existing["id"], "result", existing["result"], result, body.get("reason", ""), ctx.user_id, now_iso()),
        )
        ctx.db.execute(
            "UPDATE attendance SET result=?, actual_time=?, actual_duration_minutes=?, makeup_required=?, "
            "makeup_status=?, admin_comment=?, recorded_by=?, recorded_at=? WHERE id=?",
            (result, body.get("actual_time"), body.get("actual_duration_minutes"), makeup_required,
             makeup_status if makeup_required else existing["makeup_status"], body.get("admin_comment"),
             ctx.user_id, now_iso(), existing["id"]),
        )
        attendance_id = existing["id"]
    else:
        cur = ctx.db.execute(
            "INSERT INTO attendance (session_id, student_id, result, scheduled_time, actual_time, "
            "actual_duration_minutes, makeup_required, makeup_status, admin_comment, recorded_by, recorded_at, locked) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
            (session_id, student_id, result, session["start_time"], body.get("actual_time"),
             body.get("actual_duration_minutes"), makeup_required, makeup_status, body.get("admin_comment"),
             ctx.user_id, now_iso()),
        )
        attendance_id = cur.lastrowid

    if makeup_required and not existing:
        row = ctx.db.execute("SELECT * FROM attendance WHERE id=?", (attendance_id,)).fetchone()
        _push_to_makeup_queue(ctx, row, session)

    # Roll up session status - but only once every student on the roster has an
    # attendance record. Rolling up on each partial update (the old behavior) let a
    # group session's status get set from a single student's result and then never
    # get corrected once the rest of the group's mixed results came in.
    roster_count = ctx.db.execute(
        "SELECT COUNT(*) c FROM session_students WHERE session_id=?", (session_id,)
    ).fetchone()["c"]
    all_att = ctx.db.execute(
        "SELECT result FROM attendance WHERE session_id=?", (session_id,)
    ).fetchall()
    if all_att and len(all_att) >= roster_count:
        results = [a["result"] for a in all_att]
        if any(comp.requires_makeup(r) for r in results):
            new_status = "makeup_needed"
        elif any(comp.counts_toward_completed(r) for r in results):
            # The session happened - individual no-shows are tracked on their own
            # attendance record, not by holding the whole session's status hostage.
            new_status = "completed"
        elif all(comp.is_school_controlled(r) for r in results):
            new_status = "excused"
        else:
            new_status = "excused"  # e.g. every student absent, nobody seen, no makeup owed
        ctx.db.execute("UPDATE sessions_sched SET status=? WHERE id=?", (new_status, session_id))

    if is_past:
        ctx.db.execute("UPDATE attendance SET locked=1 WHERE id=?", (attendance_id,))

    log(ctx.db, ctx.user_id, "attendance_recorded", "attendance", attendance_id, {"result": result})
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM attendance WHERE id=?", (attendance_id,)).fetchone()
    return 200, {"attendance": attendance_public(row)}


@router.get("/api/attendance")
def list_attendance(ctx, params, body):
    qs = params.get("_qs", {})
    q = "SELECT a.*, s.session_date, s.provider_id FROM attendance a JOIN sessions_sched s ON a.session_id=s.id WHERE 1=1"
    args = []
    if qs.get("student_id"):
        q += " AND a.student_id=?"
        args.append(qs["student_id"])
    if qs.get("session_id"):
        q += " AND a.session_id=?"
        args.append(qs["session_id"])
    if ctx.role == "provider":
        visible = ctx.visible_provider_ids()
        if not visible:
            return 200, {"attendance": []}
        q += f" AND s.provider_id IN ({','.join('?' * len(visible))})"
        args += visible
    q += " ORDER BY s.session_date DESC LIMIT 500"
    rows = ctx.db.execute(q, args).fetchall()
    return 200, {"attendance": [dict(r) for r in rows]}
