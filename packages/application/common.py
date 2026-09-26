from sqlalchemy import select
from packages.domain.errors import DomainError
from packages.infrastructure.models import Account, AuditEvent, Command, Job, Review
from packages.infrastructure.security import fingerprint
from packages.infrastructure.schema_v1 import uid


def lock_treasury(s):
    """Global, fixed-order money mutex. PostgreSQL only; SQLite is single-process test mode."""
    row = s.scalar(select(Account).where(Account.code == "CONTROL").with_for_update())
    if row is None:
        raise DomainError("DATABASE_NOT_INITIALIZED", 503)
    return row


def audit(s, event: str, entity_id: str, *, actor="system", old=None, new=None,
          reason="RULE", source="application", correlation_id=None):
    s.add(AuditEvent(actor=actor, event=event, entity_id=entity_id,
        old_value=old or {}, new_value=new or {}, reason=reason, source=source,
        correlation_id=correlation_id or uid()))


def review(s, category: str, entity_id: str, details=None, key=None):
    key = key or f"{category}:{entity_id}"
    row = s.scalar(select(Review).where(Review.dedupe_key == key))
    if row is None:
        row = Review(dedupe_key=key, category=category, entity_id=entity_id, details=details or {}, status="OPEN")
        s.add(row)
        s.flush()
        if category != "JOB_DEAD_LETTER":
            enqueue(s, "notification.send", f"notify:{row.id}", {"category":category, "entity_id":entity_id, "idempotency_key":f"notify:{row.id}"})
    else:
        if row.status == "RESOLVED":
            audit(s, "REVIEW_REOPENED", row.id, old={"resolution_code": row.resolution_code}, reason=category)
            row.resolution_code = row.resolved_by = row.resolved_at = None
        row.status = "OPEN"
    return row


def enqueue(s, kind: str, key: str, payload: dict, at=None):
    existing = s.scalar(select(Job).where(Job.business_key == key))
    if existing:
        if existing.kind != kind or fingerprint(existing.payload) != fingerprint(payload):
            raise DomainError("IDEMPOTENCY_CONFLICT")
        return existing
    job = Job(kind=kind, business_key=key, payload=payload)
    if at is not None:
        job.next_run_at = at
    s.add(job)
    s.flush()
    return job


def execute_command(s, scope: str, key: str, payload: dict, action):
    if not key or len(key) > 160:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", 422)
    hashed = fingerprint(payload)
    existing = s.scalar(select(Command).where(Command.scope == scope, Command.key == key))
    if existing:
        if existing.payload_hash != hashed:
            raise DomainError("IDEMPOTENCY_CONFLICT")
        return existing.result
    result = action()
    s.add(Command(scope=scope, key=key, payload_hash=hashed, result=result))
    s.flush()
    return result
