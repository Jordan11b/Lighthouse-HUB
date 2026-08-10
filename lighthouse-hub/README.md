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

MFA is **on** — after entering a password, you'll be asked for a 6-digit
code (not an authenticator app; there's no separate setup step). Until SMTP
is configured (Administration → Settings → Email delivery), that code is
printed to the server's console instead of actually emailed, so check there
if you're testing locally without email set up. To turn MFA back off, set
`MFA_REQUIRED = False` at the top of `lighthouse/routes_auth.py`.

To start over with a clean database: delete `data/lighthouse.db` and reseed.

## What's built (the daily-use spine)

- **Auth & accounts**: invite-only (admin creates accounts, no public
  signup), password + required MFA (a 6-digit code emailed at login, with a
  resend option, 10-minute expiry, and a 5-attempt lockout), 30-minute
  inactivity timeout, password reset, account deactivation with "can't
  remove the last admin" protection.
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
- **Bulk caseload transfer**: on the Providers page, move a departing
  provider's entire active caseload to another provider in one action
  instead of transferring students one at a time. Future sessions still
  route through the approvals queue, same as a single transfer.
- **Duplicate/conflicting attendance protection**: if two people with
  access to the same session (e.g. the assigned provider and someone
  covering for them) record different results for the same student, the
  second save is blocked with a confirmation prompt naming who recorded
  what first, instead of silently overwriting it.
- **Student merge tool**: on a student's detail page, merge a duplicate
  record into it (e.g. from a double Excel import) — attendance, schedule,
  and makeup history move to the surviving record, and the duplicate is
  archived, not deleted. The Students list has a status filter to find
  archived/merged records again, and "Archived" is now a selectable status
  on the student form.
- **Real email delivery** (Administration → Settings → Email delivery).
  Fill in an SMTP host/username/password (or set the equivalent `SMTP_*`
  environment variables — recommended for a real deployment, since it keeps
  the password out of the database) and alerts, the daily digest, and MFA
  sign-in codes actually get emailed instead of just landing in the
  simulated outbox. There's a "Send test email to myself" button to confirm
  it's working. Nothing is required to keep using the app exactly as
  before — if it's not configured, everything falls back to the simulated
  outbox automatically.
- **Per-user notification email** (My Account → Notification email). Anyone
  can point their alerts and sign-in codes at a different inbox than the one
  they log in with. Login itself always uses the account email regardless.

## What's still deferred

- **A real scheduler for the daily/weekly alert checks.** The timing logic
  (90/60/30/14-day IEP warnings, weekly pace/makeup emails, daily 6am
  provider digest) is fully built — see "Run alert check now" on the
  Alerts page — and will really email people once SMTP is configured (see
  above), but nothing runs it automatically yet. That's a cron job /
  `launchd` timer / hosting-platform cron feature pointed at the
  `run-check` endpoint, not built here since it depends on where this ends
  up hosted.
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
before go-live. **MFA is on** (see "Demo logins" above) — make sure SMTP is
configured before real people rely on it, since without email set up the
sign-in code only shows up in the server console, not their inbox.

## Going live (deploying to Render)

Right now this only runs on whichever computer has the terminal open. Putting
it somewhere always-on that the whole clinic can reach takes two parts: get
the code onto GitHub, then point Render at it.

### 1. Put the code on GitHub (no command line needed)

1. Go to [github.com](https://github.com) and create a free account if you
   don't have one.
2. Click **New repository**. Name it `lighthouse-hub`, keep it **Private**,
   and click **Create repository**.
3. On the empty repo page, click **uploading an existing file**.
4. Drag the entire contents of the `lighthouse-hub` folder (not the folder
   itself — the files and subfolders inside it: `server.py`, `lighthouse/`,
   `web/`, `render.yaml`, etc.) into the upload box, then click **Commit
   changes**.

### 2. Create the Render service

1. Go to [render.com](https://render.com) and sign up (you can use your
   GitHub account to sign in, which also connects them automatically).
2. Click **New +** → **Blueprint**, and select the `lighthouse-hub` repo you
   just created. Render will read `render.yaml` from the repo and pre-fill a
   web service with a 1GB persistent disk already attached — review it and
   click **Apply**.
   - If you don't see the Blueprint option, or it doesn't pick up the file,
     use **New +** → **Web Service** instead, pick the repo, and set:
     **Runtime**: Python 3, **Build Command**: (leave blank), **Start
     Command**: `python3 server.py`. Then, after it's created, go to the
     service's **Disks** tab and add a disk (1 GB is plenty) mounted at
     `/data`, and add an environment variable `LIGHTHOUSE_DATA_DIR` = `/data`
     under the **Environment** tab — this is what makes your data survive
     restarts and redeploys instead of getting wiped.
3. Render will build and start it, and give you a URL like
   `https://lighthouse-therapy-hub.onrender.com` — that's the live site.
   HTTPS is automatic; there's nothing to configure.
4. Open that URL and run the seed step once, the same way you did locally,
   by opening a **Shell** from the service's dashboard tab and running
   `python3 -m lighthouse.seed` — or just create your first real accounts by
   hand instead of seeding fictional data, which is probably what you want
   for the real thing.

### 3. Before anyone else logs in

- MFA is already on (`MFA_REQUIRED = True`) — no action needed there.
- Reset everyone's password (Administration → each account → Reset password)
  since this is a fresh database, not the one from your local testing.
- **Set up email before real people log in.** MFA is on, and without SMTP
  configured, the sign-in code only shows up in the server's console — no
  one else can see it, so they'd be locked out. Add `SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL` as
  environment variables under the service's **Environment** tab (for
  Gmail: an [app password](https://myaccount.google.com/apppasswords),
  host `smtp.gmail.com`, port `587`). Environment variables take priority
  over the Administration screen's email settings, so this is the one to
  use for a real deployment — it keeps the password out of the database.
  Confirm it worked with the "Send test email to myself" button on the
  Administration page before anyone else tries to sign in.

### 4. What Render gives you automatically vs. what's still on you

Render handles: HTTPS, restarting the app if it crashes, keeping it running
around the clock. Still worth doing yourself: back up the disk periodically
(Render's disks aren't automatically backed up on the Starter plan — check
your plan's specifics), and everything else in the "What this is / isn't"
section above still applies once real student data is involved.

## Project layout

```
lighthouse-hub/
  server.py              entry point — run this
  lighthouse/             backend: db schema, auth, business rules, API routes
  web/                     frontend: index.html, styles.css, js/ (ES modules)
  data/                    lighthouse.db lives here once you run it
  render.yaml              optional one-click Render deployment config
  requirements.txt         intentionally empty — zero dependencies
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
- Added deployment support: honors the `PORT` and `LIGHTHOUSE_DATA_DIR`
  environment variables hosting platforms set, plus a `render.yaml` for a
  one-click Render deploy. See "Going live" below.
- Fixed: group sessions (2+ students) could get the wrong overall status
  (e.g. stuck on "excused" when someone actually completed) because the
  status was recalculated after each individual student's attendance was
  saved, before the rest of the group was recorded. It now waits until
  every student in the session has an attendance entry before setting the
  session status.
- Added bulk provider caseload transfer, duplicate-attendance conflict
  protection under overlapping coverage, and a student merge/dedupe tool
  (see "What's built" above).
- iPad/Safari pass: fixed a table-overflow bug that could clip columns on
  narrower screens instead of scrolling, switched the sidebar to a
  horizontal swipeable bar below ~880px wide instead of squeezing a fixed
  220px sidebar onto a small screen, removed the viewport setting that was
  blocking pinch-to-zoom, and forced the correct MIME type on JavaScript
  files (Safari silently refuses to run ES modules served with the wrong
  type, which depends on the host OS and can vary).
- Replaced authenticator-app MFA with a 6-digit code emailed at login —
  no separate setup step (it just goes to the account's email), a "send a
  new code" option, a 10-minute expiry, and lockout after 5 wrong tries.
  The old TOTP code is still in `lighthouse/security.py` if an authenticator
  app is ever wanted as an option later, it's just not wired up anymore.
- Added real email delivery (`lighthouse/mailer.py`, stdlib `smtplib` — no
  third-party mail SDK). Configure it via environment variables or
  Administration → Settings → Email delivery; without it, everything keeps
  working exactly as before through the simulated outbox. The saved SMTP
  password is never sent back to the browser (masked in the API response),
  and a "Send test email to myself" button confirms it's working.
- Added a per-user notification email (My Account → Notification email) so
  alerts and MFA codes can go somewhere other than someone's login email.
- MFA switched back **on** by default (`MFA_REQUIRED = True`) now that it's
  a simple emailed code instead of an authenticator-app setup flow. Make
  sure SMTP is configured (see above) before anyone besides you logs in —
  otherwise the sign-in code only reaches the server console, not an inbox.
