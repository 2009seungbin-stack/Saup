"""PostgreSQL durable queue worker: bounded retries, leases, fencing and dead letters."""
import argparse
import json
import logging
import time
from datetime import timedelta
from sqlalchemy import select, or_, and_
from packages.domain.errors import DomainError, IntegrationError
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.infrastructure.schema_v1 import now, uid
from packages.infrastructure.models import Job, Heartbeat
from packages.application.common import lock_treasury, review, audit
from packages.application.catalog import inventory_guard
from packages.application.commerce import Commerce
from packages.application.after_sales import AfterSales
from packages.application.files import Files

LOG = logging.getLogger("saup.worker")

class Worker:
    def __init__(self, commerce):
        self.c, self.factory, self.settings = commerce, commerce.factory, commerce.settings
        self.after = AfterSales(commerce); self.files = Files(commerce)
        self.handlers = {"order.process": self.c.process_order, "supplier.submit": self.c.submit_supplier,
            "supplier.cancel": self.c.cancel_supplier, "payment.execute": self.c.execute_payment,
            "marketplace.shipment": self.c.sync_shipment, "listing.sync": self.c.sync_listing,
            "file.import": self.files.process, "claim.submit": self.after.submit_claim, "refund.execute": self.after.execute_refund,
            "notification.send": self.c.registry.notification.send}

    def tick(self):
        current = now()
        with self.factory.begin() as s:
            row = s.scalar(select(Job).where(or_(
                and_(Job.status == "PENDING", Job.next_run_at <= current),
                and_(Job.status == "RUNNING", Job.lease_until < current)))
                .order_by(Job.next_run_at, Job.created_at).with_for_update(skip_locked=True).limit(1))
            if row is None: return False
            if row.attempts >= self.settings.max_job_attempts:
                row.status = "DEAD"; row.last_error = "ATTEMPTS_EXHAUSTED"
                review(s, "JOB_DEAD_LETTER", row.id, {"kind": row.kind}); return True
            row.status, row.lease_until, row.lease_token = "RUNNING", current+timedelta(seconds=120), uid()
            row.attempts += 1
            job_id, token, kind, payload = row.id, row.lease_token, row.kind, row.payload
        error = None
        try:
            handler = self.handlers.get(kind)
            if handler is None: raise DomainError("UNKNOWN_JOB_KIND")
            handler(**payload)
        except (DomainError, IntegrationError) as exc: error = exc
        except Exception:
            # Avoid logging exception messages/trace locals containing PII or SQL values.
            LOG.error(json.dumps({"event":"job_unexpected_error", "job_id":job_id, "kind":kind}))
            error = IntegrationError("UNEXPECTED_HANDLER_ERROR", retryable=False)
        with self.factory.begin() as s:
            lock_treasury(s); row = s.get(Job, job_id)
            if row.lease_token != token: return True  # A newer lease owns completion.
            row.lease_until = None
            if error is None:
                row.status, row.last_error = "DONE", None
            else:
                row.last_error = error.code
                retry = isinstance(error, IntegrationError) and error.retryable and not error.uncertain
                if retry and row.attempts < self.settings.max_job_attempts:
                    row.status = "PENDING"
                    row.next_run_at = now() + timedelta(seconds=min(300, 2**row.attempts))
                else:
                    row.status = "DEAD"
                    review(s, "JOB_DEAD_LETTER", row.id, {"kind":kind, "code":error.code})
                audit(s, "JOB_FAILED", row.id, reason=error.code, new={"attempts":row.attempts, "status":row.status})
        return True

    def maintenance(self):
        with self.factory.begin() as s:
            lock_treasury(s)
            heartbeat = s.scalar(select(Heartbeat).where(Heartbeat.worker == "commerce-worker"))
            if heartbeat: heartbeat.last_seen = now()
            else: s.add(Heartbeat(worker="commerce-worker", last_seen=now()))
            inventory_guard(s, self.settings)
            from packages.application.risk import guard_cash_and_claims
            guard_cash_and_claims(s, self.c)

    def drain(self, limit=200):
        count = 0
        while count < limit and self.tick(): count += 1
        return count

    def replay(self, job_id, actor):
        with self.factory.begin() as s:
            lock_treasury(s); row = s.get(Job, job_id)
            if row is None or row.status != "DEAD": raise DomainError("JOB_NOT_REPLAYABLE")
            if row.kind not in {"listing.sync", "marketplace.shipment", "file.import", "claim.submit"}:
                raise DomainError("FINANCIAL_OR_ORDER_REPLAY_REQUIRES_RECONCILIATION")
            row.status, row.attempts, row.next_run_at = "PENDING", 0, now()
            audit(s, "JOB_REPLAY_REQUESTED", row.id, actor=actor)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser=argparse.ArgumentParser(); parser.add_argument("--once",action="store_true"); parser.add_argument("--drain",action="store_true")
    args=parser.parse_args(); settings=Settings(); _, factory=database(settings.database_url)
    worker=Worker(Commerce(settings,factory))
    if args.once: worker.tick(); return
    if args.drain: print(json.dumps({"jobs_processed":worker.drain()})); return
    last=0
    while True:
        if time.monotonic()-last>30: worker.maintenance(); last=time.monotonic()
        if not worker.tick(): time.sleep(1)

if __name__ == "__main__": main()
