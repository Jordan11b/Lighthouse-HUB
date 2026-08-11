"""Excel roster import: upload -> preview (dedupe/flag/standardize) -> approve/reject.

The file arrives as base64 in a JSON body (the stdlib server doesn't parse
multipart/form-data, so the browser reads the file and sends it that way -
see web/js/views/administration.js).
"""
import base64
import binascii
import json
import re
from .router import Router
from .db import now_iso
from .errors import bad_request, forbidden, not_found
from .audit import log
from .xlsx_reader import read_first_sheet

router = Router()

FIELD_ALIASES = {
    "student_ext_id": ["student id", "studentid", "id", "student ext id"],
    "name": ["name", "student name", "full name"],
    "school": ["school", "school name"],
    "grade": ["grade"],
    "disability": ["disability", "diagnosis"],
    "eligibility_date": ["eligibility date", "eligibility"],
    "iep_date": ["iep date", "iep"],
    "service_start": ["service start", "start date"],
    "service_end": ["service end", "end date"],
    "provider": ["provider", "provider name", "provider email"],
    "sessions_per_week": ["sessions per week", "frequency", "sessions/week"],
    "duration_minutes": ["duration minutes", "duration", "minutes"],
    "group_individual": ["individual or group", "group or individual", "type"],
}


def _normalize_header(h):
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _map_headers(headers):
    mapping = {}
    normalized = {_normalize_header(h): h for h in headers}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized[alias]
                break
    return mapping


def _standardize_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None, False
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw[:10], True
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", raw)
    if m:
        mm, dd, yy = m.groups()
        yy = ("20" + yy) if len(yy) == 2 else yy
        try:
            return f"{int(yy):04d}-{int(mm):02d}-{int(dd):02d}", True
        except ValueError:
            return raw, False
    return raw, False


