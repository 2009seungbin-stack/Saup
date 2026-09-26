"""Explicit human handoffs for Excel suppliers.

All commands acquire the existing treasury mutex FIRST, then validate/read/write
inside one transaction. No network request or money movement occurs here. Only
admin-confirmed evidence can attest to an already completed external payment.
Unique business keys remain the second line of concurrency defence.
"""
import base64
import hashlib
from collections import Counter
from sqlalchemy import select, func
from pydantic import ValidationError
from packages.domain.errors import DomainError
from packages.domain.supplier_operations import (
    Actor, BatchCreate, MarkSent, Acknowledge, EvidenceRecord, EvidenceConfirm,
    CancellationConfirm, Revalidate, LegacyAdopt, validate_supplier_transition,
)
from packages.infrastructure.models import (
    SupplierOrder, Supplier, SupplierExcelProfile, Order, Payment, Reservation, Review,
    SupplierOrderIntent, SupplierOrderBatch, SupplierOrderBatchItem,
    SupplierBatchAcknowledgement, SupplierPaymentEvidence, SupplierPaymentConfirmation,
    SupplierCancellation, OperationalIntervention, AuditEvent, MarketplaceListing, SupplierEvidenceConfirmationBinding,
)
from packages.infrastructure.security import fingerprint
from packages.infrastructure.schema_v1 import uid
from packages.integrations.suppliers.excel import ExcelProfile, export_orders
from .order_rules import context, transition
from .common import lock_treasury, audit, review, execute_command, enqueue
from .finance import release, settle_payment, daily_commitments, treasury, balance
from .catalog import pause_listing, inventory_guard
from .risk import guard_cash_and_claims
from .payment_evidence import effective_evidence, correction_pending, reference_in_use


def supplier_transition(s, so, target, *, actor="system", reason="RULE"):
    validate_supplier_transition(so.status, target)
    if so.status == target:
        return
    before = so.status
    so.status = target
    audit(s, "SUPPLIER_ORDER_TRANSITION", so.id, actor=actor,
          old={"status": before}, new={"status": target}, reason=reason)


def intervention(s, category, key, actor, at, *, order=None, batch_id=None, supplier_id=None):
    prior = s.scalar(select(OperationalIntervention).where(OperationalIntervention.business_key == key))
    if prior is not None:
        return
    s.add(OperationalIntervention(business_key=key, category=category, actor=actor,
        order_id=order.id if order else None, batch_id=batch_id, supplier_id=supplier_id, recorded_at=at))
    if order is not None:
        order.human_interventions += 1


def resolve_reviews(s, entity_id, categories, actor, at, code):
    """Called ONLY after a typed business command has satisfied its invariant."""
    for row in s.scalars(select(Review).where(Review.entity_id == entity_id,
            Review.category.in_(categories), Review.status != "RESOLVED")):
        row.status, row.resolution_code = "RESOLVED", code
        row.resolved_by, row.resolved_at = actor, at
        audit(s, "REVIEW_RESOLVED", row.id, actor=actor, new={"resolution_code": code})


