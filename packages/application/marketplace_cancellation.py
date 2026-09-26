"""Phase 11B: customer/marketplace cancellation reconciliation after full supplier recovery.

This records evidence that the marketplace ALREADY refunded the customer in
full and issued a final, zero seller-side cancellation statement, rechecks every
invariant under the treasury lock, and only then moves Order CANCEL_REQUESTED ->
CANCELLED. It never sends money, calls a marketplace, enqueues refund jobs,
releases the SPENT reservation, restores inventory, or changes Payment,
SupplierOrder, SupplierCancellation or the supplier recovery.

Accounting: the supported path is pre-shipment, and sale/receivable recognition
happens only at delivery. MARKETPLACE_RECEIVABLE therefore never contained this
order, and the marketplace reversed the customer charge before any seller
payout. Posting the delivered-order CUSTOMER_REFUND journal would drive the
receivable negative and double count an external refund, so the evidence is
operational only and no journal is posted. Any order already carrying other
accounting (sale, refund, settlement) is rejected rather than interpreted.

Scope is one fulfillment line. A marketplace order with another line fails
closed; parent/multi-line reconciliation is future work.
"""
from sqlalchemy import select
from types import SimpleNamespace
from packages.domain.errors import DomainError
from packages.domain.marketplace_cancellation import (
    MarketplaceRefundReceipt, MarketplaceCancellationStatementInput, MarketplaceCancellationCompletion,
    CancellationStatementCorrection)
from packages.infrastructure.models import (
    Review, Order, Payment, Reservation, SupplierOrder, SupplierCancellation, SupplierCancellationRecovery,
    SupplierPaymentEvidence, SupplierEvidenceRevision, Shipment, Claim, Refund, Settlement, Journal,
    MarketplaceRefundEvidence, MarketplaceCancellationStatement, MarketplaceCancellationReconciliation, CancellationStatementRevision,
    OperationalReceipt, SettlementRevision,
)
from packages.infrastructure.security import fingerprint
from .common import audit, review
from .order_rules import transition
from .supplier_operations import intervention, resolve_reviews

CUSTOMER = "MARKETPLACE_CANCELLATION_RECONCILIATION_REQUIRED"
RESIDUAL = "MARKETPLACE_CANCELLATION_RESIDUAL_SETTLEMENT"
LATE_LINE = "MARKETPLACE_LINE_AFTER_CANCELLATION_EVIDENCE"
ACTION = "COMPLETE_MARKETPLACE_CANCELLATION_RECONCILIATION"
ZERO, UNSUPPORTED = "ZERO_SELLER_SETTLEMENT", "UNSUPPORTED_RESIDUAL_SETTLEMENT"
# The only journals the supported pre-shipment path may carry for this order.
EXPECTED_JOURNALS = {"SUPPLIER_PAYMENT", "SUPPLIER_RECOVERY"}
# Open reviews that describe exactly the situation this command reconciles.
RESOLVED_BY_COMPLETION = ("CANCELLATION_AFTER_PAYMENT",)
SETTLEMENT_FIELDS = ("seller_payout_amount", "seller_debit_amount", "retained_fee_amount", "outstanding_balance")


