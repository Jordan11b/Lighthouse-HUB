"""Fictional demo data - matches the launch plan's call for practice data.

Run with: python3 -m lighthouse.seed
"""
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lighthouse.db import init_db, get_db, now_iso
from lighthouse.security import hash_password
from lighthouse import compliance as comp


def run():
    init_db()
    db = get_db()

    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] > 0:
        print("Database already has data - skipping seed. Delete data/lighthouse.db to reseed.")
        return

    def add_user(name, email, role, password, supervising_slp_id=None, credentials=None,
                 license_number=None, license_expiration=None):
        h, s = hash_password(password)
        cur = db.execute(
            "INSERT INTO users (name,email,role,password_hash,password_salt,is_active,supervising_slp_id,"
            "credentials,license_number,license_expiration,invited_at,created_at) "
            "VALUES (?,?,?,?,?,1,?,?,?,?,?,?)",
            (name, email, role, h, s, supervising_slp_id, credentials, license_number, license_expiration,
             now_iso(), now_iso()),
        )
        return cur.lastrowid

    admin_id = add_user("Courtney", "Courtney.Lighthousetherapy@gmail.com", "admin", "Lighthouse2026!")
    add_user("Jordan Johnson", "jordan11bravo@gmail.com", "admin", "Lighthouse2026!")
    slp_id = add_user("Dana Whitfield, M.S. CCC-SLP", "dana.whitfield@lighthouse.example", "supervising_slp",
                       "Lighthouse2026!")
    prov1_id = add_user("Maria Chen", "maria.chen@lighthouse.example", "provider", "Lighthouse2026!",
                         supervising_slp_id=slp_id, credentials="SLP-CCC",
                         license_number="SLP-44210", license_expiration="2026-11-30")
    prov2_id = add_user("Ben Okafor", "ben.okafor@lighthouse.example", "provider", "Lighthouse2026!",
                         supervising_slp_id=slp_id, credentials="SLP-CF",
                         license_number="SLP-51092", license_expiration="2026-09-15")

    def add_school(name, address, contact_name, contact_phone):
        cur = db.execute(
            "INSERT INTO schools (name,address,contact_name,contact_phone,contact_email,hours,is_active) "
            "VALUES (?,?,?,?,?,?,1)",
            (name, address, contact_name, contact_phone, contact_name.lower().replace(" ", ".") + "@district.example",
             "8:00 AM - 3:30 PM"),
        )
        return cur.lastrowid

    school1 = add_school("Riverside Elementary", "100 Riverside Dr", "Pat Nguyen", "555-0101")
    school2 = add_school("Maple Grove Elementary", "220 Maple Ave", "Sam Torres", "555-0102")

    today = datetime.date.today()
    year_start = f"{today.year}-08-01"

    def add_student(ext_id, name, school_id, grade, disability, elig, iep, svc_start, svc_end,
                     provider_id, sessions_per_week, duration, group_ind="individual", status="active"):
        cur = db.execute(
            "INSERT INTO students (student_ext_id,name,school_id,grade,disability,eligibility_date,iep_date,"
            "service_start,service_end,provider_id,supervising_slp_id,sessions_per_week,duration_minutes,"
            "group_individual,status,comments,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ext_id, name, school_id, grade, disability, elig, iep, svc_start, svc_end, provider_id, slp_id,
             sessions_per_week, duration, group_ind, status, None, now_iso()),
        )
        return cur.lastrowid

    s1 = add_student("STU-1001", "Ava Reyes", school1, "2", "Speech Sound Disorder",
                      "2027-01-15", "2027-01-15", year_start, "2027-06-15", prov1_id, 2, 30)
    s2 = add_student("STU-1002", "Noah Park", school1, "4", "Language Disorder",
                      (today + datetime.timedelta(days=45)).isoformat(),
                      (today + datetime.timedelta(days=45)).isoformat(), year_start, "2027-06-15", prov1_id, 1, 30)
    s3 = add_student("STU-1003", "Liam Osei", school2, "1", "Fluency Disorder",
                      "2026-12-01", "2026-12-01", year_start, "2027-06-15", prov2_id, 2, 20)
    s4 = add_student("STU-1004", "Sofia Martins", school2, "3", "Speech Sound Disorder",
                      "2027-03-01", "2027-03-01", (today.replace(day=1)).isoformat(), "2027-06-15", prov2_id, 1, 30)
    s5 = add_student("STU-1005", "Ethan Brooks", school1, "2", "Language Disorder",
                      "2027-02-10", "2027-02-10", year_start, "2027-06-15", prov1_id, 2, 30, group_ind="group")
    s6 = add_student("STU-1006", "Mia Alvarez", school1, "2", "Language Disorder",
                      "2027-02-10", "2027-02-10", year_start, "2027-06-15", prov1_id, 2, 30, group_ind="group")

    # A few past sessions with recorded attendance so the dashboard/compliance views have real numbers.
    def add_session_with_attendance(provider_id, school_id, date, start_time, duration, student_ids, result):
        cur = db.execute(
            "INSERT INTO sessions_sched (provider_id, school_id, session_date, start_time, duration_minutes, "
            "session_type, status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (provider_id, school_id, date, start_time, duration,
             "group" if len(student_ids) > 1 else "individual", "scheduled", admin_id, now_iso()),
        )
        sess_id = cur.lastrowid
        for sid in student_ids:
            db.execute("INSERT INTO session_students (session_id, student_id) VALUES (?,?)", (sess_id, sid))
            makeup_required = 1 if result in ("provider_absent", "provider_cancelled") else 0
            db.execute(
                "INSERT INTO attendance (session_id, student_id, result, scheduled_time, actual_time, "
                "actual_duration_minutes, makeup_required, makeup_status, recorded_by, recorded_at, locked) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                (sess_id, sid, result, start_time, start_time if result == "completed" else None,
                 duration if result == "completed" else None, makeup_required,
                 "needed" if makeup_required else "not_applicable", provider_id, now_iso()),
            )
            if makeup_required:
                db.execute(
                    "INSERT INTO makeup_queue (attendance_id, student_id, school_id, original_provider_id, "
                    "responsible_provider_id, reason, missed_date, status, created_at) "
                    "SELECT id, ?, ?, ?, ?, ?, ?, 'open', ? FROM attendance WHERE session_id=? AND student_id=?",
                    (sid, school_id, provider_id, provider_id, result, date, now_iso(), sess_id, sid),
                )
        if all(r == "completed" for r in [result]):
            db.execute("UPDATE sessions_sched SET status='completed' WHERE id=?", (sess_id,))
        elif result in ("provider_absent", "provider_cancelled"):
            db.execute("UPDATE sessions_sched SET status='makeup_needed' WHERE id=?", (sess_id,))
        elif result in ("student_absent", "student_refused", "school_closed", "school_testing", "field_trip",
                         "assembly", "school_directed_unavailability", "other_excused"):
            db.execute("UPDATE sessions_sched SET status='excused' WHERE id=?", (sess_id,))
        return sess_id

    d0 = today.replace(day=1)
    add_session_with_attendance(prov1_id, school1, (d0 + datetime.timedelta(days=1)).isoformat(), "09:00", 30, [s1], "completed")
    add_session_with_attendance(prov1_id, school1, (d0 + datetime.timedelta(days=8)).isoformat(), "09:00", 30, [s1], "completed")
    add_session_with_attendance(prov1_id, school1, (d0 + datetime.timedelta(days=15)).isoformat(), "09:00", 30, [s1], "provider_cancelled")
    add_session_with_attendance(prov2_id, school2, (d0 + datetime.timedelta(days=2)).isoformat(), "10:00", 20, [s3], "completed")
    add_session_with_attendance(prov2_id, school2, (d0 + datetime.timedelta(days=9)).isoformat(), "10:00", 20, [s3], "student_absent")
    add_session_with_attendance(prov1_id, school1, (d0 + datetime.timedelta(days=3)).isoformat(), "13:00", 30, [s5, s6], "completed")

    # Upcoming/future scheduled sessions
    def add_future(provider_id, school_id, date, start_time, duration, student_ids):
        cur = db.execute(
            "INSERT INTO sessions_sched (provider_id, school_id, session_date, start_time, duration_minutes, "
            "session_type, status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (provider_id, school_id, date, start_time, duration,
             "group" if len(student_ids) > 1 else "individual", "scheduled", admin_id, now_iso()),
        )
        sess_id = cur.lastrowid
        for sid in student_ids:
            db.execute("INSERT INTO session_students (session_id, student_id) VALUES (?,?)", (sess_id, sid))
        return sess_id

    for i in range(1, 6):
        add_future(prov1_id, school1, (today + datetime.timedelta(days=i)).isoformat(), "09:00", 30, [s1])
    add_future(prov2_id, school2, (today + datetime.timedelta(days=2)).isoformat(), "10:00", 20, [s3])
    add_future(prov1_id, school1, (today + datetime.timedelta(days=1)).isoformat(), "13:00", 30, [s5, s6])

    # A pending recurring-schedule proposal awaiting approval
    import json
    cur = db.execute(
        "INSERT INTO recurring_schedules (student_id, provider_id, school_id, day_of_week, start_time, "
        "duration_minutes, session_type, status, proposed_by, effective_start, effective_end, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (s2, prov1_id, school1, 2, "09:30", 30, "individual", "proposed", prov1_id,
         (today + datetime.timedelta(days=7)).isoformat(), None, now_iso()),
    )
    rid = cur.lastrowid
    db.execute(
        "INSERT INTO approvals (type, entity_table, entity_id, original_info, proposed_change, reason, "
        "requested_by, status, created_at) VALUES ('recurring_schedule','recurring_schedules',?,?,?,?,?,?,?)",
        (rid, None, json.dumps({"student_id": s2, "day_of_week": 2, "start_time": "09:30"}),
         "New IEP just finalized for Noah Park", prov1_id, "pending", now_iso()),
    )

    db.commit()
    db.close()
    print("Seed complete.")
    print("Demo logins (password: Lighthouse2026!):")
    print("  admin            Courtney.Lighthousetherapy@gmail.com")
    print("  admin            jordan11bravo@gmail.com")
    print("  supervising_slp  dana.whitfield@lighthouse.example")
    print("  provider         maria.chen@lighthouse.example")
    print("  provider         ben.okafor@lighthouse.example")
    print("On first login each account sets up MFA (TOTP secret shown on screen).")


if __name__ == "__main__":
    run()
