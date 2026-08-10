#!/usr/bin/env python3
"""Lighthouse Therapy Hub - single-command local server.

Runs entirely on the Python standard library (http.server + sqlite3) plus
the small `lighthouse` package in this folder. No pip install required.

Usage:
    python3 server.py            # serves on http://localhost:8899
    python3 server.py 9000       # custom port
"""
import datetime
import json
import mimetypes
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lighthouse.db import init_db, get_db, now_iso
from lighthouse.app import main_router
from lighthouse.context import Context
from lighthouse.errors import ApiError

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
SESSION_TIMEOUT_MINUTES = 30


def authenticate(db, headers):
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, None
    token = auth[len("Bearer "):].strip()
    row = db.execute("SELECT * FROM sessions_auth WHERE token=?", (token,)).fetchone()
    if not row:
        return None, None
    last = datetime.datetime.fromisoformat(row["last_activity"].replace("Z", ""))
    if datetime.datetime.utcnow() - last > datetime.timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        db.execute("DELETE FROM sessions_auth WHERE token=?", (token,))
        db.commit()
        return None, None
    if not row["mfa_verified"]:
        return None, token
    db.execute("UPDATE sessions_auth SET last_activity=? WHERE token=?", (now_iso(), token))
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if not user or not user["is_active"]:
        return None, token
    return user, token


class Handler(BaseHTTPRequestHandler):
    server_version = "LighthouseHub/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, status, payload):
        if isinstance(payload, dict) and "__binary__" in payload:
            return self._send_binary(status, payload)
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_binary(self, status, payload):
        data = payload["__binary__"]
        self.send_response(status)
        self.send_header("Content-Type", payload.get("__content_type__", "application/octet-stream"))
        filename = payload.get("__filename__")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_api(self, method, parsed):
        db = get_db()
        try:
            handler, path_params, roles = main_router.match(method, parsed.path)
            if not handler:
                return self._send_json(404, {"error": "Unknown endpoint"})

            user, token = authenticate(db, self.headers)
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            path_params = path_params or {}
            path_params["_qs"] = qs

            public_paths = {"/api/auth/login", "/api/auth/mfa/verify", "/api/auth/mfa/resend"}
            if parsed.path not in public_paths:
                if user is None:
                    return self._send_json(401, {"error": "Authentication required (log in and complete MFA)"})

            ctx = Context(db, user, token)

            body = {}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return self._send_json(400, {"error": "Invalid JSON body"})

            status, payload = handler(ctx, path_params, body)
            self._send_json(status, payload)
        except ApiError as e:
            db.rollback()
            payload = {"error": e.message}
            payload.update(e.extra)
            self._send_json(e.status, payload)
        except Exception as e:  # pragma: no cover - safety net for a demo server
            db.rollback()
            sys.stderr.write(f"Unhandled error: {e!r}\n")
            import traceback
            traceback.print_exc()
            self._send_json(500, {"error": "Internal server error"})
        finally:
            db.close()

    def _handle_static(self, parsed):
        rel = parsed.path.lstrip("/")
        if rel == "" or rel == "/":
            rel = "index.html"
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(WEB_DIR):
            return self._send_json(403, {"error": "Forbidden"})
        if not os.path.isfile(full):
            full = os.path.join(WEB_DIR, "index.html")  # SPA fallback
        # Safari is strict about the MIME type on `<script type="module">` files - if the
        # host OS's mimetypes database doesn't have a JS entry (varies by system), it'll
        # serve as text/plain or octet-stream and Safari silently refuses to run it. Force
        # the right type ourselves instead of trusting the system database for this one.
        if full.endswith((".js", ".mjs")):
            ctype = "text/javascript"
        else:
            ctype, _ = mimetypes.guess_type(full)
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(method, parsed)
        else:
            self._handle_static(parsed)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")


def main():
    # Hosting platforms (Render, Railway, Heroku-style PaaS) set PORT themselves; a CLI
    # arg still works for local runs, e.g. `python3 server.py 9000`.
    if os.environ.get("PORT"):
        port = int(os.environ["PORT"])
    elif len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = 8899

    from lighthouse import db as db_module
    db_existed = os.path.exists(os.path.join(db_module.DATA_DIR, "lighthouse.db"))
    init_db()
    print("Initialized a new database." if not db_existed else "Database ready.")

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Lighthouse Therapy Hub running on port {port}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
