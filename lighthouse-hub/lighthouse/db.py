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

CREATE TABLE IF NOT EXISTS