class MarketplaceCancellationService:
    def __init__(self, resolution):
        self.r, self.c = resolution, resolution.c

    def _context(self, s, row):
        """Re-derive every invariant from current rows. Earlier successful commands prove nothing now."""
        order = self.r.get(s, Order, row.entity_id)
        recovery_id = (row.details or {}).get("supplier_recovery_id")
        recovery = s.get(SupplierCancellationRecovery, recovery_id) if recovery_id else None
        if recovery is None:
            raise DomainError("SUPPLIER_RECOVERY_REQUIRED")
        p = s.get(Payment, recovery.payment_id)
        cancel = s.get(SupplierCancellation, recovery.cancellation_id)
        so = s.get(SupplierOrder, cancel.supplier_order_id) if cancel else None
        if p is None or so is None or p.order_id != order.id or so.order_id != order.id or p.supplier_order_id != so.id:
            raise DomainError("SUPPLIER_RECOVERY_ORDER_MISMATCH")
        if cancel.status != "FINANCIALLY_RECONCILED":
            raise DomainError("SUPPLIER_FINANCIAL_RECOVERY_INCOMPLETE")
        if so.status != "CANCELLED":
            raise DomainError("SUPPLIER_ORDER_NOT_CANCELLED")
        if p.status != "SUCCEEDED":
            raise DomainError("PAYMENT_NOT_SUCCEEDED")
        reservation = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
        if (reservation is None or reservation.status != "SPENT" or
                reservation.bank_amount + reservation.deposit_amount != p.amount):
            raise DomainError("RESERVATION_NOT_SPENT")
        intent = self.r.ops.intent(s, so)
        if (recovery.amount != p.amount or recovery.bank_amount != reservation.bank_amount or
                recovery.deposit_amount != reservation.deposit_amount or recovery.supplier_id != intent.supplier_id or
                p.amount != intent.amount or p.amount != so.amount or order.cost_snapshot != intent.amount):
            raise DomainError("SUPPLIER_RECOVERY_NOT_FULL_OR_SNAPSHOT_CHANGED")
        journal = s.get(Journal, recovery.journal_id)
        if journal is None or journal.kind != "SUPPLIER_RECOVERY" or journal.order_id != order.id:
            raise DomainError("SUPPLIER_RECOVERY_JOURNAL_MISSING")
        if not order.cancel_requested or order.state != "CANCEL_REQUESTED":
            raise DomainError("ORDER_NOT_CANCEL_REQUESTED")
        if order.delivered_at is not None:
            raise DomainError("ORDER_ALREADY_DELIVERED")
        for cls, code in ((Shipment, "ORDER_ALREADY_SHIPPED"), (Claim, "CLAIM_PRESENT"),
                          (Refund, "OTHER_CUSTOMER_REFUND_PRESENT"), (Settlement, "SETTLEMENT_PRESENT")):
            if s.scalar(select(cls.id).where(cls.order_id == order.id)):
                raise DomainError(code)
        kinds = list(s.scalars(select(Journal.kind).where(Journal.order_id == order.id)))
        if sorted(kinds) != sorted(EXPECTED_JOURNALS):
            raise DomainError("UNSUPPORTED_ORDER_ACCOUNTING")
        if s.scalar(select(Order.id).where(Order.marketplace == order.marketplace,
                Order.external_id == order.external_id, Order.id != order.id)):
            raise DomainError("MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED")
        required = order.gross_sale - order.discount
        if required <= 0:
            raise DomainError("CUSTOMER_REFUND_BASIS_INVALID")
        proofs = list(s.scalars(select(SupplierPaymentEvidence.id).where(SupplierPaymentEvidence.payment_id == p.id)))
        entities = {order.id, so.id, p.id, cancel.id, recovery.id, *proofs}
        if s.scalar(select(Review.id).where(Review.entity_id.in_(entities), Review.status != "RESOLVED",
                Review.id != row.id, Review.category.not_in(RESOLVED_BY_COMPLETION))):
            raise DomainError("CONFLICTING_UNRESOLVED_REVIEW")
        snapshot = {"review_id": row.id, "order_id": order.id, "marketplace": order.marketplace,
            "external_order_id": order.external_id, "external_line_id": order.external_line_id,
            "customer_refund_amount": required, "gross_sale": order.gross_sale, "discount": order.discount,
            "payment_id": p.id, "payment_amount": p.amount, "supplier_order_id": so.id,
            "supplier_cancellation_id": cancel.id, "supplier_recovery_id": recovery.id, "recovery_amount": recovery.amount}
        return {"order": order, "payment": p, "supplier_order": so, "cancellation": cancel, "recovery": recovery,
                "required": required, "snapshot": snapshot | {"snapshot_hash": fingerprint(snapshot)}}

    @staticmethod
    def _snapshot(ctx, value):
        if value != ctx["snapshot"]["snapshot_hash"]:
            raise DomainError("MARKETPLACE_CANCELLATION_SNAPSHOT_MISMATCH")

    @staticmethod
    def _identity(record, order):
        return (record.marketplace, record.external_order_id, record.external_line_id) == (
            order.marketplace, order.external_id, order.external_line_id)

    def _check_records(self, ctx, refund, statement=None):
        """Recorded evidence must still describe exactly the current order economics."""
        order, current = ctx["order"], ctx["snapshot"]["snapshot_hash"]
        if (refund.order_id != order.id or not self._identity(refund, order) or refund.snapshot_hash != current or
                refund.supplier_recovery_id != ctx["recovery"].id or refund.amount != ctx["required"]):
            raise DomainError("REFUND_EVIDENCE_SNAPSHOT_CHANGED")
        if statement is not None and (statement.order_id != order.id or statement.refund_evidence_id != refund.id or
                not self._identity(statement, order) or statement.snapshot_hash != current or
                statement.customer_refund_amount != ctx["required"]):
            raise DomainError("STATEMENT_SNAPSHOT_CHANGED")

    def _evidence_unused(self, s, ctx, model, reference, evidence_hash):
        """Customer refund/statement evidence cannot reuse any other money evidence."""
        for cls in (OperationalReceipt, SettlementRevision, CancellationStatementRevision, MarketplaceRefundEvidence, MarketplaceCancellationStatement, SupplierCancellationRecovery,
                    SupplierPaymentEvidence, SupplierEvidenceRevision):
            if s.scalar(select(cls.id).where(cls.evidence_hash == evidence_hash)):
                raise DomainError("MARKETPLACE_EVIDENCE_HASH_IN_USE")
        if s.scalar(select(model.id).where(model.marketplace == ctx["order"].marketplace, model.reference == reference)):
            raise DomainError("MARKETPLACE_EVIDENCE_REFERENCE_IN_USE")
        # A supplier receipt or outgoing payment proof is never proof that the customer was refunded.
        p = ctx["payment"]
        proofs = list(s.scalars(select(SupplierPaymentEvidence).where(SupplierPaymentEvidence.payment_id == p.id)))
        revisions = list(s.scalars(select(SupplierEvidenceRevision).where(
            SupplierEvidenceRevision.evidence_id.in_([x.id for x in proofs])))) if proofs else []
        if reference in {ctx["recovery"].reference, p.provider_reference, *(x.reference for x in [*proofs, *revisions])}:
            raise DomainError("SUPPLIER_EVIDENCE_IS_NOT_CUSTOMER_REFUND")

    @staticmethod
    def _business(cmd):
        payload = cmd.model_dump(exclude={"idempotency_key"})
        if payload.get('expected_statement_revision') == 0:
            payload.pop('expected_statement_revision')
        return fingerprint(payload)

    @staticmethod
    def _refund_view(x):
        return {"refund_evidence_id": x.id, "review_id": x.review_id, "order_id": x.order_id,
                "supplier_recovery_id": x.supplier_recovery_id, "customer_refund_amount": x.amount}

    @staticmethod
    def _statement_view(x):
        return {"statement_id": x.id, "review_id": x.review_id, "order_id": x.order_id,
                "refund_evidence_id": x.refund_evidence_id, "classification": x.classification,
                "completion_allowed": x.classification == ZERO}

    @staticmethod
    def effective_statement(s, statement):
        if statement is None: return None
        latest = s.scalar(select(CancellationStatementRevision).where(CancellationStatementRevision.statement_id == statement.id)
            .order_by(CancellationStatementRevision.revision.desc()).limit(1))
        data = {column.name: getattr(statement, column.name) for column in statement.__table__.columns}
        data['revision'] = 0
        if latest:
            data.update(latest.values)
            data.update(reference=latest.reference, evidence_hash=latest.evidence_hash, actor=latest.actor,
                        recorded_at=latest.created_at, revision=latest.revision)
        return SimpleNamespace(**data)

    def correct_statement(self, review_id, raw, actor):
        actor.require('admin'); cmd = CancellationStatementCorrection.model_validate(raw)
        def action(s):
            row = self.r._open_review(s, review_id, CUSTOMER)
            ctx = self._context(s, row); self._snapshot(ctx, cmd.snapshot_hash)
            original = self.r.get(s, MarketplaceCancellationStatement, cmd.statement_id)
            if original.review_id != row.id or original.order_id != ctx['order'].id:
                raise DomainError('STATEMENT_NOT_FOR_THIS_REVIEW')
            current = self.effective_statement(s, original)
            if current.revision != cmd.expected_revision: raise DomainError('STALE_STATEMENT_REVISION')
            refund = self.r.get(s, MarketplaceRefundEvidence, original.refund_evidence_id)
            self._check_records(ctx, refund, current)
            if cmd.refund_evidence_id != refund.id or cmd.customer_refund_amount != refund.amount:
                raise DomainError('STATEMENT_CUSTOMER_REFUND_MISMATCH')
            self._evidence_unused(s, ctx, MarketplaceCancellationStatement, cmd.reference, cmd.evidence_hash)
            if s.scalar(select(CancellationStatementRevision.id).where(CancellationStatementRevision.reference == cmd.reference)):
                raise DomainError('MARKETPLACE_EVIDENCE_REFERENCE_IN_USE')
            values = {k: getattr(cmd, k) for k in ('customer_refund_amount', *SETTLEMENT_FIELDS)}
            values['classification'] = UNSUPPORTED if cmd.residual() else ZERO
            version = CancellationStatementRevision(statement_id=original.id, review_id=row.id, order_id=original.order_id,
                revision=current.revision+1, values=values, reason=cmd.reason, reference=cmd.reference,
                evidence_hash=cmd.evidence_hash, actor=actor.username)
            s.add(version); s.flush()
            resolve_reviews(s, original.id, [RESIDUAL], actor.username, self.c.clock(), 'STATEMENT_CORRECTED')
            if cmd.residual(): review(s, RESIDUAL, original.id, values | {'revision': version.revision})
            audit(s, 'CANCELLATION_STATEMENT_CORRECTED', original.order_id, actor=actor.username,
                new={'statement_id': original.id, 'revision_id': version.id, **values}, reason=cmd.reason,
                correlation_id=ctx['order'].correlation_id)
            intervention(s, 'CANCELLATION_STATEMENT_CORRECTED', f'cancel-statement:{version.id}', actor.username, self.c.clock(), order=ctx['order'])
            return {'statement_id': original.id, 'revision': version.revision, 'classification': values['classification']}
        return self.r._command('review.marketplace-statement-correct', cmd, review_id, actor, action)

    def record_refund(self, review_id, raw, actor):
        actor.require("admin"); cmd = MarketplaceRefundReceipt.model_validate(raw)
        def action(s):
            prior = s.scalar(select(MarketplaceRefundEvidence).where(MarketplaceRefundEvidence.review_id == review_id))
            if prior:
                if prior.payload_hash != self._business(cmd):
                    raise DomainError("MARKETPLACE_REFUND_EVIDENCE_CONFLICT")
                return self._refund_view(prior)
            row = self.r._open_review(s, review_id, CUSTOMER)
            ctx = self._context(s, row); order = ctx["order"]
            self._snapshot(ctx, cmd.snapshot_hash)
            if cmd.supplier_recovery_id != ctx["recovery"].id:
                raise DomainError("SUPPLIER_RECOVERY_MISMATCH")
            if (cmd.marketplace, cmd.external_order_id, cmd.external_line_id) != (
                    order.marketplace, order.external_id, order.external_line_id):
                raise DomainError("MARKETPLACE_ORDER_IDENTITY_MISMATCH")
            if cmd.customer_refund_amount != ctx["required"]:
                raise DomainError("FULL_CUSTOMER_REFUND_REQUIRED")
            self._evidence_unused(s, ctx, MarketplaceRefundEvidence, cmd.reference, cmd.evidence_hash)
            record = MarketplaceRefundEvidence(review_id=row.id, order_id=order.id, supplier_recovery_id=ctx["recovery"].id,
                marketplace=order.marketplace, external_order_id=order.external_id, external_line_id=order.external_line_id,
                amount=cmd.customer_refund_amount, reference=cmd.reference, evidence_hash=cmd.evidence_hash,
                snapshot_hash=cmd.snapshot_hash, payload_hash=self._business(cmd), actor=actor.username,
                recorded_at=self.c.clock())
            s.add(record); s.flush()
            audit(s, "MARKETPLACE_CUSTOMER_REFUND_EVIDENCE_RECORDED", order.id, actor=actor.username,
                new={"refund_evidence_id": record.id, "amount": record.amount, "reference_hash": fingerprint(cmd.reference),
                     "evidence_hash": cmd.evidence_hash, "money_sent": False}, correlation_id=order.correlation_id)
            intervention(s, "MARKETPLACE_REFUND_EVIDENCE_RECORDED_MANUALLY", f"marketplace-refund:{record.id}",
                actor.username, self.c.clock(), order=order)
            return self._refund_view(record)
        return self.r._command("review.marketplace-refund", cmd, review_id, actor, action)

    def record_statement(self, review_id, raw, actor):
        actor.require("admin"); cmd = MarketplaceCancellationStatementInput.model_validate(raw)
        def action(s):
            prior = s.scalar(select(MarketplaceCancellationStatement).where(MarketplaceCancellationStatement.review_id == review_id))
            if prior:
                if prior.payload_hash != self._business(cmd):
                    raise DomainError("MARKETPLACE_STATEMENT_CONFLICT")
                return self._statement_view(prior)
            row = self.r._open_review(s, review_id, CUSTOMER)
            ctx = self._context(s, row); order = ctx["order"]
            self._snapshot(ctx, cmd.snapshot_hash)
            refund = s.get(MarketplaceRefundEvidence, cmd.refund_evidence_id)
            if refund is None or refund.review_id != row.id or refund.order_id != order.id:
                raise DomainError("REFUND_EVIDENCE_NOT_FOR_THIS_ORDER")
            self._check_records(ctx, refund)
            if cmd.customer_refund_amount != refund.amount:
                raise DomainError("STATEMENT_CUSTOMER_REFUND_MISMATCH")
            self._evidence_unused(s, ctx, MarketplaceCancellationStatement, cmd.reference, cmd.evidence_hash)
            classification = UNSUPPORTED if cmd.residual() else ZERO
            record = MarketplaceCancellationStatement(review_id=row.id, order_id=order.id, refund_evidence_id=refund.id,
                marketplace=order.marketplace, external_order_id=order.external_id, external_line_id=order.external_line_id,
                customer_refund_amount=cmd.customer_refund_amount, classification=classification,
                **{k: getattr(cmd, k) for k in SETTLEMENT_FIELDS}, reference=cmd.reference, evidence_hash=cmd.evidence_hash,
                snapshot_hash=cmd.snapshot_hash, payload_hash=self._business(cmd), actor=actor.username,
                recorded_at=self.c.clock())
            s.add(record); s.flush()
            if classification == UNSUPPORTED:
                # Retain the external evidence and require explicit financial reconciliation.
                # The customer review stays open and the order is NOT closed.
                review(s, RESIDUAL, record.id, {"order_id": order.id, "customer_review_id": row.id,
                    **{k: getattr(cmd, k) for k in SETTLEMENT_FIELDS}})
            audit(s, "MARKETPLACE_CANCELLATION_STATEMENT_RECORDED", order.id, actor=actor.username,
                new={"statement_id": record.id, "classification": classification,
                     **{k: getattr(cmd, k) for k in SETTLEMENT_FIELDS}, "reference_hash": fingerprint(cmd.reference),
                     "money_sent": False}, correlation_id=order.correlation_id)
            intervention(s, "MARKETPLACE_STATEMENT_RECORDED_MANUALLY", f"marketplace-statement:{record.id}",
                actor.username, self.c.clock(), order=order)
            return self._statement_view(record)
        return self.r._command("review.marketplace-statement", cmd, review_id, actor, action)

    def complete(self, review_id, raw, actor):
        actor.require("admin"); cmd = MarketplaceCancellationCompletion.model_validate(raw)
        def action(s):
            prior = s.scalar(select(MarketplaceCancellationReconciliation).where(
                MarketplaceCancellationReconciliation.review_id == review_id))
            if prior:
                if prior.payload_hash != self._business(cmd):
                    raise DomainError("MARKETPLACE_RECONCILIATION_CONFLICT")
                from packages.infrastructure.models import ReviewResolution
                done = s.scalar(select(ReviewResolution).where(ReviewResolution.business_key == f"{ACTION}:{review_id}"))
                return {"resolution_id": done.id, "review_id": review_id, **done.result}
            row = self.r._open_review(s, review_id, CUSTOMER)
            ctx = self._context(s, row); order = ctx["order"]
            self._snapshot(ctx, cmd.snapshot_hash)
            refund = s.scalar(select(MarketplaceRefundEvidence).where(MarketplaceRefundEvidence.review_id == row.id))
            if refund is None:
                raise DomainError("CUSTOMER_REFUND_EVIDENCE_REQUIRED")
            statement = s.scalar(select(MarketplaceCancellationStatement).where(MarketplaceCancellationStatement.review_id == row.id))
            if statement is None:
                raise DomainError("MARKETPLACE_STATEMENT_REQUIRED")
            statement = self.effective_statement(s, statement)
            if cmd.expected_statement_revision != statement.revision:
                raise DomainError('STALE_STATEMENT_REVISION')
            if cmd.refund_evidence_id != refund.id or cmd.statement_id != statement.id:
                raise DomainError("STALE_RECONCILIATION_EVIDENCE")
            self._check_records(ctx, refund, statement)
            if statement.classification != ZERO or any(getattr(statement, k) for k in SETTLEMENT_FIELDS):
                raise DomainError("UNSUPPORTED_RESIDUAL_SETTLEMENT")
            before = order.state
            transition(s, order, "CANCELLED", "MARKETPLACE_CANCELLATION_RECONCILED")
            record = MarketplaceCancellationReconciliation(review_id=row.id, order_id=order.id,
                refund_evidence_id=refund.id, statement_id=statement.id, supplier_recovery_id=ctx["recovery"].id,
                payment_id=ctx["payment"].id, customer_refund_amount=refund.amount, order_state_before=before,
                order_state_after=order.state, snapshot_hash=cmd.snapshot_hash, payload_hash=self._business(cmd),
                actor=actor.username, completed_at=self.c.clock())
            s.add(record); s.flush()
            resolve_reviews(s, order.id, list(RESOLVED_BY_COMPLETION), actor.username, self.c.clock(), ACTION)
            audit(s, "MARKETPLACE_CANCELLATION_RECONCILED", order.id, actor=actor.username,
                new={"reconciliation_id": record.id, "order_state": order.state, "payment_status": ctx["payment"].status,
                     "money_sent": False, "journal_posted": False}, correlation_id=order.correlation_id)
            intervention(s, "MARKETPLACE_CANCELLATION_RECONCILED_MANUALLY", f"marketplace-reconciled:{record.id}",
                actor.username, self.c.clock(), order=order)
            return self.r._resolved(s, row, ACTION, cmd, actor, {"reconciliation_id": record.id, "order_id": order.id,
                "order_state": order.state, "payment_status": ctx["payment"].status,
                "refund_evidence_id": refund.id, "statement_id": statement.id, "statement_revision": statement.revision})
        return self.r._command("review.marketplace-complete", cmd, review_id, actor, action)

    def detail(self, s, row):
        """Operator-safe projection. No PII, ciphertext or free-text notes."""
        refund = s.scalar(select(MarketplaceRefundEvidence).where(MarketplaceRefundEvidence.review_id == row.id))
        statement = s.scalar(select(MarketplaceCancellationStatement).where(MarketplaceCancellationStatement.review_id == row.id))
        original = statement
        statement = self.effective_statement(s, statement)
        done = s.scalar(select(MarketplaceCancellationReconciliation).where(MarketplaceCancellationReconciliation.review_id == row.id))
        records = {
            "refund_evidence": refund and {"id": refund.id, "amount": refund.amount, "reference": refund.reference,
                "evidence_hash": refund.evidence_hash, "actor": refund.actor, "recorded_at": refund.recorded_at},
            "statement": statement and {"id": statement.id, "revision": statement.revision, "customer_refund_amount": statement.customer_refund_amount,
                **{k: getattr(statement, k) for k in SETTLEMENT_FIELDS}, "classification": statement.classification,
                "reference": statement.reference, "evidence_hash": statement.evidence_hash, "actor": statement.actor,
                "recorded_at": statement.recorded_at},
            "reconciliation": done and {"id": done.id, "order_state_after": done.order_state_after, "actor": done.actor,
                "completed_at": done.completed_at}}
        records['statement_history'] = ([{'revision': 0, 'reference': original.reference,
            **{k: getattr(original, k) for k in ('customer_refund_amount', *SETTLEMENT_FIELDS)}}] + [
            {'revision': x.revision, 'reference': x.reference, 'reason': x.reason, **x.values}
            for x in s.scalars(select(CancellationStatementRevision).where(CancellationStatementRevision.statement_id == original.id)
                .order_by(CancellationStatementRevision.revision))]) if original else []
        result = {"eligible": False, "blocked_reason": None, "snapshot": None, "next_action": None,
                  "marketplace_cancellation": records, "money_sent": False}
        if row.status == "RESOLVED":
            return result | {"stage": "RESOLVED", "blocked_reason": "REVIEW_ALREADY_RESOLVED"}
        try:
            ctx = self._context(s, row)
            if refund:
                self._check_records(ctx, refund, statement)
        except DomainError as exc:
            return result | {"stage": "BLOCKED", "blocked_reason": exc.code}
        result["snapshot"] = ctx["snapshot"] | {"supplier_recovery_complete": True}
        if statement and statement.classification != ZERO:
            return result | {"stage": "BLOCKED_UNSUPPORTED_RESIDUAL_SETTLEMENT", "blocked_reason": UNSUPPORTED}
        stage, step = (("CUSTOMER_REFUND_EVIDENCE_MISSING", "RECORD_MARKETPLACE_REFUND") if not refund else
                       ("MARKETPLACE_STATEMENT_MISSING", "RECORD_MARKETPLACE_STATEMENT") if not statement else
                       ("READY_FOR_COMPLETION", "COMPLETE_MARKETPLACE_CANCELLATION"))
        return result | {"stage": stage, "next_action": step, "eligible": True}