def _build_preview(ctx, headers, rows):
    """Builds the row-by-row import preview.

    Only two things ever keep a row out of the roster entirely: no name to identify the
    student by, or it looks like a duplicate (of an existing student, or of another row in
    this same file). Everything else - an unrecognized school, an unrecognized provider, a
    date that doesn't parse, a frequency/duration that isn't a number - still gets imported
    with a sensible default, and is recorded in "review_flags" so nothing gets silently lost
    off the roster. Those review flags get saved onto the student record itself (see
    approve_import below) and surface as a "needs review" notice in the app until someone
    opens the record, fixes it, and saves.
    """
    mapping = _map_headers(headers)
    missing_required = [f for f in ("name",) if f not in mapping]

    # Match on either the full school name or its short code (e.g. "OKMS"), so a roster file
    # can use whichever one the source spreadsheet already had in its School column.
    schools = {}
    for s in ctx.db.execute("SELECT id, name, code FROM schools").fetchall():
        schools[s["name"].strip().lower()] = s["id"]
        if s["code"] and s["code"].strip():
            schools.setdefault(s["code"].strip().lower(), s["id"])
    providers = ctx.db.execute("SELECT id, name, email FROM users WHERE role='provider'").fetchall()
    provider_by_name = {p["name"].strip().lower(): p["id"] for p in providers}
    provider_by_email = {p["email"].strip().lower(): p["id"] for p in providers}
    existing_ext_ids = {
        (r["student_ext_id"] or "").strip().lower()
        for r in ctx.db.execute("SELECT student_ext_id FROM students WHERE student_ext_id IS NOT NULL").fetchall()
    }
    existing_name_school = {
        (r["name"].strip().lower(), r["school_id"])
        for r in ctx.db.execute("SELECT name, school_id FROM students").fetchall()
    }
    seen_ext_ids_in_file = set()
    seen_name_school_in_file = set()

    preview_rows = []
    for i, row in enumerate(rows):
        blocking_flags = []   # row won't be created at all
        review_flags = []     # row IS created, but needs a follow-up look
        get = lambda f: (row.get(mapping.get(f, ""), "") or "").strip()

        name = get("name")
        school_raw = get("school")
        ext_id = get("student_ext_id")
        if not name:
            blocking_flags.append("Missing name - nothing to import this row as")

        school_id = schools.get(school_raw.strip().lower()) if school_raw else None
        if not school_raw:
            review_flags.append("No school given - left as \"Needs School Assignment\", please set the real school")
        elif not school_id:
            review_flags.append(f"School '{school_raw}' not recognized - left as \"Needs School Assignment\", please fix")

        provider_raw = get("provider")
        provider_id = None
        if not provider_raw:
            review_flags.append("No provider given - left unassigned")
        else:
            key = provider_raw.strip().lower()
            provider_id = provider_by_email.get(key) or provider_by_name.get(key)
            if not provider_id:
                # Fall back to matching on first name only (e.g. a schedule file that just
                # says "Kelly") - but only when exactly one provider has that first name, so
                # a first-name collision never silently assigns the wrong person. This case
                # counts as a clean match (no review flag) - it's unambiguous, so no follow-up
                # needed.
                first_name_matches = {pid for full_name, pid in provider_by_name.items() if full_name.split()[0] == key}
                if len(first_name_matches) == 1:
                    provider_id = next(iter(first_name_matches))
                elif len(first_name_matches) > 1:
                    review_flags.append(f"Provider '{provider_raw}' matches more than one account by first name - please assign manually")
                else:
                    review_flags.append(f"Provider '{provider_raw}' not recognized - left unassigned")

        elig, elig_ok = _standardize_date(get("eligibility_date"))
        if get("eligibility_date") and not elig_ok:
            review_flags.append(f"Eligibility date \"{get('eligibility_date')}\" not recognized - left blank")
            elig = None
        iep, iep_ok = _standardize_date(get("iep_date"))
        if get("iep_date") and not iep_ok:
            review_flags.append(f"IEP date \"{get('iep_date')}\" not recognized - left blank")
            iep = None
        svc_start, ss_ok = _standardize_date(get("service_start"))
        if get("service_start") and not ss_ok:
            review_flags.append(f"Service start \"{get('service_start')}\" not recognized - left blank")
            svc_start = None
        svc_end, se_ok = _standardize_date(get("service_end"))
        if get("service_end") and not se_ok:
            review_flags.append(f"Service end \"{get('service_end')}\" not recognized - left blank")
            svc_end = None

        is_duplicate = False
        if ext_id and ext_id.strip().lower() in existing_ext_ids:
            is_duplicate = True
            blocking_flags.append("Possible duplicate (matches an existing student ID)")
        elif name and school_id and (name.strip().lower(), school_id) in existing_name_school:
            is_duplicate = True
            blocking_flags.append("Possible duplicate (matches an existing name at this school)")

        # Catch duplicates *within this same file* too (e.g. the same student listed twice
        # by mistake) - the checks above only compare against students already saved in the
        # database, so two identical rows in one upload would otherwise both sail through.
        # Rows with no matched school fall back to the raw school text for this comparison so
        # two different unmatched-school students with the same name aren't mistaken for dupes.
        ext_key = ext_id.strip().lower() if ext_id else None
        school_key_part = school_id if school_id is not None else (f"raw:{school_raw.strip().lower()}" if school_raw else None)
        name_school_key = (name.strip().lower(), school_key_part) if (name and school_key_part is not None) else None
        if ext_key and ext_key in seen_ext_ids_in_file:
            is_duplicate = True
            blocking_flags.append("Duplicate row within this file (same student ID appears more than once)")
        elif name_school_key and name_school_key in seen_name_school_in_file:
            is_duplicate = True
            blocking_flags.append("Duplicate row within this file (same name/school appears more than once)")
        if ext_key:
            seen_ext_ids_in_file.add(ext_key)
        if name_school_key:
            seen_name_school_in_file.add(name_school_key)

        freq_raw = get("sessions_per_week")
        try:
            freq = float(freq_raw) if freq_raw else 1.0
        except ValueError:
            freq = 1.0
            review_flags.append(f"Sessions per week \"{freq_raw}\" not a number - defaulted to 1, please verify")
        dur_raw = get("duration_minutes")
        try:
            duration = int(float(dur_raw)) if dur_raw else 30
        except ValueError:
            duration = 30
            review_flags.append(f"Duration \"{dur_raw}\" not a number - defaulted to 30, please verify")

        gi_raw = get("group_individual").strip().lower()
        group_individual = "group" if gi_raw.startswith("g") else "individual"

        preview_rows.append({
            "row_number": i + 2,  # +2: header is row 1, data is 1-indexed after it
            "student_ext_id": ext_id or None, "name": name, "school_raw": school_raw, "school_id": school_id,
            "grade": get("grade") or None, "disability": get("disability") or None,
            "eligibility_date": elig, "iep_date": iep, "service_start": svc_start, "service_end": svc_end,
            "provider_raw": provider_raw or None, "provider_id": provider_id,
            "sessions_per_week": freq, "duration_minutes": duration, "group_individual": group_individual,
            "flags": blocking_flags + review_flags, "blocking_flags": blocking_flags, "review_flags": review_flags,
            "is_duplicate": is_duplicate,
            "will_import": not blocking_flags,
        })
    return {"headers": headers, "column_mapping": mapping, "missing_required_columns": missing_required, "rows": preview_rows}


PLACEHOLDER_SCHOOL_NAME = "Needs School Assignment"


