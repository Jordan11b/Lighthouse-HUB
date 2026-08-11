"""SQLite schema and connection helper for Lighthouse Therapy Hub.

Zero third-party dependencies: everything here is Python standard library.
"""
import os
import sqlite3
import datetime

# On a normal local run, data/ lives next to server.py. On a host with a persistent disk
# (e.g. Render), point LIGHTHOUSE_DATA_DIR at the mounted disk so the database survives
# deploys/restarts instead of living on the ephemeral container filesystem.
DATA_DIR = os.environ.get(
    "LIGHTHOUSE_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
DB_PATH = os.path.join(DATA_DIR, "lighthouse.db")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK(role IN ('admin','supervising_slp','provider')),
    password_hash TEXT,
    password_salt TEXT,
    mfa_secret TEXT,
    mfa_enabled INTEGER NOT NULL DEFAULT 0,
    notify_email TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_supervising_slp INTEGER NOT NULL DEFAULT 0,
    supervising_slp_id INTEGER REFERENCES users(id),
    credentials TEXT,
    license_number TEXT,
    license_expiration TEXT,
    invited_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions_auth (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_activity TEXT NOT NULL DEFAULT (datetime('now')),
    mfa_verified INTEGER NOT NULL DEFAULT 0,
    mfa_code_hash TEXT,
    mfa_code_expires TEXT,
    mfa_attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code TEXT,
    address TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    contact_email TEXT,
    hours TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS school_closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    closure_date TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_ext_id TEXT,
    name TEXT NOT NULL,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    grade TEXT,
    program TEXT,
    disability TEXT,
    eligibility_date TEXT,
    iep_date TEXT,
    service_start TEXT,
    service_end TEXT,
    provider_id INTEGER REFERENCES users(id),
    supervising_slp_id INTEGER REFERENCES users(id),
    sessions_per_week REAL NOT NULL DEFAULT 1,
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    group_individual TEXT NOT NULL DEFAULT 'individual' CHECK(group_individual IN ('individual','group')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','archived')),
    comments TEXT,
    import_flags TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS student_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    from_provider_id INTEGER REFERENCES users(id),
    to_provider_id INTEGER REFERENCES users(id),
    from_school_id INTEGER REFERENCES schools(id),
    to_school_id INTEGER REFERENCES schools(id),
    effective_date TEXT NOT NULL,
    reason TEXT,
    requested_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS temporary_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    covering_provider_id INTEGER NOT NULL REFERENCES users(id),
    original_provider_id INTEGER NOT NULL REFERENCES users(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    authorized_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recurring_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    provider_id INTEGER NOT NULL REFERENCES users(id),
    school_id INTEGER NOT NULL REFERENCES schools(id),
    day_of_week INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    session_type TEXT NOT NULL DEFAULT 'individual' CHECK(session_type IN ('individual','group')),
    group_key TEXT,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','active','ended','rejected')),
    proposed_by INTEGER REFERENCES users(id),
    effective_start TEXT NOT NULL,
    effective_end TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions_sched (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL REFERENCES users(id),
    school_id INTEGER NOT NULL REFERENCES schools(id),
    session_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    session_type TEXT NOT NULL DEFAULT 'individual' CHECK(session_type IN ('individual','group')),
    recurring_schedule_id INTEGER REFERENCES recurring_schedules(id),
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN (
        'scheduled','completed','makeup_needed','makeup_scheduled',
        'excused','provider_cancelled','awaiting_approval','cancelled'
    )),
    conflict_override_reason TEXT,
    created_by INTEGER REFERENCES users(id),
    original_session_id INTEGER REFERENCES sessions_sched(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS session_students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions_sched(id),
    student_id INTEGER NOT NULL REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions_sched(id),
    student_id INTEGER NOT NULL REFERENCES students(id),
    result TEXT NOT NULL CHECK(result IN (
        'completed','student_absent','student_refused','provider_absent',
        'provider_cancelled','school_closed','school_testing','field_trip',
        'assembly','school_directed_unavailability','rescheduled','other_excused'
    )),
    scheduled_time TEXT,
    actual_time TEXT,
    actual_duration_minutes INTEGER,
    makeup_required INTEGER NOT NULL DEFAULT 0,
    makeup_status TEXT DEFAULT 'not_applicable' CHECK(makeup_status IN ('not_applicable','needed','scheduled','completed')),
    admin_comment TEXT,
    recorded_by INTEGER REFERENCES users(id),
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    locked INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, student_id)
);

CREATE TABLE IF NOT EXISTS attendance_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attendance_id INTEGER NOT NULL REFERENCES attendance(id),
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    changed_by INTEGER REFERENCES users(id),
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS makeup_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attendance_id INTEGER NOT NULL REFERENCES attendance(id),
    student_id INTEGER NOT NULL REFERENCES students(id),
    school_id INTEGER NOT NULL REFERENCES schools(id),
    original_provider_id INTEGER NOT NULL REFERENCES users(id),
    responsible_provider_id INTEGER NOT NULL REFERENCES users(id),
    reason TEXT,
    missed_date TEXT NOT NULL,
    proposed_makeup_date TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','scheduled','completed','excused_exception')),
    completed_session_id INTEGER REFERENCES sessions_sched(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN (
        'recurring_schedule','cross_week_move','conflict_override','target_adjustment',
        'transfer','late_attendance_correction','makeup_exception','emergency_change_review'
    )),
    entity_table TEXT,
    entity_id INTEGER,
    original_info TEXT,
    proposed_change TEXT,
    reason TEXT,
    requested_by INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    decided_by INTEGER REFERENCES users(id),
    decided_at TEXT,
    decision_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS target_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    year_month TEXT NOT NULL,
    adjusted_target INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, year_month)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    recipient_user_id INTEGER REFERENCES users(id),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    row_count INTEGER,
    preview_json TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    decided_by INTEGER REFERENCES users(id),
    decided_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn):
    """Add columns that were introduced after a database might already have been created,
    so an existing clinic's data upgrades in place instead of needing to be wiped."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions_auth)")}
    if "mfa_code_hash" not in cols:
        conn.execute("ALTER TABLE sessions_auth ADD COLUMN mfa_code_hash TEXT")
    if "mfa_code_expires" not in cols:
        conn.execute("ALTER TABLE sessions_auth ADD COLUMN mfa_code_expires TEXT")
    if "mfa_attempts" not in cols:
        conn.execute("ALTER TABLE sessions_auth ADD COLUMN mfa_attempts INTEGER NOT NULL DEFAULT 0")

    user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "notify_email" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN notify_email TEXT")
    if "is_supervising_slp" not in user_cols:
        # Lets a role='admin' account also act as a clinical supervising SLP (providers can
        # report to them, credentials/license are tracked) without needing a second account.
        # Meaningless for role='provider'; always implicitly true for role='supervising_slp'.
        conn.execute("ALTER TABLE users ADD COLUMN is_supervising_slp INTEGER NOT NULL DEFAULT 0")

    school_cols = {row["name"] for row in conn.execute("PRAGMA table_info(schools)")}
    if "code" not in school_cols:
        # Short acronym (e.g. "OKMS") kept alongside the full display name (e.g. "Orchard
        # Knob Middle School") so roster/schedule spreadsheets can keep using the acronym in
        # their School column while the app shows the real name everywhere.
        conn.execute("ALTER TABLE schools ADD COLUMN code TEXT")

    student_cols = {row["name"] for row in conn.execute("PRAGMA table_info(students)")}
    if "program" not in student_cols:
        # A special-ed classroom/program designation (e.g. "IDS" - Intensive Development
        # Skills) that some source rosters glue onto the front of the Grade text instead of
        # giving it its own column. Kept separate so Grade itself can stay normalized.
        conn.execute("ALTER TABLE students ADD COLUMN program TEXT")
    if "import_flags" not in student_cols:
        # Free-text note (e.g. "School not recognized - please assign"; "Provider not set")
        # left behind when a roster import couldn't fully match a row, so nothing gets left
        # off the roster just because one field was missing or unrecognized - the row still
        # gets created, and this is what powers the "needs review" alert on the Students page.
        # Cleared automatically the next time the record is edited and saved.
        conn.execute("ALTER TABLE students ADD COLUMN import_flags TEXT")


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    conn.close()


def now_iso():
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    init_db()
    print("Database initialized at", DB_PATH)
