# Lighthouse Therapy Hub — Working Prototype (Version 1 core)

This is a running, clickable build of the system described in the Master
Product Specification: scheduling, attendance, monthly compliance/proration,
makeup tracking, approvals, and role-based access for a school-based speech
therapy clinic.

It's a **prototype for review and iteration**, not a hardened production
deployment — see "What this is / isn't" below before using it with real
student data.

## Run it (one command, no installation)

Requires only Python 3.9+ (already on most Macs; if not, install from
python.org). No `pip install`, no Node, no internet connection needed.

```
cd lighthouse-hub
python3 server.py
```

Then open **http://localhost:8899** in a browser. First run creates the
database and prints a message. Stop the server with Ctrl+C.

Custom port: `python3 server.py 9000`

### Demo logins

The first time you run it, the database is empty. Seed it with fictional
practice data (matches the spec's launch-plan guidance to test with
fictional data before go-live):

```
python3 -m lighthouse.seed
```

| Role | Email | Password |
|---|---|---|
| Clinic administrator | Courtney.Lighthousetherapy@gmail.com | Lighthouse2026! |
| Clinic administrator | jordan11bravo@gmail.com | Lighthouse2026! |
| Supervising SLP | dana.whitfield@lighthouse.example | Lighthouse2026! |
| Provider | maria.chen@lighthouse.example | Lighthouse2026! |
| Provider | ben.okafor@lighthouse.example | Lighthouse2026! |

MFA is currently **switched off** for easier local testing (login goes
straight through on email + password). The code for it is still there and
works — flip `MFA_REQUIRED = True` at the top of `lighthouse/routes_auth.py`
to turn it back on before anyone besides you uses this.

To start over with a clean database: delete `data/lighthouse.db` and reseed.

## What's built (the daily-use spine)

- **Auth & accounts**: invite-only (admin creates accounts, no public
  signup), password + required MFA, 30-minute inactivity timeout, password
  reset, account deactivation with "can't remove the last admin" protection.
- **Roles**: clinic administrator, supervising SLP, provider — each sees and
  can do only what the spec allows (providers see only their assigned/covered
  caseload; no self-approval anywhere).
- **Students, providers, schools**: full records matching the spec's field
  lists, temporary coverage grants with automatic date-based expiry.
- **Scheduling**: daily/weekly views, individual and group sessions (each
  student gets independent attendance/credit), recurring schedule proposals
  that generate real sessions once approved and auto-stop at service-end or
  IEP date, conflict prevention that blocks double-booking with an
  admin/SLP-only override path, same-week reschedules apply instantly while
  cross-week/month moves route to approval.
- **Attendance**: the full result list from the spec, locked after midnight
  on the service date (providers can't edit; admin/SLP corrections after
  that go through the approvals queue), full correction history.
- **Compliance & proration**: monthly targets prorated for partial-month
  service (always rounds up), on-target/at-risk/behind status computed
  against pace-to-date rather than the full month (so a student isn't
  flagged "behind" on day 3 of the month), school-controlled interruptions
  excluded from compliance the way the spec requires.
- **Makeup queue**: auto-populated only for provider-caused misses, links to
  the original session, reassignable, schedulable, or exception-approvable.
- **Approvals**: one queue for recurring schedules, cross-week moves,
  conflict overrides, transfers, late attendance corrections, and makeup
  exceptions — no one can approve their own request.
- **Dashboard**: today's counts, compliance breakdown, provider workload and
  live status, outstanding makeups, pending approvals, upcoming IEP/
  eligibility dates — scoped per role.
- **Reports & audit**: a filterable/exportable (CSV **and PDF**) compliance
  report and a full audit history view.
- **Excel roster import**: upload a `.xlsx` on the Administration page, get a
  row-by-row preview (duplicate detection, unknown school/provider flags,
  date standardization, missing-field warnings), and nothing is added to the
  roster until you approve the batch. Import history is kept.
