import datetime
from .router import Router
from . import compliance as comp

router = Router()


def _today():
    return datetime.date.today().isoformat()


def _provider_live_status(db, provider_id):
    today = _today()
    now_t = datetime.datetime.now().strftime("%H:%M:%S")
    rows = db.execute(
        "SELECT * FROM sessions_sched WHERE provider_id=? AND session_date=? AND status NOT IN ('cancelled','excused') "
        "ORDER BY start_time", (provider_id, today),
    ).fetchall()
    if not rows:
        return "missing_schedule"
    for r in rows:
        start = datetime.datetime.strptime(r["start_time"], "%H:%M:%S" if r["start_time"].count(":") == 2 else "%H:%M")
        end = start + datetime.timedelta(minutes=r["duration_minutes"])
        now_dt = datetime.datetime.strptime(now_t, "%H:%M:%S")
        if start.time() <= now_dt.time() <= end.time():
            return "in_session"
    last = rows[-1]
    last_start = datetime.datetime.strptime(last["start_time"], "%H:%M:%S" if last["start_time"].count(":") == 2 else "%H:%M")
    last_end = last_start + datetime.timedelta(minutes=last["duration_minutes"])
    now_dt = datetime.datetime.strptime(now_t, "%H:%M:%S")
    if now_dt.time() > last_end.time():
        return "finished_for_day"
    return "available"


def _students_by_status(db, student_ids, year, month):
    on_target, at_risk, behind = [], [], []
    for sid in student_ids:
        s = db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
        if not s or s["status"] != "active":
            continue
        std, prorated, active_days, dim, is_p = comp.prorated_target(
            s["sessions_per_week"], s["service_start"], s["service_end"], year, month
        )
        month_prefix = f"{year:04d}-{month:02d}"
        completed = db.execute(
            "SELECT COUNT(*) c FROM attendance a JOIN sessions_sched s ON a.session_id=s.id "
            "WHERE a.student_id=? AND substr(s.session_date,1,7)=? AND a.result='completed'",
            (sid, month_prefix),
        ).fetchone()["c"]
        elapsed = comp.elapsed_active_days(s["service_start"], s["service_end"], year, month)
        status = comp.pace_status(completed, prorated, active_days, elapsed)
        entry = {"student_id": sid, "name": s["name"], "target": prorated, "completed": completed, "status": status}
        {"on_target": on_target, "at_risk": at_risk, "behind": behind}[status].append(entry)
    return on_target, at_risk, behind


@router.get("/api/dashboard")
def dashboard(ctx, params, body):
    today = _today()
    now = datetime.date.today()
    year, month = now.year, now.month

    provider_ids = ctx.visible_provider_ids() if ctx.role != "admin" else [
        r["id"] for r in ctx.db.execute("SELECT id FROM users WHERE role='provider'").fetchall()
    ]

    placeholders = ",".join("?" * len(provider_ids)) if provider_ids else "-1"
    today_sessions = ctx.db.execute(
        f"SELECT * FROM sessions_sched WHERE session_date=? AND provider_id IN ({placeholders})",
        [today] + provider_ids,
    ).fetchall() if provider_ids else []

    counts = {"scheduled": 0, "completed": 0, "missed": 0, "remaining": 0}
    for s in today_sessions:
        if s["status"] == "completed":
            counts["completed"] += 1
        elif s["status"] in ("makeup_needed", "provider_cancelled"):
            counts["missed"] += 1
        elif s["status"] in ("scheduled", "awaiting_approval"):
            counts["remaining"] += 1
        counts["scheduled"] += 1

    student_rows = ctx.db.execute("SELECT id FROM students WHERE status='active'").fetchall()
    if ctx.role == "admin":
        student_ids = [r["id"] for r in student_rows]
    else:
        all_students = ctx.db.execute("SELECT * FROM students WHERE status='active'").fetchall()
        from .routes_people import student_visible_to
        student_ids = [s["id"] for s in all_students if student_visible_to(ctx, s)]

    on_target, at_risk, behind = _students_by_status(ctx.db, student_ids, year, month)

    makeups = ctx.db.execute(
        f"SELECT * FROM makeup_queue WHERE status='open' AND responsible_provider_id IN ({placeholders})",
        provider_ids,
    ).fetchall() if provider_ids else []

    pending_approvals = ctx.db.execute("SELECT * FROM approvals WHERE status='pending'").fetchall()

    horizon = (now + datetime.timedelta(days=90)).isoformat()
    upcoming_iep = ctx.db.execute(
        "SELECT id, name, iep_date, eligibility_date FROM students WHERE status='active' AND "
        "((iep_date IS NOT NULL AND iep_date BETWEEN ? AND ?) OR (eligibility_date IS NOT NULL AND eligibility_date BETWEEN ? AND ?)) "
        "ORDER BY iep_date", (today, horizon, today, horizon),
    ).fetchall()
    upcoming_iep = [dict(r) for r in upcoming_iep if r["id"] in student_ids or ctx.role == "admin"]

    resp = {
        "today": {"date": today, **counts},
        "students_on_target": len(on_target), "students_at_risk": len(at_risk), "students_behind": len(behind),
        "students_behind_list": behind[:25],
        "students_at_risk_list": at_risk[:25],
        "outstanding_makeups": len(makeups),
        "pending_approvals": len(pending_approvals),
        "upcoming_iep_eligibility": upcoming_iep[:25],
    }

    if ctx.role in ("admin", "supervising_slp"):
        workload = []
        for pid in provider_ids:
            p = ctx.db.execute("SELECT id, name FROM users WHERE id=?", (pid,)).fetchone()
            if not p:
                continue
            caseload = ctx.db.execute(
                "SELECT COUNT(*) c FROM students WHERE provider_id=? AND status='active'", (pid,)
            ).fetchone()["c"]
            schools = ctx.db.execute(
                "SELECT DISTINCT sc.name FROM students st JOIN schools sc ON sc.id=st.school_id "
                "WHERE st.provider_id=? AND st.status='active'", (pid,)
            ).fetchall()
            workload.append({
                "provider_id": pid, "name": p["name"], "caseload": caseload,
                "schools": [s["name"] for s in schools],
                "live_status": _provider_live_status(ctx.db, pid),
            })
        resp["provider_workload"] = workload

    if ctx.role == "provider":
        weekly = ctx.db.execute(
            "SELECT * FROM sessions_sched WHERE provider_id=? AND session_date BETWEEN ? AND ? ORDER BY session_date, start_time",
            (ctx.user_id, today, (now + datetime.timedelta(days=7)).isoformat()),
        ).fetchall()
        resp["weekly_session_count"] = len(weekly)
        resp["live_status"] = _provider_live_status(ctx.db, ctx.user_id)

    return 200, resp
