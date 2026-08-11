"""Shared grade-text normalization, used by both the roster importer (for new uploads) and
the one-time cleanup script (for students already imported with messy grade text).

Source spreadsheets have used all kinds of formats for the same grade: "7th", "6", "04"
(leading zero), "11th Grade", "K". Some schools (OKMS specifically) also prefix the grade
with a program code like "IDS" (Intensive Development Skills - a special ed classroom),
which isn't part of the grade at all and belongs in its own field.
"""
import re

GRADE_NAMES = {
    0: "Kindergarten",
    1: "1st Grade", 2: "2nd Grade", 3: "3rd Grade", 4: "4th Grade",
    5: "5th Grade", 6: "6th Grade", 7: "7th Grade", 8: "8th Grade",
    9: "9th Grade", 10: "10th Grade", 11: "11th Grade", 12: "12th Grade",
}

# Known program-code prefixes that sometimes show up glued onto the front of a Grade cell
# in source spreadsheets. Add more here if another school uses a different one.
KNOWN_PROGRAM_PREFIXES = ["IDS"]


def normalize_grade(raw):
    """Returns (program, normalized_grade).

    program is a recognized prefix like "IDS" if the raw text started with one, else None.
    normalized_grade is "Kindergarten" / "1st Grade" .. "12th Grade" when the grade portion
    can be confidently parsed, otherwise the original text is returned unchanged (nothing is
    ever silently discarded - an unparseable value is left as-is rather than blanked out).

    Idempotent: running this on an already-normalized value returns the same value, so it's
    safe to re-run against data that's already been cleaned up.
    """
    if not raw:
        return None, raw
    text = str(raw).strip()
    program = None

    for prefix in KNOWN_PROGRAM_PREFIXES:
        m = re.match(rf'^{re.escape(prefix)}\s+(.*)$', text, re.I)
        if m:
            program = prefix
            text = m.group(1).strip()
            break

    if re.match(r'^k(indergarten)?$', text, re.I):
        return program, GRADE_NAMES[0]

    m = re.match(r'^0*(\d{1,2})', text)
    if m:
        n = int(m.group(1))
        if n in GRADE_NAMES:
            return program, GRADE_NAMES[n]

    # Couldn't confidently parse (e.g. free text) - leave the grade text exactly as given.
    return program, raw.strip() if isinstance(raw, str) else raw
