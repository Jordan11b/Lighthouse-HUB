import json
import datetime
from .router import Router
from .db import now_iso
from .errors import bad_request, forbidden, not_found, conflict
from .audit import log
from . import compliance as comp

router = Router()

STATUS_COLOR = {
    "scheduled": "blue",
    "completed": "green",
    "makeup_needed": "orange",
    "makeup_scheduled": "purple",
    "excused": "gray",
    "provider_cancelled": "red",
    "awaiting_approval": "yellow",
    "cancelled": "gray",
}


def _time_range(date_str, start_time, duration_minutes):
    start_dt = datetime.datetime.fromisoformat(f"{date_str}T{start_time}")
    end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
    return start_dt, end_dt


def _has_conflict(db, provider_id, date_str, start_time, duration_minutes, exclude_session_id=None):
    new_start, new_end = _time_range(date_str, start_time, duration_minutes)
    rows = db.execute(
        "SELECT id, start_time, duration_minutes FROM sessions_sched "
        "WHERE provider_id=? AND session_date=? AND status NOT IN ('cancelled','excused')",
        (provider_id, date_str),
    ).fetchall()
    for r in rows:
        if exclude_session_id and r["id"] == exclude_session_id:
            continue
        ex_start, ex_end = _time_range(date_str, r["start_time"], r["duration_minutes"])
        if new_start < ex_end and ex_start < new_end:
            return r["id"]
    return None


def _iso_week(date_str):
    d = datetime.date.fromisoformat(date_str)
    return d.isocalendar()[:2]  # (iso_year, iso_week)


def session_public(db, row):
    d = dict(row)
    d["color"] = STATUS_COLOR.get(row["status"], "blue")
    students = db.execute(
        "SELECT st.id, st.name FROM session_students ss JOIN students st ON st.id=ss.student_id "
        "WHERE ss.session_id=?", (row["id"],),
    ).fetchall()
    d["students"] = [dict(s) for s in students]
    provider = db.execute("SELECT id, name FROM users WHERE id=?", (row["provider_id"],)).fetchone()
    school = db.execute("SELECT id, name FROM schools WHERE id=?", (row["school_id"],)).fetchone()
    d["provider_name"] = provider["name"] if provider else None
    d["school_name"] = school["name"] if school else None
    return d


@router.get("/api/schedule")
def list_schedule(ctx, params, body):
    qs = params.get("_qs", {})
    start = qs.get("start") or (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    end = qs.get("end") or (datetime.date.today() + datetime.timedelta(days=21)).isoformat()
    visible_providers = ctx.visible_provider_ids() if ctx.role != "admin" else None
    q = "SELECT * FROM sessions_sched WHERE session_date BETWEEN ? AND ?"
    args = [start, end]
    if visible_providers is not None:
        if not visible_providers:
            return 200, {"sessions": []}
        q += f" AND provider_id IN ({','.join('?' * len(visible_providers))})"
        args += visible_providers
    if qs.get("provider_id"):
        q += " AND provider_id=?"
        args.append(qs["provider_id"])
    if qs.get("school_id"):
        q += " AND school_id=?"
        args.append(qs["school_id"])
    q += " ORDER BY session_date, start_time"
    rows = ctx.db.execute(q, args).fetchall()
    out = [session_public(ctx.db, r) for r in rows]
    if qs.get("student_id"):
        sid = str(qs["student_id"])
        out = [s for s in out if any(str(st["id"]) == sid for st in s["students"])]
    return 200, {"sessions": out}


def _create_session_row(db, provider_id, school_id, date, start_time, duration, session_type,
                         student_ids, status, created_by, recurring_id=None):
    cur = db.execute(
        "INSERT INTO sessions_sched (provider_id, school_id, session_date, start_time, duration_minutes, "
        "session_type, recurring_schedule_id, status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (provider_id, school_id, date, start_time, duration, session_type, recurring_id, status,
         created_by, now_iso()),
    )
    session_id = cur.lastrowid
    for sid in student_ids:
        db.execute("INSERT INTO session_students (session_id, student_id) VALUES (?,?)", (session_id, sid))
    return session_id


