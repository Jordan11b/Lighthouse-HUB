import json
from .db import now_iso


def log(db, actor_id, action, entity_type=None, entity_id=None, details=None):
    db.execute(
        "INSERT INTO audit_log (actor_id, action, entity_type, entity_id, details, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (actor_id, action, entity_type, entity_id, json.dumps(details) if details else None, now_iso()),
    )