def _get_or_create_placeholder_school(ctx):
    """A real, permanent school row used only as a parking spot for imported students whose
    School column was blank or didn't match anything - so the row can still be created (the
    database requires every student to belong to some school) without guessing which real
    school they meant. Reassign them for real from the student's Edit form."""
    row = ctx.db.execute("SELECT id FROM schools WHERE name=?", (PLACEHOLDER_SCHOOL_NAME,)).fetchone()
    if row:
        return row["id"]
    cur = ctx.db.execute(
        "INSERT INTO schools (name, code, is_active) VALUES (?,?,1)",
        (PLACEHOLDER_SCHOOL_NAME, None),
    )
    return cur.lastrowid


@router.post("/api/imports/roster")
def upload_roster(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    filename = body.get("filename") or "upload.xlsx"
    content_b64 = body.get("content_base64")
    if not content_b64:
        raise bad_request("No file content received")
    try:
        raw = base64.b64decode(content_b64)
    except (binascii.Error, ValueError):
        raise bad_request("Could not decode the uploaded file")
    try:
        headers, rows = read_first_sheet(raw)
    except Exception as e:
        raise bad_request(f"Could not read this file as .xlsx: {e}")
    if not headers:
        raise bad_request("No header row found in the first sheet")

    preview = _build_preview(ctx, headers, rows)
    cur = ctx.db.execute(
        "INSERT INTO import_batches (filename, status, row_count, preview_json, uploaded_by, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (filename, "pending", len(rows), json.dumps(preview), ctx.user_id, now_iso()),
    )
    batch_id = cur.lastrowid
    log(ctx.db, ctx.user_id, "roster_import_uploaded", "import_batches", batch_id, {"filename": filename, "rows": len(rows)})
    ctx.db.commit()
    return 201, {"id": batch_id, "preview": preview}


@router.get("/api/imports")
def list_imports(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    rows = ctx.db.execute("SELECT id, filename, status, row_count, uploaded_by, decided_by, decided_at, created_at FROM import_batches ORDER BY created_at DESC").fetchall()
    return 200, {"imports": [dict(r) for r in rows]}


@router.get("/api/imports/<id>")
def get_import(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    row = ctx.db.execute("SELECT * FROM import_batches WHERE id=?", (params["id"],)).fetchone()
    if not row:
        raise not_found()
    d = dict(row)
    d["preview"] = json.loads(d.pop("preview_json"))
    return 200, {"import": d}


@router.post("/api/imports/<id>/approve")
def approve_import(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    batch_id = int(params["id"])
    row = ctx.db.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
    if not row:
        raise not_found()
    if row["status"] != "pending":
        raise bad_request("This import has already been decided")
    preview = json.loads(row["preview_json"])

    placeholder_school_id = None  # created lazily, only if a row actually needs it

    created, skipped = 0, 0
    for r in preview["rows"]:
        if not r["will_import"]:
            skipped += 1
            continue
        school_id = r["school_id"]
        if not school_id:
            if placeholder_school_id is None:
                placeholder_school_id = _get_or_create_placeholder_school(ctx)
            school_id = placeholder_school_id
        review_flags = r.get("review_flags") or []
        ctx.db.execute(
            "INSERT INTO students (student_ext_id,name,school_id,grade,disability,eligibility_date,iep_date,"
            "service_start,service_end,provider_id,supervising_slp_id,sessions_per_week,duration_minutes,"
            "group_individual,status,comments,import_flags,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["student_ext_id"], r["name"], school_id, r["grade"], r["disability"], r["eligibility_date"],
             r["iep_date"], r["service_start"], r["service_end"], r["provider_id"],
             ctx.user_id if ctx.role == "supervising_slp" else None,
             r["sessions_per_week"], r["duration_minutes"], r["group_individual"], "active", None,
             "; ".join(review_flags) or None, now_iso()),
        )
        created += 1

    ctx.db.execute(
        "UPDATE import_batches SET status='approved', decided_by=?, decided_at=? WHERE id=?",
        (ctx.user_id, now_iso(), batch_id),
    )
    log(ctx.db, ctx.user_id, "roster_import_approved", "import_batches", batch_id, {"created": created, "skipped": skipped})
    ctx.db.commit()
    return 200, {"created": created, "skipped": skipped}


@router.post("/api/imports/<id>/reject")
def reject_import(ctx, params, body):
    ctx.require_role("admin", "supervising_slp")
    batch_id = int(params["id"])
    row = ctx.db.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
    if not row:
        raise not_found()
    ctx.db.execute(
        "UPDATE import_batches SET status='rejected', decided_by=?, decided_at=? WHERE id=?",
        (ctx.user_id, now_iso(), batch_id),
    )
    log(ctx.db, ctx.user_id, "roster_import_rejected", "import_batches", batch_id)
    ctx.db.commit()
    return 200, {"ok": True}
