"""Rules-only claims/refunds and reconciliation. Supplier promises are not cash."""
from datetime import timedelta
from contextlib import nullcontext
from sqlalchemy import select, func
from packages.domain.errors import DomainError, IntegrationError
from packages.domain.pricing import krw
from packages.infrastructure.models import Claim, Order, Refund, Settlement, Payment, SupplierOrder
from packages.infrastructure.security import fingerprint
from packages.infrastructure.db import aware
from .commerce import context, transition
from .common import lock_treasury, audit, review, enqueue
from .finance import post
from .supplier_operations import intervention
from packages.infrastructure.models import SupplierCancellationRecovery

CATEGORIES = {"ROTTEN", "BROKEN", "BRUISED", "WRONG_ITEM", "MISSING_WEIGHT", "DELIVERY_DELAY", "CHANGE_OF_MIND",
              "TASTE_COMPLAINT", "ADDRESS_ERROR", "MISSING_ITEM", "OTHER"}
QUALITY = {"ROTTEN", "BROKEN", "BRUISED", "MISSING_WEIGHT"}
EVIDENCE = {"parcel_label", "entire_contents", "damage_closeup"}

class AfterSales:
    def __init__(self, commerce):
        self.c = commerce
        self.factory, self.settings, self.registry = commerce.factory, commerce.settings, commerce.registry

    def open_claim(self, order_id, external_id, category, amount, evidence, *, actor='system', operational=False, session=None):
        krw(amount)
        if category not in CATEGORIES or amount <= 0 or not 1 <= len(external_id) <= 120:
            raise DomainError("INVALID_CLAIM", 422)
        if not isinstance(evidence, list) or not set(evidence).issubset(EVIDENCE):
            raise DomainError("INVALID_EVIDENCE_REFERENCE", 422)
        evidence = sorted(set(evidence))
        with (nullcontext(session) if session is not None else self.factory.begin()) as s:
            lock_treasury(s)
            prior = s.scalar(select(Claim).where(Claim.external_id == external_id))
            if prior:
                if (prior.order_id, prior.category, prior.requested_amount, prior.evidence) != (order_id, category, amount, evidence):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return prior.id
            order = s.get(Order, order_id)
            if order is None or order.delivered_at is None: raise DomainError("CLAIM_REQUIRES_DELIVERY")
            if s.scalar(select(Settlement.id).where(Settlement.order_id == order_id)):
                raise DomainError("POST_SETTLEMENT_CLAIM_REQUIRES_MANUAL_RECONCILIATION")
            if amount > order.gross_sale-order.discount: raise DomainError("REFUND_EXCEEDS_SALE")
            supplier = context(s, order)[2]
            deadline = aware(order.delivered_at) + timedelta(days=supplier.claim_days)
            state = "READY"
            if self.c.clock() > deadline or category in {"TASTE_COMPLAINT", "OTHER", "CHANGE_OF_MIND"}:
                state = "MANUAL_REVIEW"
            elif category in QUALITY and not EVIDENCE.issubset(evidence): state = "EVIDENCE_REQUIRED"
            claim = Claim(order_id=order_id, external_id=external_id, category=category, status=state,
                requested_amount=amount, evidence=evidence, deadline=deadline)
            s.add(claim); s.flush()
            audit(s, "CLAIM_OPENED", claim.id, actor=actor, new={"category": category, "status": state}, correlation_id=order.correlation_id)
            if state == "READY" and not operational: enqueue(s, "claim.submit", f"claim:{claim.id}", {"claim_id": claim.id})
            elif state == "READY": pass  # Operator records the actual external supplier response.
            else: review(s, "AMBIGUOUS_CLAIM" if state == "MANUAL_REVIEW" else "CLAIM_EVIDENCE_REQUIRED", claim.id,
                         {"required": sorted(EVIDENCE) if category in QUALITY else [], "deadline": deadline.isoformat()})
            return claim.id

    def submit_claim(self, claim_id):
        with self.factory() as s:
            claim = s.get(Claim, claim_id)
            if claim.status != "READY": return
            supplier = context(s, s.get(Order, claim.order_id))[2]
            payload = {"claim_id": claim.id, "category": claim.category, "evidence_kinds": claim.evidence}
            mode = supplier.mode
        self.registry.supplier(mode).invoke("submit_claim", payload, f"claim:{claim_id}")
        with self.factory.begin() as s:
            lock_treasury(s); claim = s.get(Claim, claim_id)
            if claim.status == "READY": claim.status = "SUPPLIER_REVIEW"
            audit(s, "SUPPLIER_CLAIM_SUBMITTED", claim.id, correlation_id=s.get(Order, claim.order_id).correlation_id)

    def supplier_response(self, claim_id, accepted_amount, accepted, actor="supplier", *, operational=False, session=None):
        krw(accepted_amount)
        with (nullcontext(session) if session is not None else self.factory.begin()) as s:
            lock_treasury(s); claim = s.get(Claim, claim_id)
            if claim is None: raise DomainError("CLAIM_NOT_FOUND", 404)
            response = "ACCEPTED" if accepted else "REJECTED"
            if claim.supplier_response:
                if claim.supplier_response != response or claim.supplier_accepted_amount != accepted_amount:
                    raise DomainError("SUPPLIER_RESPONSE_CONFLICT")
                return
            if claim.status not in ({"READY", "SUPPLIER_REVIEW"} if operational else {"SUPPLIER_REVIEW"}): raise DomainError("CLAIM_NOT_SUBMITTED")
            payment = s.scalar(select(Payment).where(Payment.order_id == claim.order_id, Payment.status == "SUCCEEDED"))
            if accepted_amount > claim.requested_amount or (payment and accepted_amount > payment.amount) or (not accepted and accepted_amount):
                raise DomainError("INVALID_SUPPLIER_RECOVERY")
            claim.supplier_response, claim.supplier_accepted_amount = response, accepted_amount
            claim.status = "REFUND_ELIGIBLE" if accepted else "MANUAL_REVIEW"
            if not accepted: review(s, "SUPPLIER_REJECTED_CLAIM", claim.id)
            if actor not in {"supplier", "system"}:
                intervention(s, "SUPPLIER_CLAIM_RESPONSE_RECORDED_MANUALLY", f"claim-response:{claim.id}",
                    actor, self.c.clock(), order=s.get(Order, claim.order_id))
            audit(s, "SUPPLIER_CLAIM_RESPONSE", claim.id, actor=actor, new={"response": response, "accepted_amount": accepted_amount}, correlation_id=s.get(Order, claim.order_id).correlation_id)

    def confirm_supplier_recovery(self, claim_id, amount, receipt_id, actor="operator", *, session=None):
        """A confirmed supplier deposit credit, not merely an accepted claim."""
        krw(amount)
        if amount <= 0 or not receipt_id: raise DomainError("CONFIRMED_RECEIPT_REQUIRED")
        with (nullcontext(session) if session is not None else self.factory.begin()) as s:
            lock_treasury(s); claim = s.get(Claim, claim_id)
            if claim.supplier_recovery:
                if claim.supplier_recovery != amount: raise DomainError("RECOVERY_CONFLICT")
                return
            if amount > claim.supplier_accepted_amount: raise DomainError("RECOVERY_EXCEEDS_ACCEPTED")
            order = s.get(Order, claim.order_id); supplier = context(s, order)[2]
            paid = s.scalar(select(Payment.amount).where(Payment.order_id == order.id, Payment.status == "SUCCEEDED")) or 0
            recovered = s.scalar(select(func.coalesce(func.sum(Claim.supplier_recovery), 0)).where(Claim.order_id == order.id))
            recovered += s.scalar(select(func.coalesce(func.sum(SupplierCancellationRecovery.amount), 0)).join(
                Payment, SupplierCancellationRecovery.payment_id == Payment.id).where(Payment.order_id == order.id))
            if recovered + amount > paid: raise DomainError("RECOVERY_EXCEEDS_SUPPLIER_PAYMENT")
            post(s, f"supplier-recovery:{supplier.id}:{receipt_id}", "SUPPLIER_RECOVERY",
                 {f"DEPOSIT:{supplier.id}": amount, "SUPPLIER_RECOVERY": -amount}, order.id, order.correlation_id)
            claim.supplier_recovery = amount
            intervention(s, "SUPPLIER_RECOVERY_CONFIRMED_MANUALLY", f"recovery-confirmed:{claim.id}",
                actor, self.c.clock(), order=order, supplier_id=supplier.id)
            audit(s, "SUPPLIER_RECOVERY_CONFIRMED", claim.id, actor=actor,
                new={"amount": amount, "receipt_hash": fingerprint(receipt_id)}, correlation_id=order.correlation_id)

    def request_refund(self, claim_id, amount, key, actor=None, *, operational=False, session=None):
        krw(amount)
        if amount <= 0 or not key or len(key) > 160: raise DomainError("INVALID_REFUND")
        with (nullcontext(session) if session is not None else self.factory.begin()) as s:
            lock_treasury(s)
            prior = s.scalar(select(Refund).where(Refund.business_key == key))
            if prior:
                if prior.claim_id != claim_id or prior.amount != amount: raise DomainError("IDEMPOTENCY_CONFLICT")
                return prior.id
            claim = s.get(Claim, claim_id)
            if claim is None: raise DomainError('CLAIM_NOT_FOUND', 404)
            order = s.get(Order, claim.order_id)
            if s.scalar(select(Settlement).where(Settlement.order_id == order.id)):
                raise DomainError("POST_SETTLEMENT_REFUND_REQUIRES_MANUAL_RECONCILIATION")
            if claim.status not in {"REFUND_ELIGIBLE", "MANUAL_REVIEW", "PARTIALLY_REFUNDED", "REFUNDED"}: raise DomainError("CLAIM_NOT_REFUNDABLE")
            total = s.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.order_id == order.id,
                Refund.status.in_(["PENDING", "SENDING", "UNKNOWN", "SUCCEEDED", "MANUAL_APPROVAL", "EVIDENCE_PENDING"])))
            claim_total = s.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.claim_id == claim.id,
                Refund.status.in_(["PENDING", "SENDING", "UNKNOWN", "SUCCEEDED", "MANUAL_APPROVAL", "EVIDENCE_PENDING"])))
            if total + amount > order.gross_sale-order.discount or claim_total + amount > claim.requested_amount:
                raise DomainError("REFUND_EXCEEDS_SALE_OR_CLAIM")
            manual = (amount > self.settings.auto_refund_limit or claim.status == "MANUAL_REVIEW") and not actor
            row = Refund(claim_id=claim.id, order_id=order.id, business_key=key, amount=amount,
                         status="EVIDENCE_PENDING" if operational else "MANUAL_APPROVAL" if manual else "PENDING")
            s.add(row); s.flush()
            if operational: pass  # Evidence of an already completed refund never dispatches money.
            elif manual: review(s, "REFUND_APPROVAL", row.id, {"amount": amount})
            else: enqueue(s, "refund.execute", f"refund:{row.id}", {"refund_id": row.id})
            if actor:
                intervention(s, "CLAIM_REFUND_APPROVED_MANUALLY", f"refund-approved:{row.id}",
                    actor, self.c.clock(), order=order)
                audit(s, "REFUND_APPROVED", row.id, actor=actor, new={"amount": amount}, correlation_id=order.correlation_id)
            return row.id

    def execute_refund(self, refund_id):
        with self.factory.begin() as s:
            lock_treasury(s); row = s.get(Refund, refund_id)
            if row.status in {"SUCCEEDED", "MANUAL_APPROVAL", "UNKNOWN", "EVIDENCE_PENDING"}: return
            if row.status == "SENDING":
                row.status = "UNKNOWN"; review(s, "REFUND_RESULT_UNKNOWN", row.id); return
            order = s.get(Order, row.order_id)
            row.status = "SENDING"
            payload = {"order_id": order.external_id, "line_id": order.external_line_id, "amount": row.amount}
            channel, key = order.marketplace, row.business_key
        try:
            receipt = self.registry.marketplace(channel).invoke("refund", payload, key)
        except IntegrationError:
            with self.factory.begin() as s:
                lock_treasury(s); row = s.get(Refund, refund_id); row.status = "UNKNOWN"
                review(s, "REFUND_RESULT_UNKNOWN", row.id)
            return
        with self.factory.begin() as s:
            lock_treasury(s); row = s.get(Refund, refund_id)
            if row.status == "SUCCEEDED": return
            order = s.get(Order, row.order_id); claim = s.get(Claim, row.claim_id)
            # Marketplace-mediated refund is deducted from receivables, NOT also bank cash.
            post(s, f"refund:{row.id}", "CUSTOMER_REFUND", {"REFUND_EXPENSE": row.amount,
                "MARKETPLACE_RECEIVABLE": -row.amount}, order.id, order.correlation_id)
            row.status, row.provider_reference = "SUCCEEDED", receipt["reference"]
            claim.customer_refund += row.amount
            claim.status = "REFUNDED" if claim.customer_refund == claim.requested_amount else "PARTIALLY_REFUNDED"
            audit(s, "REFUND_CREATED", row.id, new={"amount": row.amount}, correlation_id=order.correlation_id)

    def reconcile_settlement(self, order_id, external_id, actual, adjustment=0, tolerance=100, actor=None, *, session=None):
        krw(actual)
        if isinstance(adjustment, bool) or not isinstance(adjustment, int) or abs(adjustment) > 10**9:
            raise DomainError("INVALID_ADJUSTMENT")
        if tolerance < 0: raise DomainError("INVALID_TOLERANCE")
        hashed = fingerprint([order_id, external_id, actual, adjustment])
        with (nullcontext(session) if session is not None else self.factory.begin()) as s:
            lock_treasury(s)
            existing = s.scalar(select(Settlement).where(Settlement.order_id == order_id))
            if existing:
                if existing.input_hash != hashed: raise DomainError("SETTLEMENT_CONFLICT")
                return existing.id
            order = s.get(Order, order_id)
            if order.state != "DELIVERED": raise DomainError("SETTLEMENT_REQUIRES_DELIVERY")
            unsettled_refund = s.scalar(select(Refund.id).where(Refund.order_id == order.id, Refund.status != "SUCCEEDED"))
            if unsettled_refund: raise DomainError("PENDING_REFUND_RECONCILIATION")
            refunded = int(s.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.order_id == order.id, Refund.status == "SUCCEEDED")))
            expected = order.gross_sale-order.discount-order.fee-order.promotion_cost-refunded+adjustment
            if expected < 0: raise DomainError("NEGATIVE_SETTLEMENT_REQUIRES_MANUAL_RECONCILIATION")
            row = Settlement(order_id=order_id, external_id=external_id, expected=expected, actual=actual,
                             difference=actual-expected, adjustment=adjustment, input_hash=hashed)
            s.add(row); s.flush()
            if adjustment:
                post(s, f"adjustment:{row.id}", "MARKETPLACE_ADJUSTMENT", {"MARKETPLACE_RECEIVABLE": adjustment,
                    "SETTLEMENT_VARIANCE": -adjustment}, order.id, order.correlation_id)
            if actual or expected:
                post(s, f"settlement:{row.id}", "SETTLEMENT_STATEMENT", {"SETTLEMENT_CLEARING": actual,
                    "MARKETPLACE_RECEIVABLE": -expected, "SETTLEMENT_VARIANCE": expected-actual}, order.id, order.correlation_id)
            transition(s, order, "SETTLEMENT_PENDING")
            if abs(row.difference) > tolerance: review(s, "SETTLEMENT_ANOMALY", row.id, {"expected": expected, "actual": actual, "difference": row.difference})
            if actor:
                intervention(s, "SETTLEMENT_RECONCILED_MANUALLY", f"settlement-reconciled:{row.id}",
                    actor, self.c.clock(), order=order)
            audit(s, "SETTLEMENT_RECONCILED", row.id, actor=actor or "system", new={"expected": expected, "actual": actual}, correlation_id=order.correlation_id)
            return row.id

    def confirm_settlement_cash(self, settlement_id, receipt_id, actor="operator", *, session=None):
        if not receipt_id: raise DomainError("CONFIRMED_RECEIPT_REQUIRED")
        with (nullcontext(session) if session is not None else self.factory.begin()) as s:
            lock_treasury(s); row = s.get(Settlement, settlement_id)
            if row.confirmed_cash: return
            order = s.get(Order, row.order_id)
            if row.actual:
                post(s, f"bank-settlement:{receipt_id}", "BANK_SETTLEMENT", {"BANK": row.actual,
                    "SETTLEMENT_CLEARING": -row.actual}, order.id, order.correlation_id)
            row.confirmed_cash = True; transition(s, order, "SETTLED")
            open_claim = s.scalar(select(Claim.id).where(Claim.order_id == order.id, Claim.status != "REFUNDED"))
            if row.difference == 0 and not open_claim: transition(s, order, "CLOSED")
            intervention(s, "SETTLEMENT_CASH_CONFIRMED_MANUALLY", f"settlement-cash:{row.id}",
                actor, self.c.clock(), order=order)
            audit(s, "SETTLEMENT_CASH_CONFIRMED", row.id, actor=actor, correlation_id=order.correlation_id)

    def claim_metrics(self, s, supplier_product_id, days=30):
        from packages.infrastructure.models import MarketplaceListing
        since = self.c.clock() - timedelta(days=days)
        ids = list(s.scalars(select(Order.id).join(MarketplaceListing, Order.listing_id == MarketplaceListing.id).where(
            MarketplaceListing.supplier_product_id == supplier_product_id, Order.delivered_at >= since)))
        if not ids: return {"sample_size": 0, "claim_rate": None, "seller_loss_per_order": None, "window_days": days}
        rows = list(s.scalars(select(Claim).where(Claim.order_id.in_(ids))))
        total_loss = sum(max(0, r.customer_refund-r.supplier_recovery) for r in rows)
        return {"sample_size": len(ids), "claim_rate": len({r.order_id for r in rows})/len(ids),
            "supplier_accepted_claim_rate": sum(r.supplier_response == "ACCEPTED" for r in rows)/len(rows) if rows else None,
            "seller_loss_per_order": total_loss/len(ids), "refund_loss": total_loss, "window_days": days,
            "method": "claims for delivered-order cohort; confirmed recovery only", "last_updated": self.c.clock().isoformat()}