class SupplierOperations:
    def __init__(self, commerce):
        self.c, self.factory = commerce, commerce.factory

    @staticmethod
    def get(s, model, identifier):
        obj = s.get(model, identifier)
        if obj is None:
            raise DomainError("SUPPLIER_RESOURCE_NOT_FOUND", 404)
        return obj

    @staticmethod
    def active_item(s, so_id):
        return s.scalar(select(SupplierOrderBatchItem).where(
            SupplierOrderBatchItem.supplier_order_id == so_id, SupplierOrderBatchItem.active.is_(True)))

    @staticmethod
    def items(s, batch_id):
        return list(s.scalars(select(SupplierOrderBatchItem).where(
            SupplierOrderBatchItem.batch_id == batch_id).order_by(SupplierOrderBatchItem.position)))

    def freeze_intent(self, s, order, so):
        _, sp, supplier, _ = context(s, order)
        original = self.c.cipher.decrypt(order.pii_ciphertext)["original_address"]
        snapshot = {"supplier_sku": sp.supplier_sku, "supplier_product_id": sp.id,
            "unit_cost": sp.cost, "shipping": sp.shipping, "quantity": order.quantity,
            "amount": so.amount, "address_hash": fingerprint(original), "input_hash": order.input_hash,
            "destination_fingerprint": supplier.destination_fingerprint,
            "marketplace_order_id": order.external_id}
        row = SupplierOrderIntent(supplier_order_id=so.id, supplier_id=supplier.id,
            amount=so.amount, snapshot=snapshot, snapshot_hash=fingerprint(snapshot))
        s.add(row)
        audit(s, "SUPPLIER_ORDER_INTENT_CREATED", so.id,
            new={"supplier_id": supplier.id, "amount": so.amount, "snapshot_hash": row.snapshot_hash})
        return row

    def intent(self, s, so):
        row = s.scalar(select(SupplierOrderIntent).where(SupplierOrderIntent.supplier_order_id == so.id))
        if row is None:
            raise DomainError("LEGACY_SUPPLIER_STATE_UNVERIFIED")
        if fingerprint(row.snapshot) != row.snapshot_hash:
            raise DomainError("SUPPLIER_INTENT_INTEGRITY_ERROR")
        return row

    def validate_frozen(self, s, order, so):
        intent = self.intent(s, so)
        _, sp, supplier, _, _ = self.c.validate_order(s, order, already_reserved=True)
        snap = intent.snapshot
        original = self.c.cipher.decrypt(order.pii_ciphertext)["original_address"]
        if supplier.id != intent.supplier_id or sp.id != snap["supplier_product_id"]:
            raise DomainError("SUPPLIER_IDENTITY_CHANGED")
        if (so.amount != intent.amount or order.cost_snapshot != intent.amount or
                sp.cost != snap["unit_cost"] or sp.shipping != snap["shipping"] or
                order.quantity != snap["quantity"] or sp.supplier_sku != snap["supplier_sku"] or
                order.external_id != snap["marketplace_order_id"] or order.input_hash != snap["input_hash"] or
                fingerprint(original) != snap["address_hash"]):
            raise DomainError("SUPPLIER_FROZEN_TERMS_CHANGED")
        if not supplier.destination_approved or not supplier.destination_fingerprint:
            raise DomainError("DESTINATION_NOT_WHITELISTED")
        if supplier.destination_fingerprint != snap["destination_fingerprint"]:
            raise DomainError("DESTINATION_CHANGED")
        reservation = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
        if (reservation is None or reservation.status != "HELD" or
                reservation.supplier_id != supplier.id or
                reservation.bank_amount + reservation.deposit_amount != intent.amount):
            raise DomainError("PAYMENT_RESERVATION_MISMATCH")
        position = treasury(s, self.c.settings, supplier.id)
        if position["free_bank"] < 0 or position["supplier_deposit"] < position["supplier_deposit_committed"]:
            raise DomainError("INSUFFICIENT_CASH")
        return intent, reservation

    def validate_payable(self, s, order, so):
        item = self.active_item(s, so.id)
        if item is None or item.ack_status != "ACCEPTED" or item.accepted_amount != so.amount:
            raise DomainError("SUPPLIER_ACK_REQUIRED")
        batch = self.get(s, SupplierOrderBatch, item.batch_id)
        if batch.sent_at is None or batch.acknowledged_at is None:
            raise DomainError("SUPPLIER_ACK_REQUIRED")
        if so.status not in {"ACKNOWLEDGED", "PAYMENT_PENDING"}:
            raise DomainError("SUPPLIER_ORDER_NOT_PAYABLE")
        if order.state != "SUPPLIER_ORDERED":
            raise DomainError("ORDER_NOT_PAYABLE")
        self.validate_frozen(s, order, so)
        return batch

    def create_batch(self, raw, actor: Actor):
        actor.require()
        cmd = BatchCreate.model_validate(raw)
        ids = sorted(cmd.supplier_order_ids)
        if len(ids) != len(set(ids)):
            raise DomainError("DUPLICATE_BATCH_ORDER", 422)
        if cmd.payment_path == "DEMO_PROVIDER" and self.c.settings.app_mode not in {"test", "demo"}:
            raise DomainError("DEMO_DISABLED", 403)
        payload = cmd.model_dump(); payload["supplier_order_ids"] = ids
        with self.factory.begin() as s:
            lock_treasury(s)
            def action():
                supplier = self.get(s, Supplier, cmd.supplier_id)
                profile = self.get(s, SupplierExcelProfile, cmd.profile_id)
                if profile.supplier_id != supplier.id or supplier.mode != "excel" or not supplier.active:
                    raise DomainError("BATCH_SUPPLIER_PROFILE_MISMATCH")
                mapping = ExcelProfile.model_validate(profile.mapping)
                orders, rows, intents = [], [], []
                for identifier in ids:
                    so = self.get(s, SupplierOrder, identifier)
                    order = self.get(s, Order, so.order_id)
                    intent = self.intent(s, so)
                    if intent.supplier_id != supplier.id:
                        raise DomainError("CROSS_SUPPLIER_BATCH")
                    if order.cancel_requested or order.state != "SUPPLIER_ORDER_PENDING" or so.status != "PENDING":
                        raise DomainError("SUPPLIER_ORDER_NOT_BATCHABLE")
                    if self.active_item(s, so.id) is not None:
                        raise DomainError("SUPPLIER_ORDER_ALREADY_BATCHED")
                    self.validate_frozen(s, order, so)
                    rows.append({"supplier_order_id": so.id, "marketplace_order_id": order.external_id,
                        "supplier_sku": intent.snapshot["supplier_sku"], "quantity": intent.snapshot["quantity"],
                        **self.c.cipher.decrypt(order.pii_ciphertext)["original_address"]})
                    orders.append((so, order)); intents.append(intent)
                data = export_orders(mapping, rows)
                batch_id = uid()
                batch = SupplierOrderBatch(id=batch_id, supplier_id=supplier.id, profile_id=profile.id,
                    profile_version=profile.version, profile_snapshot=mapping.model_dump(mode="json"),
                    payment_path=cmd.payment_path, status="FILE_READY", order_count=len(rows),
                    file_name=f"supplier-batch-{batch_id}.xlsx", file_hash=hashlib.sha256(data).hexdigest(),
                    file_ciphertext=self.c.cipher.encrypt(base64.b64encode(data).decode()),
                    generated_at=self.c.clock(), generated_by=actor.username)
                s.add(batch); s.flush()
                for index, ((so, order), row, intent) in enumerate(zip(orders, rows, intents)):
                    supplier_transition(s, so, "BATCHED", actor=actor.username)
                    supplier_transition(s, so, "FILE_READY", actor=actor.username)
                    s.add(SupplierOrderBatchItem(batch_id=batch.id, supplier_id=supplier.id,
                        supplier_order_id=so.id, position=index, active=True,
                        row_ciphertext=self.c.cipher.encrypt(row), snapshot_hash=intent.snapshot_hash))
                    intervention(s, "SUPPLIER_BATCH_CREATED", f"batch-created:{batch.id}:{so.id}", actor.username,
                        self.c.clock(), order=order, batch_id=batch.id, supplier_id=supplier.id)
                audit(s, "SUPPLIER_BATCH_CREATED", batch.id, actor=actor.username,
                    new={"supplier_id": supplier.id, "profile_id": profile.id, "profile_version": profile.version,
                         "order_count": len(rows), "file_hash": batch.file_hash, "payment_path": batch.payment_path})
                return {"id": batch.id}
            result = execute_command(s, "supplier.batch.create", cmd.idempotency_key, payload, action)
            return self.batch_view(s, self.get(s, SupplierOrderBatch, result["id"]), detail=True)

    def batch_view(self, s, batch, *, detail=False):
        joined = list(s.execute(select(SupplierOrderBatchItem, SupplierOrder, Payment, SupplierPaymentEvidence)
            .join(SupplierOrder, SupplierOrder.id == SupplierOrderBatchItem.supplier_order_id)
            .outerjoin(Payment, Payment.supplier_order_id == SupplierOrder.id)
            .outerjoin(SupplierPaymentEvidence, SupplierPaymentEvidence.payment_id == Payment.id)
            .where(SupplierOrderBatchItem.batch_id == batch.id).order_by(SupplierOrderBatchItem.position)))
        items = [row[0] for row in joined]
        states = Counter(so.status for _, so, _, _ in joined)
        lines = []
        if detail:
            for item, so, payment, evidence in joined:
                lines.append({"supplier_order_id": so.id, "order_id": so.order_id, "status": so.status,
                    "active": item.active, "ack_status": item.ack_status, "rejection_reason": item.rejection_reason,
                    "amount": so.amount, "payment_id": payment.id if payment else None,
                    "payment_status": payment.status if payment else None, "evidence_id": evidence.id if evidence else None})
        result = {"id": batch.id, "supplier_id": batch.supplier_id, "profile_id": batch.profile_id,
            "profile_version": batch.profile_version, "status": batch.status, "order_count": batch.order_count,
            "payment_path": batch.payment_path, "file_hash": batch.file_hash,
            "generated_at": batch.generated_at, "exported_at": batch.exported_at, "sent_at": batch.sent_at,
            "acknowledged_at": batch.acknowledged_at,
            "acknowledgement_state": "RECORDED" if batch.acknowledged_at else ("ACK_PENDING" if batch.sent_at else "NOT_SENT"),
            "accepted_count": sum(i.ack_status == "ACCEPTED" for i in items),
            "rejected_count": sum(i.ack_status == "REJECTED" for i in items),
            "review_count": sum(i.ack_status == "MANUAL_REVIEW" for i in items),
            "payment_pending_count": states["ACKNOWLEDGED"] + states["PAYMENT_PENDING"],
            "shipment_pending_count": states["SHIPMENT_PENDING"]}
        if detail:
            result["items"] = lines
        return result

    def list_batches(self, *, limit=100, offset=0):
        if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
            raise DomainError("INVALID_PAGINATION", 422)
        with self.factory() as s:
            return [self.batch_view(s, batch) for batch in s.scalars(select(SupplierOrderBatch)
                .order_by(SupplierOrderBatch.created_at.desc(), SupplierOrderBatch.id).limit(limit).offset(offset))]

    def get_batch(self, batch_id):
        with self.factory() as s:
            return self.batch_view(s, self.get(s, SupplierOrderBatch, batch_id), detail=True)

    def candidates(self):
        with self.factory() as s:
            return [{"id": so.id, "order_id": so.order_id, "supplier_id": intent.supplier_id,
                     "amount": so.amount, "status": so.status}
                    for so, intent in s.execute(select(SupplierOrder, SupplierOrderIntent)
                    .join(SupplierOrderIntent, SupplierOrderIntent.supplier_order_id == SupplierOrder.id)
                    .where(SupplierOrder.status == "PENDING").order_by(SupplierOrder.id).limit(500))]

    def export_batch(self, batch_id, actor: Actor):
        actor.require()
        with self.factory.begin() as s:
            lock_treasury(s)
            batch = self.get(s, SupplierOrderBatch, batch_id)
            if batch.status in {"INVALIDATED", "CANCELLED", "CANCEL_PENDING"}:
                raise DomainError("BATCH_FILE_INVALIDATED")
            data = base64.b64decode(self.c.cipher.decrypt(batch.file_ciphertext), validate=True)
            if hashlib.sha256(data).hexdigest() != batch.file_hash:
                raise DomainError("BATCH_FILE_INTEGRITY_ERROR")
            if batch.exported_at is None:
                batch.exported_at, batch.exported_by = self.c.clock(), actor.username
                if batch.status == "FILE_READY":
                    batch.status = "EXPORTED"
                for item in self.items(s, batch.id):
                    so = self.get(s, SupplierOrder, item.supplier_order_id)
                    if so.status == "FILE_READY":
                        supplier_transition(s, so, "EXPORTED", actor=actor.username)
                    intervention(s, "SUPPLIER_FILE_EXPORTED", f"file-exported:{batch.id}:{so.id}", actor.username,
                        self.c.clock(), order=self.get(s, Order, so.order_id), batch_id=batch.id, supplier_id=batch.supplier_id)
            # Every PII download is audited, including repeat downloads. Business
            # transitions/interventions occur once, access events occur each time.
            audit(s, "SUPPLIER_BATCH_FILE_EXPORTED", batch.id, actor=actor.username,
                  new={"file_hash": batch.file_hash, "order_count": batch.order_count}, reason="PII_EXPORT")
            return data, batch.file_name

    def mark_sent(self, batch_id, raw, actor: Actor):
        actor.require(); cmd = MarkSent.model_validate(raw)
        hashed = fingerprint(cmd.model_dump())
        with self.factory.begin() as s:
            lock_treasury(s)
            batch = self.get(s, SupplierOrderBatch, batch_id)
            if batch.send_hash:
                if batch.send_hash != hashed:
                    raise DomainError("SUPPLIER_SEND_CONFLICT")
                return self.batch_view(s, batch, detail=True)
            if batch.status not in {"FILE_READY", "EXPORTED"} or cmd.file_hash != batch.file_hash:
                raise DomainError("BATCH_NOT_SENDABLE")
            batch.sent_at, batch.sent_by = self.c.clock(), actor.username
            batch.send_channel, batch.send_reference = cmd.send_channel, cmd.send_reference
            batch.send_hash, batch.status = hashed, "SENT"
            for item in self.items(s, batch.id):
                so = self.get(s, SupplierOrder, item.supplier_order_id)
                order = self.get(s, Order, so.order_id)
                if order.cancel_requested:
                    raise DomainError("CANCEL_REQUESTED")
                supplier_transition(s, so, "SENT", actor=actor.username)
                intervention(s, "SUPPLIER_FILE_SENT_MANUALLY", f"file-sent:{batch.id}:{so.id}", actor.username,
                    self.c.clock(), order=order, batch_id=batch.id, supplier_id=batch.supplier_id)
            audit(s, "SUPPLIER_BATCH_SENT", batch.id, actor=actor.username,
                  new={"channel": cmd.send_channel, "reference_hash": fingerprint(cmd.send_reference), "file_hash": batch.file_hash})
            return self.batch_view(s, batch, detail=True)

    def acknowledge(self, batch_id, raw, actor: Actor):
        actor.require(); cmd = Acknowledge.model_validate(raw)
        payload = cmd.canonical(); hashed = fingerprint(payload)
        with self.factory.begin() as s:
            lock_treasury(s)
            batch = self.get(s, SupplierOrderBatch, batch_id)
            prior = s.scalar(select(SupplierBatchAcknowledgement).where(SupplierBatchAcknowledgement.batch_id == batch.id))
            if prior:
                if prior.payload_hash != hashed:
                    raise DomainError("SUPPLIER_ACK_CONFLICT")
                return self.batch_view(s, batch, detail=True)
            if batch.sent_at is None or batch.status not in {"SENT", "CANCEL_PENDING"}:
                raise DomainError("SUPPLIER_BATCH_NOT_SENT")
            items = self.items(s, batch.id)
            ids = {item.supplier_order_id for item in items}
            reported_ids = cmd.accepted_order_ids + [line.supplier_order_id for line in cmd.rejected]
            if len(reported_ids) != len(set(reported_ids)) or set(reported_ids) != ids:
                raise DomainError("ACK_BATCH_MEMBERSHIP_MISMATCH", 422)
            changes = {line.supplier_order_id: line for line in cmd.reported_changes}
            if len(changes) != len(cmd.reported_changes) or not set(changes) <= ids:
                raise DomainError("ACK_CHANGE_MEMBERSHIP_MISMATCH", 422)
            rejected = {line.supplier_order_id: line.reason.value for line in cmd.rejected}
            # Do not persist reported SKUs or destinations in audit/JSON receipts.
            # The immutable receipt contains safe classifications plus original payload hash.
            safe_receipt = {"accepted_order_ids": sorted(cmd.accepted_order_ids),
                "rejected": payload["rejected"], "reported_changes": [
                    {"supplier_order_id": x.supplier_order_id, "hash": fingerprint(x.model_dump())}
                    for x in cmd.reported_changes]}
            s.add(SupplierBatchAcknowledgement(batch_id=batch.id, payload_hash=hashed, payload=safe_receipt,
                reference=cmd.reference, actor=actor.username, recorded_at=self.c.clock()))
            batch.acknowledged_at, batch.acknowledged_by = self.c.clock(), actor.username
            batch.ack_reference = cmd.reference
            # Process all decisions before preparing ANY payment so a supplier's
            # stock/price rejection can conservatively pause accepted same-SKU lines.
            accepted = []
            for item in items:
                so = self.get(s, SupplierOrder, item.supplier_order_id)
                order = self.get(s, Order, so.order_id)
                intent = self.intent(s, so); snap = intent.snapshot
                change = changes.get(so.id)
                changed = bool(change and (
                    (change.amount is not None and change.amount != intent.amount) or
                    (change.shipping is not None and change.shipping != snap["shipping"]) or
                    (change.quantity is not None and change.quantity != snap["quantity"]) or
                    (change.sku is not None and change.sku != snap["supplier_sku"]) or change.destination_changed))
                reason = rejected.get(so.id)
                resolve_reviews(s, order.id, ["SUPPLIER_FILE_ACK_REQUIRED"], actor.username, self.c.clock(), "SUPPLIER_ACK_RECORDED")
                intervention(s, "SUPPLIER_ACK_RECORDED_MANUALLY", f"ack:{batch.id}:{so.id}", actor.username,
                    self.c.clock(), order=order, batch_id=batch.id, supplier_id=batch.supplier_id)
                if changed or reason == "PRICE_CHANGED":
                    item.ack_status, item.rejection_reason = "MANUAL_REVIEW", "PRICE_CHANGED" if reason else "TERMS_CHANGED"
                    if so.status not in {"CANCEL_PENDING", "CANCELLED"}:
                        supplier_transition(s, so, "MANUAL_REVIEW", actor=actor.username)
                        self.c.hold(s, order, "SUPPLIER_TERMS_CHANGED")
                    review(s, "SUPPLIER_TERMS_CHANGED", so.id, {"batch_id": batch.id, "frozen_amount": intent.amount})
                    pause_listing(s, context(s, order)[0], "SUPPLIER_TERMS_CHANGED")
                    continue
                if reason:
                    item.ack_status, item.rejection_reason = "REJECTED", reason
                    audit(s, "SUPPLIER_ORDER_REJECTED", so.id, actor=actor.username, new={"reason": reason})
                    if reason in {"OUT_OF_STOCK", "SKU_NOT_FOUND"}:
                        pause_listing(s, context(s, order)[0], f"SUPPLIER_REJECTED_{reason}")
                    if so.status not in {"CANCEL_PENDING", "CANCELLED"}:
                        supplier_transition(s, so, "REJECTED", actor=actor.username)
                        release(s, order, restore_inventory=False)
                        self.c.hold(s, order, "SUPPLIER_ORDER_REJECTED")
                    review(s, "SUPPLIER_ORDER_REJECTED", so.id, {"reason": reason, "batch_id": batch.id})
                    continue
                item.ack_status, item.accepted_amount = "ACCEPTED", intent.amount
                audit(s, "SUPPLIER_ORDER_ACCEPTED", so.id, actor=actor.username,
                      new={"batch_id": batch.id, "amount": intent.amount})
                if order.cancel_requested or so.status == "CANCEL_PENDING":
                    review(s, "SUPPLIER_CANCELLATION_REQUIRED", so.id)
                    continue
                supplier_transition(s, so, "ACKNOWLEDGED", actor=actor.username)
                transition(s, order, "SUPPLIER_ORDERED", "EXPLICIT_SUPPLIER_ACK")
                accepted.append((so, order))
            s.flush()
            for so, order in accepted:
                self.c.prepare_payment(s, order, so)
            if batch.status != "CANCEL_PENDING":
                outcomes = {item.ack_status for item in items}
                batch.status = "ACKNOWLEDGED" if outcomes == {"ACCEPTED"} else "REJECTED" if outcomes == {"REJECTED"} else "PARTIAL"
            audit(s, "SUPPLIER_BATCH_ACKNOWLEDGED", batch.id, actor=actor.username,
                  new={"payload_hash": hashed, "accepted": sum(i.ack_status == "ACCEPTED" for i in items),
                       "rejected": sum(i.ack_status == "REJECTED" for i in items)})
            return self.batch_view(s, batch, detail=True)

    def payment_completed(self, s, payment):
        """Called only after money accounting has been committed within this transaction."""
        so = self.get(s, SupplierOrder, payment.supplier_order_id)
        if self.active_item(s, so.id) is None:
            return
        order = self.get(s, Order, so.order_id)
        if order.cancel_requested or so.status == "CANCEL_PENDING":
            review(s, "SUPPLIER_CANCELLATION_FINANCIAL_REVIEW", so.id)
            return
        supplier_transition(s, so, "PAID")
        supplier_transition(s, so, "SHIPMENT_PENDING")

    def payment_details(self, payment_id, actor: Actor):
        actor.require()
        with self.factory() as s:
            payment = self.get(s, Payment, payment_id)
            so = self.get(s, SupplierOrder, payment.supplier_order_id)
            intent = self.intent(s, so)
            reservation = s.scalar(select(Reservation).where(Reservation.order_id == payment.order_id))
            evidence = s.scalar(select(SupplierPaymentEvidence).where(SupplierPaymentEvidence.payment_id == payment.id))
            effective = effective_evidence(s, evidence) if evidence else {}
            return {"id": payment.id, "supplier_id": intent.supplier_id, "amount": payment.amount,
                "evidence_revision_id": effective.get("revision_id"),
                "destination_fingerprint": payment.destination_fingerprint, "status": payment.status,
                "bank_amount": reservation.bank_amount, "deposit_amount": reservation.deposit_amount,
                "evidence_id": evidence.id if evidence else None,
                "evidence": {"id": evidence.id, "method": evidence.method, "reference": effective["reference"],
                    "evidence_hash": effective["evidence_hash"], "revision_id": effective["revision_id"], "recorded_by": evidence.recorded_by,
                    "recorded_at": evidence.recorded_at} if evidence else None,
                "evidence_status": "CONFIRMED" if evidence and s.scalar(select(SupplierPaymentConfirmation.id).where(
                    SupplierPaymentConfirmation.evidence_id == evidence.id)) else "CORRECTION_REQUIRED" if evidence and correction_pending(s, evidence.id) else "RECORDED" if evidence else "ABSENT"}

    def record_evidence(self, payment_id, raw, actor: Actor):
        actor.require(); cmd = EvidenceRecord.model_validate(raw)
        hashed = fingerprint(cmd.model_dump()); error = None; result = None
        with self.factory.begin() as s:
            lock_treasury(s)
            payment = self.get(s, Payment, payment_id)
            prior = s.scalar(select(SupplierPaymentEvidence).where(SupplierPaymentEvidence.payment_id == payment.id))
            if prior:
                if prior.payload_hash != hashed:
                    raise DomainError("PAYMENT_EVIDENCE_CONFLICT")
                return {"id": prior.id, "payment_id": payment.id}
            if reference_in_use(s, cmd.supplier_id, cmd.reference, payment.id):
                raise DomainError("PAYMENT_EVIDENCE_REFERENCE_IN_USE")
            so = self.get(s, SupplierOrder, payment.supplier_order_id)
            intent = self.intent(s, so)
            item = self.active_item(s, so.id)
            batch = self.get(s, SupplierOrderBatch, item.batch_id) if item else None
            if batch is None or batch.payment_path != "MANUAL_EVIDENCE" or payment.status not in {"EVIDENCE_PENDING", "MANUAL_APPROVAL"}:
                raise DomainError("PAYMENT_EVIDENCE_NOT_ALLOWED")
            order = self.get(s, Order, payment.order_id)
            reservation = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
            if (cmd.amount != payment.amount or cmd.supplier_id != intent.supplier_id or
                    cmd.destination_fingerprint != payment.destination_fingerprint or
                    reservation is None or reservation.status != "HELD" or
                    cmd.bank_amount != reservation.bank_amount or cmd.deposit_amount != reservation.deposit_amount):
                error = "PAYMENT_EVIDENCE_SNAPSHOT_MISMATCH"
                review(s, error, payment.id)
                audit(s, "SUPPLIER_PAYMENT_EVIDENCE_REJECTED", payment.id, actor=actor.username, reason=error)
            elif order.cancel_requested or item.ack_status != "ACCEPTED":
                error = "PAYMENT_EVIDENCE_REQUIRES_RECONCILIATION"
                review(s, error, payment.id)
            else:
                proof = SupplierPaymentEvidence(payment_id=payment.id, **cmd.model_dump(),
                    payload_hash=hashed, recorded_by=actor.username, recorded_at=self.c.clock())
                s.add(proof); s.flush()
                audit(s, "SUPPLIER_PAYMENT_EVIDENCE_RECORDED", proof.id, actor=actor.username,
                    new={"payment_id": payment.id, "supplier_id": intent.supplier_id, "amount": payment.amount,
                         "evidence_hash": cmd.evidence_hash, "method": cmd.method})
                intervention(s, "PAYMENT_EVIDENCE_RECORDED_MANUALLY", f"evidence:{proof.id}", actor.username,
                    self.c.clock(), order=order, batch_id=batch.id, supplier_id=intent.supplier_id)
                result = {"id": proof.id, "payment_id": payment.id}
        if error:
            raise DomainError(error)  # after COMMIT: mismatch review must survive the HTTP 409
        return result

    def confirm_evidence(self, evidence_id, raw, actor: Actor):
        actor.require("admin"); cmd = EvidenceConfirm.model_validate(raw)
        # Keep pre-0003 confirmation hashes replay-compatible when no revision exists.
        hashed = fingerprint(cmd.model_dump(exclude_none=True)); error = None; result = None
        with self.factory.begin() as s:
            lock_treasury(s)
            proof = self.get(s, SupplierPaymentEvidence, evidence_id)
            payment = self.get(s, Payment, proof.payment_id)
            prior = s.scalar(select(SupplierPaymentConfirmation).where(SupplierPaymentConfirmation.evidence_id == proof.id))
            if prior:
                if prior.payload_hash != hashed:
                    raise DomainError("PAYMENT_CONFIRMATION_CONFLICT")
                return {"id": prior.id, "payment_id": payment.id, "status": "CONFIRMED"}
            order = self.get(s, Order, payment.order_id)
            so = self.get(s, SupplierOrder, payment.supplier_order_id)
            try:
                effective = effective_evidence(s, proof)
                if correction_pending(s, proof.id):
                    raise DomainError("PAYMENT_EVIDENCE_CORRECTION_REQUIRED")
                if cmd.evidence_revision_id != effective["revision_id"]:
                    raise DomainError("STALE_EVIDENCE_REVISION")
                if (cmd.amount != payment.amount or cmd.amount != proof.amount or
                        cmd.destination_fingerprint != payment.destination_fingerprint or
                        cmd.destination_fingerprint != proof.destination_fingerprint or cmd.reference != effective["reference"]):
                    raise DomainError("PAYMENT_CONFIRMATION_SNAPSHOT_MISMATCH")
                if payment.status != "EVIDENCE_PENDING":
                    raise DomainError("PAYMENT_NOT_EVIDENCE_CONFIRMABLE")
                batch = self.validate_payable(s, order, so)
                if batch.payment_path != "MANUAL_EVIDENCE":
                    raise DomainError("PAYMENT_EVIDENCE_NOT_ALLOWED")
                if payment.amount > self.c.settings.auto_payment_limit and not payment.approved_by:
                    raise DomainError("PAYMENT_APPROVAL_REQUIRED")
                if daily_commitments(s, payment.id, self.c.clock()) + payment.amount > self.c.settings.daily_payment_limit:
                    raise DomainError("DAILY_PAYMENT_LIMIT")
            except (DomainError, ValidationError) as exc:
                error = getattr(exc, "code", "ADDRESS_ERROR")
                review(s, error, payment.id)
                audit(s, "SUPPLIER_PAYMENT_CONFIRMATION_BLOCKED", payment.id, actor=actor.username, reason=error)
            else:
                confirmation = SupplierPaymentConfirmation(evidence_id=proof.id, payment_id=payment.id,
                    payload_hash=hashed, actor=actor.username, confirmed_at=self.c.clock(), amount=cmd.amount,
                    destination_fingerprint=cmd.destination_fingerprint, reference=cmd.reference)
                s.add(confirmation); s.flush()
                if effective["revision_id"]:
                    s.add(SupplierEvidenceConfirmationBinding(confirmation_id=confirmation.id, revision_id=effective["revision_id"]))
                payment.dispatched_at = self.c.clock()
                settle_payment(s, payment, f"manual-evidence:{proof.id}", source="MANUAL_EVIDENCE")
                transition(s, order, "SUPPLIER_PAID", "ADMIN_PAYMENT_EVIDENCE")
                transition(s, order, "SHIPMENT_PENDING", "ADMIN_PAYMENT_EVIDENCE")
                self.payment_completed(s, payment)
                resolve_reviews(s, payment.id, ["PAYMENT_APPROVAL", "PAYMENT_EVIDENCE_SNAPSHOT_MISMATCH",
                    "PAYMENT_CONFIRMATION_SNAPSHOT_MISMATCH", "STALE_EVIDENCE_REVISION",
                    "PAYMENT_EVIDENCE_CORRECTION_REQUIRED"], actor.username, self.c.clock(), "CONFIRM_MANUAL_PAYMENT")
                audit(s, "SUPPLIER_PAYMENT_CONFIRMED", payment.id, actor=actor.username,
                    new={"supplier_id": proof.supplier_id, "amount": payment.amount, "evidence_id": proof.id,
                         "destination_fingerprint": payment.destination_fingerprint, "source": "MANUAL_EVIDENCE",
                         "evidence_revision_id": effective["revision_id"]})
                intervention(s, "PAYMENT_EVIDENCE_CONFIRMED_MANUALLY", f"payment-confirmed:{payment.id}", actor.username,
                    self.c.clock(), order=order, batch_id=batch.id, supplier_id=proof.supplier_id)
                result = {"id": confirmation.id, "payment_id": payment.id, "status": "CONFIRMED"}
        if error:
            raise DomainError(error)
        return result

    def request_cancellation_in_session(self, s, so, actor):
        """Caller holds treasury. Used by marketplace cancellation and operator commands."""
        prior = s.scalar(select(SupplierCancellation).where(SupplierCancellation.supplier_order_id == so.id))
        if prior:
            return prior
        order = self.get(s, Order, so.order_id)
        item = self.active_item(s, so.id)
        batch = self.get(s, SupplierOrderBatch, item.batch_id) if item else None
        intent = s.scalar(select(SupplierOrderIntent).where(SupplierOrderIntent.supplier_order_id == so.id))
        uncertain_legacy = intent is None
        sent = bool(batch and batch.sent_at)
        explicitly_rejected = bool(item and item.ack_status == "REJECTED" and so.status == "REJECTED")
        payment = s.scalar(select(Payment).where(Payment.supplier_order_id == so.id))
        proof = s.scalar(select(SupplierPaymentEvidence).where(SupplierPaymentEvidence.payment_id == payment.id)) if payment else None
        money_exposed = bool(proof or payment and payment.status in {"SENDING", "UNKNOWN", "SUCCEEDED"})
        request = SupplierCancellation(supplier_order_id=so.id, status="PENDING", from_state=so.status,
            requested_by=actor, requested_at=self.c.clock())
        s.add(request)
        order.cancel_requested = True
        if order.state not in {"CANCEL_REQUESTED", "CANCELLED", "CLOSED", "SETTLED", "SETTLEMENT_PENDING"}:
            transition(s, order, "CANCEL_REQUESTED")
        audit(s, "SUPPLIER_CANCELLATION_REQUESTED", so.id, actor=actor,
              new={"external_confirmation_required": sent or money_exposed or uncertain_legacy})
        if actor not in {"marketplace", "system"}:
            intervention(s, "SUPPLIER_CANCELLATION_REQUESTED_MANUALLY", f"cancel-request:{so.id}", actor,
                self.c.clock(), order=order, batch_id=batch.id if batch else None,
                supplier_id=intent.supplier_id if intent else None)
        if batch and not sent:
            # A downloaded file cannot be rewritten invisibly: invalidate the whole
            # file; retain all old membership, allow only surviving lines to re-batch.
            batch.status = "INVALIDATED"
            for old_item in self.items(s, batch.id):
                old_item.active = False
                other = self.get(s, SupplierOrder, old_item.supplier_order_id)
                if other.id != so.id and other.status in {"FILE_READY", "EXPORTED"}:
                    supplier_transition(s, other, "PENDING", actor=actor, reason="UNSENT_BATCH_INVALIDATED")
            audit(s, "SUPPLIER_BATCH_INVALIDATED", batch.id, actor=actor, reason="CANCELLATION_BEFORE_SEND")
        if (not sent or explicitly_rejected) and not money_exposed and not uncertain_legacy:
            if payment:
                payment.status = "CANCELLED"
            supplier_transition(s, so, "CANCELLED", actor=actor)
            release(s, order)
            if order.state == "CANCEL_REQUESTED":
                transition(s, order, "CANCELLED")
            request.status = "CONFIRMED_LOCAL"
            request.confirmed_by, request.confirmed_at = actor, self.c.clock()
            resolve_reviews(s, order.id, ["SUPPLIER_FILE_ACK_REQUIRED", "SUPPLIER_ORDER_REJECTED"], actor, self.c.clock(), "CANCEL_UNACCEPTED_ORDER")
            resolve_reviews(s, so.id, ["SUPPLIER_ORDER_REJECTED"], actor, self.c.clock(), "CANCEL_UNACCEPTED_ORDER")
            audit(s, "SUPPLIER_CANCELLATION_CONFIRMED", so.id, actor=actor, reason="LOCAL_BEFORE_SEND")
        else:
            if payment and not money_exposed:
                payment.status = "CANCELLED"
            if so.status not in {"CANCEL_PENDING", "CANCELLED"}:
                supplier_transition(s, so, "CANCEL_PENDING", actor=actor)
            if batch:
                batch.status = "CANCEL_PENDING"
            review(s, "SUPPLIER_CANCELLATION_REQUIRED", so.id)
            if money_exposed:
                review(s, "SUPPLIER_CANCELLATION_FINANCIAL_REVIEW", so.id)
        return request

    def cancel_order(self, so_id, actor: Actor):
        actor.require()
        with self.factory.begin() as s:
            lock_treasury(s)
            request = self.request_cancellation_in_session(s, self.get(s, SupplierOrder, so_id), actor.username)
            s.flush()
            return {"id": request.id, "status": request.status}

    def cancel_batch(self, batch_id, actor: Actor):
        actor.require()
        with self.factory.begin() as s:
            lock_treasury(s)
            batch = self.get(s, SupplierOrderBatch, batch_id)
            if batch.status == "RESOLVED":
                raise DomainError("BATCH_ALREADY_RESOLVED")
            for item in self.items(s, batch.id):
                current = self.active_item(s, item.supplier_order_id)
                if current is not None and current.batch_id != batch.id:
                    raise DomainError("BATCH_SUPERSEDED")
            for item in self.items(s, batch.id):
                self.request_cancellation_in_session(s, self.get(s, SupplierOrder, item.supplier_order_id), actor.username)
            if not batch.sent_at:
                batch.status = "CANCELLED"
            return self.batch_view(s, batch, detail=True)

    def confirm_cancellation(self, so_id, raw, actor: Actor):
        actor.require("admin"); cmd = CancellationConfirm.model_validate(raw)
        hashed = fingerprint(cmd.model_dump())
        with self.factory.begin() as s:
            lock_treasury(s)
            so = self.get(s, SupplierOrder, so_id)
            request = s.scalar(select(SupplierCancellation).where(SupplierCancellation.supplier_order_id == so.id))
            if request is None or request.status == "CONFIRMED_LOCAL":
                raise DomainError("SUPPLIER_CANCEL_CONFIRMATION_NOT_REQUIRED")
            if request.confirmation_hash:
                if request.confirmation_hash != hashed:
                    raise DomainError("SUPPLIER_CANCELLATION_CONFLICT")
                return {"id": request.id, "status": request.status}
            order = self.get(s, Order, so.order_id)
            payment = s.scalar(select(Payment).where(Payment.supplier_order_id == so.id))
            proof = s.scalar(select(SupplierPaymentEvidence).where(SupplierPaymentEvidence.payment_id == payment.id)) if payment else None
            exposed = bool(proof or payment and payment.status in {"SENDING", "UNKNOWN", "SUCCEEDED"})
            request.confirmation_hash, request.reference = hashed, cmd.reference
            request.confirmed_by, request.confirmed_at = actor.username, self.c.clock()
            request.status = "FINANCIAL_REVIEW" if exposed else "CONFIRMED"
            supplier_transition(s, so, "CANCELLED", actor=actor.username)
            if not exposed:
                if payment:
                    payment.status = "CANCELLED"
                release(s, order, restore_inventory=False)
                if order.state == "CANCEL_REQUESTED":
                    transition(s, order, "CANCELLED")
            else:
                review(s, "SUPPLIER_CANCELLATION_FINANCIAL_REVIEW", so.id)
            resolve_reviews(s, so.id, ["SUPPLIER_CANCELLATION_REQUIRED"], actor.username, self.c.clock(), "CONFIRM_SUPPLIER_CANCELLATION")
            resolve_reviews(s, order.id, ["SUPPLIER_FILE_ACK_REQUIRED"], actor.username, self.c.clock(), "CONFIRM_SUPPLIER_CANCELLATION")
            audit(s, "SUPPLIER_CANCELLATION_CONFIRMED", so.id, actor=actor.username,
                  new={"financial_review": exposed, "reference_hash": fingerprint(cmd.reference)})
            intervention(s, "SUPPLIER_CANCELLATION_CONFIRMED_MANUALLY", f"cancel-confirmed:{so.id}", actor.username,
                         self.c.clock(), order=order)
            return {"id": request.id, "status": request.status}

    def resume_own_terms_pause(self, s, order, so, actor, reference):
        listing, sp, _, product = context(s, order)
        if listing.desired_state == "ACTIVE":
            return
        intent = self.intent(s, so)
        reasons = list(s.scalars(select(AuditEvent.reason).where(AuditEvent.entity_id == listing.id,
            AuditEvent.event == "LISTING_PAUSED", AuditEvent.created_at >= intent.created_at)))
        if not reasons or any(reason != "SUPPLIER_TERMS_CHANGED" for reason in reasons):
            raise DomainError("LISTING_REQUIRES_SEPARATE_RISK_RESOLUTION")
        if s.scalar(select(Review.id).where(Review.entity_id.in_([listing.id, sp.id, product.id]),
                Review.status != "RESOLVED")):
            raise DomainError("LISTING_HAS_UNRESOLVED_RISK_REVIEW")
        # Temporary inside the transaction. Any failed check rolls this back;
        # there is never a network call while temporarily changing desired state.
        listing.desired_state = "ACTIVE"
        self.validate_frozen(s, order, so)
        inventory_guard(s, self.c.settings, at=self.c.clock())
        guard_cash_and_claims(s, self.c)
        if listing.desired_state != "ACTIVE":
            raise DomainError("LISTING_RISK_STILL_ACTIVE")
        listing.remote_state = "UNCONFIRMED"
        listing.sync_revision += 1
        enqueue(s, "listing.sync", f"listing:{listing.id}:{listing.sync_revision}", {
            "listing_id": listing.id, "revision": listing.sync_revision, "desired_state": "ACTIVE", "price": listing.price})
        audit(s, "LISTING_RESUMED_ORIGINAL_SUPPLIER_TERMS", listing.id, actor=actor,
            new={"supplier_order_id": so.id, "remote_confirmed": False, "reference_hash": fingerprint(reference)})

    def adopt_verified_unsent_legacy(self, so_id, raw, actor: Actor):
        actor.require("admin"); cmd = LegacyAdopt.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s)
            def action():
                so = self.get(s, SupplierOrder, so_id)
                order = self.get(s, Order, so.order_id)
                if (so.status != "MANUAL_REVIEW" or order.state != "SUPPLIER_ORDER_PENDING" or order.cancel_requested or
                        s.scalar(select(SupplierOrderIntent.id).where(SupplierOrderIntent.supplier_order_id == so.id)) or
                        s.scalar(select(Payment.id).where(Payment.supplier_order_id == so.id)) or
                        s.scalar(select(SupplierCancellation.id).where(SupplierCancellation.supplier_order_id == so.id))):
                    raise DomainError("LEGACY_ORDER_NOT_ADOPTABLE")
                _, _, supplier, cost, _ = self.c.validate_order(s, order, already_reserved=True)
                if supplier.mode != "excel" or cost != so.amount:
                    raise DomainError("LEGACY_ORDER_NOT_ADOPTABLE")
                self.freeze_intent(s, order, so)
                s.flush()
                self.validate_frozen(s, order, so)
                supplier_transition(s, so, "PENDING", actor=actor.username, reason="VERIFIED_LEGACY_NEVER_SENT")
                resolve_reviews(s, so.id, ["LEGACY_SUPPLIER_STATE_UNVERIFIED"], actor.username, self.c.clock(), "ADOPT_VERIFIED_UNSENT")
                audit(s, "SUPPLIER_LEGACY_ADOPTED_UNSENT", so.id, actor=actor.username,
                    new={"reference_hash": fingerprint(cmd.reference), "amount": so.amount})
                intervention(s, "LEGACY_SUPPLIER_RECONCILED_MANUALLY", f"legacy-adopt:{so.id}", actor.username,
                    self.c.clock(), order=order, supplier_id=supplier.id)
                return {"supplier_order_id": so.id, "status": so.status}
            return execute_command(s, "supplier.legacy.adopt", so_id, cmd.model_dump(), action)

    def revalidate_original_terms(self, so_id, raw, actor: Actor):
        """Recover an unchanged, accepted/frozen order; cannot reprice or revive a cancellation."""
        actor.require("admin"); cmd = Revalidate.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s)
            def action():
                so = self.get(s, SupplierOrder, so_id)
                order = self.get(s, Order, so.order_id)
                item = self.active_item(s, so.id)
                if item is None or item.ack_status not in {"ACCEPTED", "MANUAL_REVIEW"}:
                    raise DomainError("SUPPLIER_REVALIDATION_NOT_ALLOWED")
                if so.status not in {"MANUAL_REVIEW", "ACKNOWLEDGED", "PAYMENT_PENDING"}:
                    raise DomainError("SUPPLIER_REVALIDATION_NOT_ALLOWED")
                if s.scalar(select(SupplierCancellation.id).where(SupplierCancellation.supplier_order_id == so.id)):
                    raise DomainError("CANCEL_REQUESTED")
                self.resume_own_terms_pause(s, order, so, actor.username, cmd.reference)
                intent, _ = self.validate_frozen(s, order, so)
                payment = s.scalar(select(Payment).where(Payment.supplier_order_id == so.id))
                if payment and payment.status in {"SENDING", "UNKNOWN", "SUCCEEDED", "CANCELLED"}:
                    raise DomainError("PAYMENT_NOT_REVALIDATABLE")
                item.ack_status, item.accepted_amount, item.rejection_reason = "ACCEPTED", intent.amount, None
                if so.status == "MANUAL_REVIEW":
                    supplier_transition(s, so, "ACKNOWLEDGED", actor=actor.username, reason="ORIGINAL_TERMS_RECONFIRMED")
                if order.state == "MANUAL_REVIEW":
                    transition(s, order, "SUPPLIER_ORDERED", "GUARDED_SUPPLIER_REVALIDATION")
                if order.state != "SUPPLIER_ORDERED":
                    raise DomainError("ORDER_NOT_PAYABLE")
                if payment:
                    if payment.amount != intent.amount or payment.destination_fingerprint != intent.snapshot["destination_fingerprint"]:
                        raise DomainError("PAYMENT_SNAPSHOT_MISMATCH")
                    # Never overwrite UNKNOWN or an existing proof. Approval remains
                    # a separate command for MANUAL_APPROVAL payments.
                    review(s, "PAYMENT_APPROVAL", payment.id)
                else:
                    self.c.prepare_payment(s, order, so)
                resolve_reviews(s, so.id, ["SUPPLIER_TERMS_CHANGED", "SUPPLIER_PAYMENT_PREPARATION_BLOCKED"],
                    actor.username, self.c.clock(), "RETRY_VALIDATION_ORIGINAL_TERMS")
                resolve_reviews(s, order.id, ["SUPPLIER_TERMS_CHANGED", "DESTINATION_NOT_WHITELISTED", "DESTINATION_CHANGED",
                    "SUPPLIER_INACTIVE", "RESERVED_COST_CHANGED", "STALE_INVENTORY", "INSUFFICIENT_CASH", "LISTING_PAUSED",
                    "SUPPLIER_FROZEN_TERMS_CHANGED"], actor.username, self.c.clock(), "RETRY_VALIDATION_ORIGINAL_TERMS")
                current_batch = self.get(s, SupplierOrderBatch, item.batch_id)
                if current_batch.status == "PARTIAL" and all(x.ack_status == "ACCEPTED" for x in self.items(s, item.batch_id)):
                    current_batch.status = "ACKNOWLEDGED"
                audit(s, "SUPPLIER_ORIGINAL_TERMS_RECONFIRMED", so.id, actor=actor.username,
                      new={"reference_hash": fingerprint(cmd.reference), "amount": intent.amount})
                intervention(s, "SUPPLIER_REVIEW_RESOLVED_MANUALLY", f"supplier-revalidate:{so.id}:{cmd.reference}",
                             actor.username, self.c.clock(), order=order, batch_id=item.batch_id)
                return {"supplier_order_id": so.id, "status": so.status}
            return execute_command(s, "supplier.revalidate", fingerprint({"so": so_id, "reference": cmd.reference}), {"supplier_order_id": so_id, **cmd.model_dump()}, action)

    def resolve_batch(self, batch_id, actor: Actor):
        actor.require("admin")
        with self.factory.begin() as s:
            lock_treasury(s)
            batch = self.get(s, SupplierOrderBatch, batch_id)
            if batch.status == "RESOLVED":
                return self.batch_view(s, batch, detail=True)
            for item in self.items(s, batch.id):
                so = self.get(s, SupplierOrder, item.supplier_order_id)
                order = self.get(s, Order, so.order_id)
                if so.status not in {"SHIPPED", "CANCELLED"} or order.state == "CANCEL_REQUESTED":
                    raise DomainError("BATCH_UNRESOLVED_BUSINESS_ISSUE")
                if s.scalar(select(Review.id).where(Review.entity_id.in_([so.id, order.id]), Review.status != "RESOLVED")):
                    raise DomainError("BATCH_HAS_OPEN_REVIEWS")
            batch.status = "RESOLVED"
            audit(s, "SUPPLIER_BATCH_RESOLVED", batch.id, actor=actor.username)
            return self.batch_view(s, batch, detail=True)

    def metrics(self):
        with self.factory() as s:
            completed = list(s.scalars(select(Order.id).where(Order.state == "CLOSED")))
            touched = set(s.scalars(select(OperationalIntervention.order_id).where(OperationalIntervention.order_id.is_not(None))))
            categories = dict(s.execute(select(OperationalIntervention.category, func.count())
                .group_by(OperationalIntervention.category)).all())
            return {"measurement_scope": "PHASE10_RECORDED_INTERVENTIONS_ONLY", "production_automation_percentage": None,
                "completed_orders": len(completed), "completed_with_recorded_interventions": len(set(completed) & touched),
                "completed_without_recorded_interventions": len(set(completed) - touched),
                "interventions_by_category": categories,
                "caveat": "Historical/unrecorded manual work is not proof of zero human intervention."}
