class Context:
    """Per-request context: db handle + authenticated user (or None)."""

    def __init__(self, db, user=None, session_token=None):
        self.db = db
        self.user = user  # sqlite3.Row or None
        self.session_token = session_token

    @property
    def role(self):
        return self.user["role"] if self.user else None

    @property
    def user_id(self):
        return self.user["id"] if self.user else None

    def require_role(self, *roles):
        from .errors import forbidden
        if self.role not in roles:
            raise forbidden(f"Requires role: {' or '.join(roles)}")

    def visible_provider_ids(self):
        """Provider ids this user is allowed to see data for."""
        if self.role == "admin":
            rows = self.db.execute("SELECT id FROM users WHERE role='provider'").fetchall()
            return [r["id"] for r in rows]
        if self.role == "supervising_slp":
            rows = self.db.execute(
                "SELECT id FROM users WHERE role='provider' AND supervising_slp_id=?", (self.user_id,)
            ).fetchall()
            return [r["id"] for r in rows]
        if self.role == "provider":
            ids = {self.user_id}
            from .db import now_iso
            today = now_iso()[:10]
            rows = self.db.execute(
                "SELECT original_provider_id FROM temporary_coverage "
                "WHERE covering_provider_id=? AND start_date<=? AND end_date>=?",
                (self.user_id, today, today),
            ).fetchall()
            for r in rows:
                ids.add(r["original_provider_id"])
            return list(ids)
        return []
