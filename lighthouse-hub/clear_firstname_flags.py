"""One-time cleanup: removes just the "Provider matched by first name only..." note from
students' import_flags, since first-name provider matching is confirmed unambiguous (no two
providers share a first name) - this note was just noise, not something to actually review.

Any OTHER real review flags on a student (unrecognized school, missing dates, etc.) are left
untouched. If the first-name note was the ONLY flag a student had, import_flags is cleared
to NULL entirely (removing the "needs review" tag). Safe to re-run - does nothing on a second
pass since the target text will already be gone.

Run this from the Render Shell:
    PYTHONPATH=. python3 clear_firstname_flags.py
"""
import re
from lighthouse.db import get_db

FIRSTNAME_FLAG_RE = re.compile(r"Provider matched by first name only \([^)]*\) - please double-check this is the right person")

def main():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, import_flags FROM students WHERE import_flags LIKE '%matched by first name only%'"
    ).fetchall()
    print(f"Found {len(rows)} student(s) with the first-name-match note.")

    cleared, trimmed = 0, 0
    for r in rows:
        parts = [p.strip() for p in r["import_flags"].split(";")]
        remaining = [p for p in parts if not FIRSTNAME_FLAG_RE.search(p)]
        new_value = "; ".join(remaining) if remaining else None
        conn.execute("UPDATE students SET import_flags=? WHERE id=?", (new_value, r["id"]))
        if new_value is None:
            cleared += 1
            print(f"  cleared entirely: {r['name']}")
        else:
            trimmed += 1
            print(f"  trimmed (other flags remain): {r['name']} -> {new_value}")
    conn.commit()
    conn.close()
    print(f"\nDone. {cleared} student(s) fully cleared, {trimmed} student(s) had other flags remain.")

if __name__ == "__main__":
    main()
