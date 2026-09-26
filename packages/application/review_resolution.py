"""Bounded review resolution, not general state forcing or a banking connector.

Every command locks treasury before any workflow read and executes atomically.
Only payment-proof metadata can be corrected. Recovery records already-received
funds for fully paid, pre-shipment supplier cancellations. The resulting customer
review is reconciled only by the separate Phase 11B marketplace commands.
"""
from sqlalchemy import select
from packages.domain.errors import DomainError
from packages.domain.review_resolution import CorrectionRequest, EvidenceCorrection, CancellationRecoveryConfirm
from packages.infrastructure.models import (
    Review, ReviewResolution, SupplierEvidenceRevision, SupplierCancellationRecovery,
    SupplierPaymentEvidence, SupplierPaymentConfirmation, SupplierCancellation,
    SupplierOrder, SupplierOrderIntent, Order, Payment, Reservation, Shipment, Claim,
    Refund, Settlement, Journal, Posting, Account,
)
from packages.infrastructure.security import fingerprint
from .common import lock_treasury, audit, review, execute_command
from .finance import post
from .payment_evidence import effective_evidence, reference_in_use
from .supplier_operations import intervention, resolve_reviews
from .marketplace_cancellation import (MarketplaceCancellationService, CUSTOMER, RESIDUAL, LATE_LINE,
    ACTION as CUSTOMER_ACTION)

CORRECTION = "SUPPLIER_PAYMENT_EVIDENCE_CORRECTION"
FINANCIAL = "SUPPLIER_CANCELLATION_FINANCIAL_REVIEW"
ACTIONS = {CORRECTION: "CORRECT_UNCONFIRMED_PAYMENT_EVIDENCE", FINANCIAL: "CONFIRM_SUPPLIER_CANCELLATION_RECOVERY",
           CUSTOMER: CUSTOMER_ACTION}
# Listed for visibility only: these have no automated resolution command.
LISTED = (CORRECTION, FINANCIAL, CUSTOMER, RESIDUAL, LATE_LINE)


