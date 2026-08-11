"""One-time cleanup: normalizes Grade text on every already-imported student (e.g. "IDS 6th",
"04", "11th Grade", "K" all become "Kindergarten" or "1st Grade".."12th Grade"), and splits
any program code (like "IDS" - Intensive Development Skills) out of Grade into its own
Program field, so it doesn't get lost or stay mashed together with the grade text.

Safe to re-run - normalize_grade() is idempotent, so a student whose grade is already clean
comes out unchanged.

Run this from the Render Shell:
    PYTHONPATH=. python3 normalize_existing_grades.py
"""
from lighthouse.db import get_db
from lighthouse.grade_utils import normalize_grade


def main():
    conn = get_db()
    rows = conn.execute("SELECT id, name, grade, program FROM students").fetchall()
    print(f"Checking {len(rows)} student(s)...")

    changed = 0
    for r in rows:
        new_program, new_grade = normalize_grade(r["grade"])
        # A dedicated Program value already on the record wins over anything detected in Grade.
        final_program = r["program"] or new_program
        if new_grade != r["grade"] or final_program != r["program"]:
            conn.execute(
                "UPDATE students SET grade=?, program=? WHERE id=?",
                (new_grade, final_program, r["id"]),
            )
            changed += 1
            print(f"  {r['name']}: grade {r['grade']!r} -> {new_grade!r}"
                  + (f", program -> {final_program!r}" if final_program != r["program"] else ""))

    conn.commit()
    conn.close()
    print(f"\nDone. {changed} student(s) updated, {len(rows) - changed} already clean.")


if __name__ == "__main__":
    main()