- **Alerts**: a dedicated Alerts page grouping items into Urgent / Attention /
  Informational (conflicts and expired IEP dates; students behind pace,
  unresolved makeups, pending approvals, upcoming IEP dates, expiring
  licenses; recent approval decisions and imports).
- **Administration screen**: school-year dates, daily digest time setting,
  a read-only reference table of attendance/cancellation reasons, plus the
  roster import tool and its history.

## What's still deferred

- **Real email delivery.** The spec's timing rules (90/60/30/14-day IEP
  warnings, weekly pace/makeup emails, daily 6am provider digest) are fully
  implemented as logic — see "Run alert check now" on the Alerts page — but
  there's no SMTP server reachable from this environment to actually send
  mail, so notifications are written to a simulated outbox instead (visible
  on the Alerts page) and printed to the server console. Wiring real email
  means implementing one function, `_deliver()` in
  `lighthouse/routes_alerts.py`, and hooking `run-check` up to a real
  scheduler (cron, `launchd`, etc.) instead of the manual button.
- Multi-branch expansion hooks (explicitly future work in the spec).

## Architecture, in brief

- **Backend**: Python standard library only — `http.server` for the HTTP
  layer, `sqlite3` for storage, `hashlib`/`hmac` for password hashing
  (PBKDF2-HMAC-SHA256) and TOTP MFA (RFC 6238). No third-party packages to
  install, no version drift, works offline.
- **Frontend**: vanilla HTML/CSS/JS (ES modules), no build step — open the
  files directly or serve them (the Python server does both, from the same
  origin, so there's no CORS configuration to manage).
- **Data**: a single SQLite file at `data/lighthouse.db`. Back it up by
  copying that one file. Good for one clinic's data volumes; if Lighthouse
  later wants simultaneous multi-branch write traffic or remote hosting,
  swapping in Postgres is a contained change (the SQL is plain, no ORM).

## What this is / isn't

This runs entirely on your machine — nothing leaves your computer, no
external services are called at runtime, which is a reasonable way to pilot
this with the team before deciding on hosting. It's not yet a hardened,
internet-facing production system: before putting real student data in front
of the whole clinic, get a developer to review session/token handling,
add HTTPS (this local server is plain HTTP), add proper backups, and pressure-
test the concurrency model (SQLite handles one clinic's traffic fine, but a
real deployment should be reviewed for the actual hosting environment).
The security principles from the spec (invite-only, MFA, audit history,
role scoping, 30-minute timeout) are implemented with real algorithms, not
stubs — but a professional security review is still the right next step
before go-live. **MFA is currently switched off** (see the Run It section) —
turn it back on before real people beyond you are using this.

## Project layout

```
lighthouse-hub/
  server.py              entry point — run this
  lighthouse/             backend: db schema, auth, business rules, API routes
  web/                     frontend: index.html, styles.css, js/ (ES modules)
  data/                    lighthouse.db lives here once you run it
```

## Changelog

- Fixed: repeated login attempts before finishing MFA setup used to issue a
  new secret each time, silently invalidating whatever code you'd already
  entered into an authenticator app.
- Widened TOTP verification tolerance to reduce false rejections from minor
  clock drift.
- MFA switched off by default for local testing (toggle in
  `lighthouse/routes_auth.py`).
- Added Excel roster import, PDF report export, the Administration screen,
  and the Alerts page with a simulated email outbox.
- Dashboard's provider workload table is now clickable — jumps straight to
  that provider's schedule. The Schedule page also got a provider filter
  dropdown (admin/supervising SLP) for switching between providers directly.
- Providers can now add new students (e.g. a new referral), but only to
  their own caseload — they can't assign someone else's students. The
  clinic administrator and the provider's supervising SLP get an in-app
  alert and a simulated email the moment it happens. Editing or transferring
  an *existing* student record is still admin/supervising-SLP only, per the
  spec.
- Applied the actual Lighthouse Therapy brand: navy + gold color palette
  (was a placeholder navy + teal) and a lighthouse mark (was a plain "L")
  used in the sidebar, login screen, and browser tab icon.