@router.post("/api/schedule")
def create_session(ctx, params, body):
    provider_id = body.get("provider_id")
    school_id = body.get("school_id")
    date = body.get("date")
    start_time = body.get("start_time")
    duration = int(body.get("duration_minutes", 30))
    session_type = body.get("session_type", "individual")
    student_ids = body.get("student_ids") or ([body["student_id"]] if body.get("student_id") else [])
    override_reason = body.get("override_reason")

    if not (provider_id and school_id and date and start_time and student_ids):
        raise bad_request("provider_id, school_id, date, start_time, and at least one student are required")

    if ctx.role == "provider" and provider_id != ctx.user_id and provider_id not in ctx.visible_provider_ids():
        raise forbidden("Providers may only schedule their own assigned students")

    conflict_id = _has_conflict(ctx.db, provider_id, date, start_time, duration)
    if conflict_id and not override_reason:
        raise conflict("This overlaps another appointment for this provider", {"conflicting_session_id": conflict_id})

    status = "scheduled"
    if conflict_id and override_reason:
        if ctx.role not in ("admin", "supervising_slp"):
            raise forbidden("Only an administrator or supervising SLP may override a scheduling conflict")
        status = "awaiting_approval"

    session_id = _create_session_row(
        ctx.db, provider_id, school_id, date, start_time, duration, session_type, student_ids,
        status, ctx.user_id,
    )

    if status == "awaiting_approval":
        ctx.db.execute(
            "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
            "requested_by, status, created_at) VALUES ('conflict_override','sessions_sched',?,?,?,?,?,?,?)",
            (session_id, json.dumps({"conflicting_session_id": conflict_id}),
             json.dumps({"date": date, "start_time": start_time, "provider_id": provider_id}),
             override_reason, ctx.user_id, "pending", now_iso()),
        )

    log(ctx.db, ctx.user_id, "session_created", "sessions_sched", session_id, body)
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM sessions_sched WHERE id=?", (session_id,)).fetchone()
    return 201, {"session": session_public(ctx.db, row)}


@router.patch("/api/schedule/<id>/reschedule")
def reschedule_session(ctx, params, body):
    session_id = int(params["id"])
    row = ctx.db.execute("SELECT * FROM sessions_sched WHERE id=?", (session_id,)).fetchone()
    if not row:
        raise not_found()
    if ctx.role == "provider" and row["provider_id"] not in ctx.visible_provider_ids():
        raise forbidden()

    new_date = body.get("new_date") or row["session_date"]
    new_start = body.get("new_start_time") or row["start_time"]
    reason = body.get("reason") or ""
    urgent = bool(body.get("urgent"))

    same_week = _iso_week(new_date) == _iso_week(row["session_date"])

    conflict_id = _has_conflict(ctx.db, row["provider_id"], new_date, new_start, row["duration_minutes"],
                                 exclude_session_id=session_id)
    if conflict_id and not urgent:
        raise conflict("New time overlaps another appointment for this provider",
                        {"conflicting_session_id": conflict_id})

    if same_week or urgent or ctx.role in ("admin", "supervising_slp"):
        ctx.db.execute(
            "UPDATE sessions_sched SET session_date=?, start_time=? WHERE id=?",
            (new_date, new_start, session_id),
        )
        note = "urgent same-day/retrospective change" if urgent else ("same-week move" if same_week else "moved by admin/SLP")
        ctx.db.execute(
            "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
            "requested_by, status, decided_by, decided_at, decision_note, created_at) "
            "VALUES ('cross_week_move','sessions_sched',?,?,?,?,?,?,?,?,?,?)",
            (session_id, json.dumps({"date": row["session_date"], "start_time": row["start_time"]}),
             json.dumps({"date": new_date, "start_time": new_start}), reason, ctx.user_id,
             "approved" if (same_week or urgent) else "approved", ctx.user_id, now_iso(), note, now_iso()),
        )
        log(ctx.db, ctx.user_id, "session_rescheduled", "sessions_sched", session_id,
            {"new_date": new_date, "new_start_time": new_start, "note": note})
        ctx.db.commit()
        row = ctx.db.execute("SELECT * FROM sessions_sched WHERE id=?", (session_id,)).fetchone()
        return 200, {"session": session_public(ctx.db, row), "applied_immediately": True}

    # Cross-week/month move proposed by a provider requires approval.
    ctx.db.execute("UPDATE sessions_sched SET status='awaiting_approval' WHERE id=?", (session_id,))
    ctx.db.execute(
        "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
        "requested_by, status, created_at) VALUES ('cross_week_move','sessions_sched',?,?,?,?,?,?,?)",
        (session_id, json.dumps({"date": row["session_date"], "start_time": row["start_time"]}),
         json.dumps({"date": new_date, "start_time": new_start}), reason, ctx.user_id, "pending", now_iso()),
    )
    log(ctx.db, ctx.user_id, "session_reschedule_requested", "sessions_sched", session_id, body)
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM sessions_sched WHERE id=?", (session_id,)).fetchone()
    return 200, {"session": session_public(ctx.db, row), "applied_immediately": False}