class ReviewResolutionService:
    def __init__(self, commerce):
        self.c, self.factory = commerce, commerce.factory
        self.ops = commerce.supplier_operations
        self.marketplace = MarketplaceCancellationService(self)

    @staticmethod
    def get(s, model, identifier):
        obj = s.get(model, identifier)
        if obj is None:
            raise DomainError("REVIEW_RESOURCE_NOT_FOUND", 404)
        return obj

    def _command(self, scope, cmd, target, actor, fn):
        result, error = None, None
        with self.factory.begin() as s:
            lock_treasury(s)
            try:
                # Failed commands roll back ALL business effects, but retain a
                # safe rejection audit outside the savepoint.
                with s.begin_nested():
                    result = execute_command(s, scope, cmd.idempotency_key,
                        {"target": target, **cmd.model_dump()}, lambda: fn(s))
            except DomainError as exc:
                error = exc
                audit(s, "REVIEW_COMMAND_BLOCKED", target, actor=actor.username, reason=exc.code)
        if error:
            raise error
        return result

    def _unconfirmed(self, s, proof):
        p = self.get(s, Payment, proof.payment_id)
        order = self.get(s, Order, p.order_id)
        if p.status not in {"EVIDENCE_PENDING", "MANUAL_APPROVAL"} or p.dispatched_at is not None:
            raise DomainError("EVIDENCE_CORRECTION_REQUIRES_UNCONFIRMED_PAYMENT")
        if s.scalar(select(SupplierPaymentConfirmation.id).where(SupplierPaymentConfirmation.payment_id == p.id)):
            raise DomainError("CONFIRMED_EVIDENCE_IS_IMMUTABLE")
        if order.cancel_requested:
            raise DomainError("CANCELLED_EVIDENCE_REQUIRES_SEPARATE_RECONCILIATION")
        so = self.get(s, SupplierOrder, p.supplier_order_id)
        batch = self.ops.validate_payable(s, order, so)
        if batch.payment_path != "MANUAL_EVIDENCE":
            raise DomainError("PAYMENT_EVIDENCE_NOT_ALLOWED")
        intent = self.ops.intent(s, so)
        reservation = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
        if (proof.amount != p.amount or p.amount != intent.amount or proof.supplier_id != intent.supplier_id or
                proof.destination_fingerprint != p.destination_fingerprint or
                p.destination_fingerprint != intent.snapshot["destination_fingerprint"] or
                proof.bank_amount != reservation.bank_amount or proof.deposit_amount != reservation.deposit_amount):
            raise DomainError("PAYMENT_EVIDENCE_SNAPSHOT_MISMATCH")
        return p, order

    def request_correction(self, evidence_id, raw, actor):
        actor.require(); cmd = CorrectionRequest.model_validate(raw)
        def action(s):
            proof = self.get(s, SupplierPaymentEvidence, evidence_id)
            _, order = self._unconfirmed(s, proof)
            current = effective_evidence(s, proof)
            if cmd.expected_revision_id != current["revision_id"]:
                raise DomainError("STALE_EVIDENCE_REVISION")
            key = f"evidence-correction:{proof.id}:{current['version']}"
            prior = s.scalar(select(Review).where(Review.dedupe_key == key))
            if prior:
                if prior.details["reason"] != cmd.reason or prior.status == "RESOLVED":
                    raise DomainError("EVIDENCE_CORRECTION_REQUEST_CONFLICT")
                return {"review_id": prior.id, "status": prior.status}
            row = review(s, CORRECTION, proof.id, {"payment_id": proof.payment_id,
                "expected_revision_id": current["revision_id"], "reason": cmd.reason}, key=key)
            audit(s, "PAYMENT_EVIDENCE_CORRECTION_REQUESTED", proof.id, actor=actor.username,
                new={"review_id": row.id, "revision_id": current["revision_id"], "reason": cmd.reason})
            intervention(s, "PAYMENT_EVIDENCE_CORRECTION_REQUESTED", f"correction-request:{row.id}",
                actor.username, self.c.clock(), order=order, supplier_id=proof.supplier_id)
            return {"review_id": row.id, "status": row.status}
        return self._command("review.evidence-request", cmd, evidence_id, actor, action)

    def _open_review(self, s, review_id, category):
        row = self.get(s, Review, review_id)
        if row.category != category:
            raise DomainError("REVIEW_ACTION_CATEGORY_MISMATCH")
        if row.status not in {"OPEN", "ACKNOWLEDGED"}:
            raise DomainError("REVIEW_ALREADY_RESOLVED")
        return row

    def _resolved(self, s, row, action, cmd, actor, result):
        record = ReviewResolution(review_id=row.id, business_key=f"{action}:{row.id}", action=action,
            payload_hash=fingerprint(cmd.model_dump()), actor=actor.username, resolved_at=self.c.clock(), result=result)
        s.add(record); s.flush()
        row.status, row.resolution_code = "RESOLVED", action
        row.resolved_by, row.resolved_at = actor.username, self.c.clock()
        audit(s, "REVIEW_RESOLVED", row.id, actor=actor.username,
            new={"resolution_id": record.id, "resolution_code": action})
        return {"resolution_id": record.id, "review_id": row.id, **result}

    def correct_evidence(self, review_id, raw, actor):
        actor.require("admin"); cmd = EvidenceCorrection.model_validate(raw)
        def action(s):
            row = self._open_review(s, review_id, CORRECTION)
            proof = self.get(s, SupplierPaymentEvidence, row.entity_id)
            p, order = self._unconfirmed(s, proof)
            current = effective_evidence(s, proof)
            if cmd.expected_revision_id != current["revision_id"] or row.details["expected_revision_id"] != current["revision_id"]:
                raise DomainError("STALE_EVIDENCE_REVISION")
            if (cmd.reference, cmd.evidence_hash) == (current["reference"], current["evidence_hash"]):
                raise DomainError("EVIDENCE_CORRECTION_HAS_NO_CHANGE")
            reason = row.details["reason"]
            if (reason == "WRONG_REFERENCE" and cmd.evidence_hash != current["evidence_hash"] or
                    reason == "WRONG_ATTACHMENT" and cmd.reference != current["reference"]):
                raise DomainError("EVIDENCE_CORRECTION_REASON_MISMATCH")
            if reference_in_use(s, proof.supplier_id, cmd.reference, p.id):
                raise DomainError("PAYMENT_EVIDENCE_REFERENCE_IN_USE")
            revision = SupplierEvidenceRevision(evidence_id=proof.id, review_id=row.id,
                supersedes_id=current["revision_id"], revision=current["version"]+1,
                reference=cmd.reference, evidence_hash=cmd.evidence_hash, reason=reason,
                payload_hash=fingerprint(cmd.model_dump()), actor=actor.username, recorded_at=self.c.clock())
            s.add(revision); s.flush()
            audit(s, "PAYMENT_EVIDENCE_CORRECTED", proof.id, actor=actor.username,
                new={"revision_id": revision.id, "review_id": row.id, "reference_hash": fingerprint(cmd.reference),
                     "evidence_hash": cmd.evidence_hash, "economics_changed": False})
            resolve_reviews(s, p.id, ["PAYMENT_EVIDENCE_CORRECTION_REQUIRED", "STALE_EVIDENCE_REVISION"],
                actor.username, self.c.clock(), "EVIDENCE_CORRECTION_APPLIED")
            intervention(s, "PAYMENT_EVIDENCE_CORRECTED_MANUALLY", f"evidence-corrected:{revision.id}",
                actor.username, self.c.clock(), order=order, supplier_id=proof.supplier_id)
            return self._resolved(s, row, ACTIONS[CORRECTION], cmd, actor,
                {"evidence_id": proof.id, "revision_id": revision.id, "payment_id": p.id, "payment_status": p.status})
        return self._command("review.correct-evidence", cmd, review_id, actor, action)

    def _recoverable(self, s, row):
        so = self.get(s, SupplierOrder, row.entity_id)
        order = self.get(s, Order, so.order_id)
        cancel = s.scalar(select(SupplierCancellation).where(SupplierCancellation.supplier_order_id == so.id))
        p = s.scalar(select(Payment).where(Payment.supplier_order_id == so.id))
        if (not cancel or cancel.status != "FINANCIAL_REVIEW" or not cancel.confirmation_hash or
                not cancel.confirmed_at or so.status != "CANCELLED" or not order.cancel_requested or order.state != "CANCEL_REQUESTED"):
            raise DomainError("CONFIRMED_SUPPLIER_CANCELLATION_REQUIRED")
        if not p or p.status != "SUCCEEDED":
            raise DomainError("RECOVERY_REQUIRES_CONFIRMED_PAID_PAYMENT")
        # Narrow first release: no shipment/claim/settlement accounting can overlap.
        if order.delivered_at or any(s.scalar(select(cls.id).where(cls.order_id == order.id))
                for cls in (Shipment, Claim, Refund, Settlement)):
            raise DomainError("POST_SHIPMENT_RECOVERY_REQUIRES_SEPARATE_RECONCILIATION")
        intent = self.ops.intent(s, so)
        reservation = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
        if (not reservation or reservation.status != "SPENT" or reservation.supplier_id != intent.supplier_id or
                p.amount != so.amount or p.amount != intent.amount or order.cost_snapshot != intent.amount or
                p.destination_fingerprint != intent.snapshot["destination_fingerprint"] or
                reservation.bank_amount + reservation.deposit_amount != p.amount):
            raise DomainError("RECOVERY_PAYMENT_SNAPSHOT_MISMATCH")
        original = s.scalar(select(Journal).where(Journal.business_key == f"supplier-payment:{p.id}", Journal.kind == "SUPPLIER_PAYMENT"))
        expected = {k: v for k, v in {"SUPPLIER_EXPENSE": p.amount, "BANK": -reservation.bank_amount,
            f"DEPOSIT:{intent.supplier_id}": -reservation.deposit_amount}.items() if v}
        actual = dict(s.execute(select(Account.code, Posting.delta).join(Posting, Posting.account_id == Account.id)
            .where(Posting.journal_id == original.id)).all()) if original else {}
        if actual != expected or not original or original.order_id != order.id:
            raise DomainError("RECOVERY_REQUIRES_ORIGINAL_PAYMENT_JOURNAL")
        if s.scalar(select(SupplierCancellationRecovery.id).where(SupplierCancellationRecovery.payment_id == p.id)):
            raise DomainError("SUPPLIER_CANCELLATION_ALREADY_RECOVERED")
        return so, order, cancel, p, intent, reservation

    def confirm_recovery(self, review_id, raw, actor):
        actor.require("admin"); cmd = CancellationRecoveryConfirm.model_validate(raw)
        def action(s):
            row = self._open_review(s, review_id, FINANCIAL)
            so, order, cancel, p, intent, reservation = self._recoverable(s, row)
            if (cmd.supplier_id != intent.supplier_id or cmd.payment_id != p.id or cmd.amount != p.amount or
                    cmd.bank_amount != reservation.bank_amount or cmd.deposit_amount != reservation.deposit_amount or
                    cmd.amount != cmd.bank_amount+cmd.deposit_amount or cmd.destination_fingerprint != p.destination_fingerprint):
                raise DomainError("RECOVERY_SNAPSHOT_MISMATCH")
            # Outgoing payment proof must not be reused as evidence of incoming funds.
            proof = s.scalar(select(SupplierPaymentEvidence).where(SupplierPaymentEvidence.payment_id == p.id))
            if cmd.reference == p.provider_reference:
                raise DomainError("RECOVERY_RECEIPT_IS_PAYMENT_EVIDENCE")
            if proof:
                revisions = list(s.scalars(select(SupplierEvidenceRevision).where(SupplierEvidenceRevision.evidence_id == proof.id)))
                if any(cmd.reference == x.reference or cmd.evidence_hash == x.evidence_hash for x in [proof, *revisions]):
                    raise DomainError("RECOVERY_RECEIPT_IS_PAYMENT_EVIDENCE")
            # Share the existing claim-recovery receipt namespace, so one receipt
            # cannot be credited through both the legacy claim and this pathway.
            key = f"supplier-recovery:{intent.supplier_id}:{cmd.reference}"
            if s.scalar(select(Journal.id).where(Journal.business_key == key)):
                raise DomainError("SUPPLIER_RECOVERY_RECEIPT_IN_USE")
            if s.scalar(select(SupplierCancellationRecovery.id).where(SupplierCancellationRecovery.evidence_hash == cmd.evidence_hash)):
                raise DomainError("SUPPLIER_RECOVERY_EVIDENCE_IN_USE")
            journal = post(s, key, "SUPPLIER_RECOVERY", {"BANK": cmd.bank_amount,
                f"DEPOSIT:{intent.supplier_id}": cmd.deposit_amount, "SUPPLIER_RECOVERY": -cmd.amount},
                order.id, order.correlation_id)
            recovery = SupplierCancellationRecovery(cancellation_id=cancel.id, payment_id=p.id,
                supplier_id=intent.supplier_id, journal_id=journal.id, amount=cmd.amount,
                bank_amount=cmd.bank_amount, deposit_amount=cmd.deposit_amount,
                destination_fingerprint=cmd.destination_fingerprint, reference=cmd.reference,
                evidence_hash=cmd.evidence_hash, payload_hash=fingerprint(cmd.model_dump()),
                actor=actor.username, confirmed_at=self.c.clock())
            s.add(recovery); s.flush()
            cancel.status = "FINANCIALLY_RECONCILED"
            # Never release a SPENT reservation, restore guessed inventory, change
            # SUCCEEDED to CANCELLED, or pretend the customer has been refunded.
            customer = review(s, CUSTOMER, order.id, {"supplier_recovery_id": recovery.id})
            audit(s, "SUPPLIER_CANCELLATION_RECOVERY_CONFIRMED", so.id, actor=actor.username,
                new={"recovery_id": recovery.id, "journal_id": journal.id, "amount": cmd.amount,
                    "bank_amount": cmd.bank_amount, "deposit_amount": cmd.deposit_amount,
                    "supplier_id": intent.supplier_id, "receipt_hash": fingerprint(cmd.reference)})
            intervention(s, "SUPPLIER_CANCELLATION_RECOVERY_CONFIRMED_MANUALLY", f"cancellation-recovery:{recovery.id}",
                actor.username, self.c.clock(), order=order, supplier_id=intent.supplier_id)
            return self._resolved(s, row, ACTIONS[FINANCIAL], cmd, actor,
                {"recovery_id": recovery.id, "payment_id": p.id, "cancellation_status": cancel.status,
                 "order_state": order.state, "customer_review_id": customer.id})
        return self._command("review.cancellation-recovery", cmd, review_id, actor, action)

    def view(self, s, row, *, detail=False):
        result = {k: getattr(row, k) for k in ("id", "category", "entity_id", "status", "resolution_code", "resolved_by", "resolved_at", "created_at")}
        result["action"] = ACTIONS.get(row.category)
        if not detail:
            return result
        result.update({"eligible": False, "blocked_reason": None, "snapshot": None})
        if row.category == CUSTOMER:
            result.update(self.marketplace.detail(s, row))
            result["history"] = self._history(s, row)
            return result
        try:
            if row.status == "RESOLVED":
                raise DomainError("REVIEW_ALREADY_RESOLVED")
            if row.category == CORRECTION:
                proof = self.get(s, SupplierPaymentEvidence, row.entity_id)
                p, _ = self._unconfirmed(s, proof)
                result["snapshot"] = {"payment_id": p.id, "amount": p.amount, "evidence_id": proof.id,
                    "reason": row.details["reason"], **effective_evidence(s, proof)}
            elif row.category == FINANCIAL:
                _, _, _, p, intent, reservation = self._recoverable(s, row)
                result["snapshot"] = {"payment_id": p.id, "supplier_id": intent.supplier_id, "amount": p.amount,
                    "bank_amount": reservation.bank_amount, "deposit_amount": reservation.deposit_amount,
                    "destination_fingerprint": p.destination_fingerprint}
            else:
                raise DomainError("NO_AUTOMATED_RESOLUTION_FOR_CATEGORY")
            result["eligible"] = True
        except DomainError as exc:
            result["blocked_reason"] = exc.code
        result["history"] = self._history(s, row)
        return result

    @staticmethod
    def _history(s, row):
        return [{"id": x.id, "action": x.action, "actor": x.actor, "resolved_at": x.resolved_at,
            "result": x.result} for x in s.scalars(select(ReviewResolution).where(ReviewResolution.review_id == row.id)
            .order_by(ReviewResolution.created_at, ReviewResolution.id))]

    def record_marketplace_refund(self, review_id, raw, actor):
        return self.marketplace.record_refund(review_id, raw, actor)

    def record_marketplace_statement(self, review_id, raw, actor):
        return self.marketplace.record_statement(review_id, raw, actor)

    def complete_marketplace_cancellation(self, review_id, raw, actor):
        return self.marketplace.complete(review_id, raw, actor)

    def list_reviews(self, limit=100, offset=0):
        with self.factory() as s:
            return [self.view(s, x) for x in s.scalars(select(Review).where(Review.category.in_(LISTED))
                .order_by(Review.created_at.desc(), Review.id).limit(limit).offset(offset))]

    def get_review(self, review_id):
        with self.factory() as s:
            return self.view(s, self.get(s, Review, review_id), detail=True)