# ------------------------------------------------------- recurring schedules

@router.get("/api/recurring")
def list_recurring(ctx, params, body):
    if ctx.role == "provider":
        rows = ctx.db.execute(
            "SELECT * FROM recurring_schedules WHERE provider_id=? ORDER BY id DESC", (ctx.user_id,)
        ).fetchall()
    else:
        rows = ctx.db.execute("SELECT * FROM recurring_schedules ORDER BY id DESC").fetchall()
    return 200, {"recurring_schedules": [dict(r) for r in rows]}


@router.post("/api/recurring")
def propose_recurring(ctx, params, body):
    required = ["student_id", "provider_id", "school_id", "day_of_week", "start_time",
                "duration_minutes", "effective_start"]
    for f in required:
        if body.get(f) is None:
            raise bad_request(f"{f} is required")
    if ctx.role == "provider" and body["provider_id"] != ctx.user_id:
        raise forbidden("Providers may only propose schedules for themselves")

    cur = ctx.db.execute(
        "INSERT INTO recurring_schedules (student_id, provider_id, school_id, day_of_week, start_time, "
        "duration_minutes, session_type, status, proposed_by, effective_start, effective_end, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (body["student_id"], body["provider_id"], body["school_id"], body["day_of_week"], body["start_time"],
         body["duration_minutes"], body.get("session_type", "individual"), "proposed", ctx.user_id,
         body["effective_start"], body.get("effective_end"), now_iso()),
    )
    rid = cur.lastrowid
    ctx.db.execute(
        "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
        "requested_by, status, created_at) VALUES ('recurring_schedule','recurring_schedules',?,?,?,?,?,?,?)",
        (rid, None, json.dumps(body), body.get("reason", "New recurring schedule"), ctx.user_id, "pending", now_iso()),
    )
    log(ctx.db, ctx.user_id, "recurring_schedule_proposed", "recurring_schedules", rid, body)
    ctx.db.commit()
    return 201, {"id": rid}


def generate_sessions_for_recurring(db, recurring_row, created_by, weeks_ahead=16):
    student = db.execute("SELECT * FROM students WHERE id=?", (recurring_row["student_id"],)).fetchone()
    hard_stop = None
    for candidate in (recurring_row["effective_end"], student["service_end"] if student else None,
                       student["iep_date"] if student else None):
        if candidate:
            hard_stop = candidate if hard_stop is None else min(hard_stop, candidate)

    start = datetime.date.fromisoformat(recurring_row["effective_start"])
    target_dow = int(recurring_row["day_of_week"])  # 0=Monday
    days_ahead = (target_dow - start.weekday()) % 7
    first = start + datetime.timedelta(days=days_ahead)

    created = []
    d = first
    horizon = datetime.date.today() + datetime.timedelta(weeks=weeks_ahead)
    limit_date = datetime.date.fromisoformat(hard_stop) if hard_stop else horizon
    while d <= min(horizon, limit_date):
        exists = db.execute(
            "SELECT s.id FROM sessions_sched s JOIN session_students ss ON ss.session_id=s.id "
            "WHERE ss.student_id=? AND s.session_date=? AND s.recurring_schedule_id=?",
            (recurring_row["student_id"], d.isoformat(), recurring_row["id"]),
        ).fetchone()
        if not exists and not _has_conflict(db, recurring_row["provider_id"], d.isoformat(),
                                             recurring_row["start_time"], recurring_row["duration_minutes"]):
            sid = _create_session_row(
                db, recurring_row["provider_id"], recurring_row["school_id"], d.isoformat(),
                recurring_row["start_time"], recurring_row["duration_minutes"], recurring_row["session_type"],
                [recurring_row["student_id"]], "scheduled", created_by, recurring_id=recurring_row["id"],
            )
            created.append(sid)
        d += datetime.timedelta(days=7)
    return created
