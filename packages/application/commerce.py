"""Transactional order orchestration. No network call is made inside a money transaction."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from pydantic import ValidationError
from packages.domain.errors import DomainError, IntegrationError
from packages.domain.schemas import OrderInput, Address, ShipmentRow
from packages.domain.pricing import margin, fee_for
from packages.domain.state_machine import validate_transition, EARLY_CANCEL
from packages.infrastructure.models import (Order, Supplier, SupplierProduct, Product, MarketplaceListing,
    SupplierOrder, Reservation, Payment, Shipment, Claim)
from packages.infrastructure.schema_v1 import uid
from packages.infrastructure.db import aware
from packages.infrastructure.security import Cipher, fingerprint
from packages.integrations.adapters import Registry
from .common import audit, review, enqueue, lock_treasury
from .finance import reserve, release, daily_commitments, settle_payment, post
from .catalog import pause_listing


def transition(s, order, target, reason="RULE"):
    validate_transition(order.state, target)
    if order.state == target: return
    before = order.state
    order.state = target
    audit(s, "ORDER_TRANSITION", order.id, old={"state": before}, new={"state": target},
          reason=reason, correlation_id=order.correlation_id)


def context(s, order):
    listing = s.get(MarketplaceListing, order.listing_id)
    sp = s.get(SupplierProduct, listing.supplier_product_id)
    return listing, sp, s.get(Supplier, sp.supplier_id), s.get(Product, sp.product_id)


class Commerce:
    def __init__(self, settings, factory, registry=None, clock=None):
        self.settings, self.factory = settings, factory
        self.registry = registry or Registry(settings, factory)
        self.cipher = Cipher(settings.pii_encryption_key.get_secret_value())
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def ingest(self, raw: dict) -> dict:
        data = OrderInput.model_validate(raw)
        payload = data.model_dump()
        hashed = fingerprint(payload)
        with self.factory.begin() as s:
            lock_treasury(s)
            existing = s.scalar(select(Order).where(Order.marketplace == data.marketplace,
                Order.external_id == data.external_id, Order.external_line_id == data.external_line_id))
            if existing:
                if existing.input_hash != hashed: raise DomainError("ORDER_IDENTITY_PAYLOAD_CONFLICT")
                return {"id": existing.id, "state": existing.state, "duplicate": True}
            listing = s.get(MarketplaceListing, data.listing_id)
            if listing is None or listing.marketplace != data.marketplace: raise DomainError("INVALID_LISTING", 422)
            order = Order(marketplace=data.marketplace, external_id=data.external_id,
                external_line_id=data.external_line_id, listing_id=data.listing_id, quantity=data.quantity,
                gross_sale=data.gross_sale, discount=data.discount, input_hash=hashed,
                pii_ciphertext=self.cipher.encrypt({"original_address": data.address, "normalized_address": data.address}),
                hold_until=self.clock() + timedelta(seconds=self.settings.order_hold_seconds))
            s.add(order); s.flush()
            audit(s, "ORDER_RECEIVED", order.id, correlation_id=order.correlation_id)
            enqueue(s, "order.process", f"order:{order.id}", {"order_id": order.id}, at=order.hold_until)
            return {"id": order.id, "state": order.state, "duplicate": False}

    def validate_order(self, s, order, *, already_reserved=False):
        listing, sp, supplier, product = context(s, order)
        Address.model_validate(self.cipher.decrypt(order.pii_ciphertext)["original_address"])
        if order.cancel_requested: raise DomainError("CANCEL_REQUESTED")
        if not supplier.active: raise DomainError("SUPPLIER_INACTIVE")
        if listing.desired_state != "ACTIVE": raise DomainError("LISTING_PAUSED")
        if product.tax_type == "UNKNOWN": raise DomainError("TAX_CLASSIFICATION_REQUIRED")
        if product.season_state != "OPEN": raise DomainError("OUT_OF_SEASON")
        if sp.stock is None or sp.stock_status == "UNKNOWN": raise DomainError("UNKNOWN_INVENTORY")
        if not already_reserved and sp.stock < order.quantity: raise DomainError("OUT_OF_STOCK")
        if (self.clock() - aware(sp.last_inventory_at)).total_seconds() > self.settings.inventory_max_age_seconds:
            raise DomainError("STALE_INVENTORY")
        local_time = self.clock().astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M")
        if local_time >= supplier.cutoff: raise DomainError("SUPPLIER_CUTOFF")
        cost = sp.cost * order.quantity + sp.shipping
        result = margin(order.gross_sale-order.discount, cost, listing.fee_rate,
                        listing.claim_allowance * order.quantity, listing.promotion_cost)
        if result.percentage < self.settings.min_margin: raise DomainError("MARGIN_BELOW_THRESHOLD")
        if already_reserved and cost != order.cost_snapshot: raise DomainError("RESERVED_COST_CHANGED")
        return listing, sp, supplier, cost, result

    def hold(self, s, order, code):
        if order.state not in {"MANUAL_REVIEW", "CANCEL_REQUESTED", "CANCELLED", "CLOSED"}:
            transition(s, order, "MANUAL_REVIEW", code)
        review(s, code, order.id)
        audit(s, "ORDER_HELD", order.id, reason=code, correlation_id=order.correlation_id)

    def process_order(self, order_id):
        with self.factory() as s:
            order = s.get(Order, order_id)
            if order is None: raise DomainError("ORDER_NOT_FOUND", 404)
            market, external_id = order.marketplace, order.external_id
        remote = self.registry.marketplace(market).get_order(external_id)
        if remote["status"] == "CANCELLED":
            self.cancel(order_id, actor="marketplace")
            return
        with self.factory.begin() as s:
            lock_treasury(s)
            order = s.get(Order, order_id)
            if order.state != "RECEIVED": return
            if self.clock() < aware(order.hold_until): raise IntegrationError("ORDER_HOLD", retryable=True)
            transition(s, order, "VALIDATING")
            try:
                listing, sp, supplier, cost, result = self.validate_order(s, order)
                transition(s, order, "VALIDATED")
                transition(s, order, "RISK_CHECKED")
                reserve(s, self.settings, order, sp, cost)
                order.cost_snapshot, order.fee, order.promotion_cost = cost, result.fee, listing.promotion_cost
                transition(s, order, "PAYMENT_RESERVED")
                so = SupplierOrder(order_id=order.id, business_key=f"supplier:{order.id}", amount=cost, status="PENDING")
                s.add(so); s.flush()
                transition(s, order, "SUPPLIER_ORDER_PENDING")
                if supplier.mode == "excel":
                    so.status = "FILE_READY"
                    review(s, "SUPPLIER_FILE_ACK_REQUIRED", order.id)
                else:
                    enqueue(s, "supplier.submit", so.business_key, {"supplier_order_id": so.id})
            except ValidationError:
                self.hold(s, order, "ADDRESS_ERROR")
            except DomainError as exc:
                self.hold(s, order, exc.code)
                if exc.code in {"INSUFFICIENT_CASH", "MARGIN_BELOW_THRESHOLD", "STALE_INVENTORY", "OUT_OF_STOCK"}:
                    listing = s.get(MarketplaceListing, order.listing_id)
                    pause_listing(s, listing, exc.code)

    def submit_supplier(self, supplier_order_id):
        with self.factory() as s:
            so = s.get(SupplierOrder, supplier_order_id); order = s.get(Order, so.order_id)
            market, external_id = order.marketplace, order.external_id
        if self.registry.marketplace(market).get_order(external_id)["status"] == "CANCELLED":
            self.cancel(order.id, actor="marketplace"); return
        with self.factory.begin() as s:
            lock_treasury(s)
            so = s.get(SupplierOrder, supplier_order_id); order = s.get(Order, so.order_id)
            if so.status in {"ACCEPTED", "CANCELLED", "FILE_READY"}: return
            if order.cancel_requested:
                enqueue(s, "supplier.cancel", f"cancel:{so.id}", {"supplier_order_id": so.id}); return
            try:
                _, sp, supplier, _, _ = self.validate_order(s, order, already_reserved=True)
            except (ValidationError, DomainError) as exc:
                self.hold(s, order, getattr(exc, "code", "ADDRESS_ERROR")); return
            so.status = "SENDING"
            payload = {"order_id": order.id, "sku": sp.supplier_sku, "quantity": order.quantity,
                "amount": so.amount, "address": self.cipher.decrypt(order.pii_ciphertext)["original_address"]}
            key, mode = so.business_key, supplier.mode
        receipt = self.registry.supplier(mode).create_orders(payload, key)
        with self.factory.begin() as s:
            lock_treasury(s)
            so = s.get(SupplierOrder, supplier_order_id); order = s.get(Order, so.order_id)
            so.status, so.external_id = "ACCEPTED", receipt["reference"]
            audit(s, "SUPPLIER_ORDER_CREATED", order.id, correlation_id=order.correlation_id)
            if order.cancel_requested:
                enqueue(s, "supplier.cancel", f"cancel:{so.id}", {"supplier_order_id": so.id}); return
            transition(s, order, "SUPPLIER_ORDERED")
            self.prepare_payment(s, order, so)

    def prepare_payment(self, s, order, so):
        if s.scalar(select(Payment).where(Payment.order_id == order.id)): return
        _, _, supplier, _ = context(s, order)
        if not supplier.destination_approved or not supplier.destination_fingerprint:
            self.hold(s, order, "DESTINATION_NOT_WHITELISTED"); return
        status = "PENDING"
        if so.amount > self.settings.auto_payment_limit or daily_commitments(s, at=self.clock()) + so.amount > self.settings.daily_payment_limit:
            status = "MANUAL_APPROVAL"
        p = Payment(order_id=order.id, supplier_order_id=so.id, business_key=f"payment:{order.id}",
                    amount=so.amount, destination_fingerprint=supplier.destination_fingerprint, status=status)
        s.add(p); s.flush()
        if status == "MANUAL_APPROVAL": review(s, "PAYMENT_APPROVAL", p.id, {"amount": p.amount})
        else: enqueue(s, "payment.execute", p.business_key, {"payment_id": p.id})

    def approve_payment(self, payment_id, amount, destination_fingerprint, actor):
        with self.factory.begin() as s:
            lock_treasury(s); p = s.get(Payment, payment_id)
            if p is None: raise DomainError("PAYMENT_NOT_FOUND", 404)
            if p.status != "MANUAL_APPROVAL": raise DomainError("PAYMENT_NOT_AWAITING_APPROVAL")
            if p.amount != amount or p.destination_fingerprint != destination_fingerprint: raise DomainError("APPROVAL_SNAPSHOT_MISMATCH")
            order = s.get(Order, p.order_id)
            if order.cancel_requested: raise DomainError("CANCEL_REQUESTED")
            p.approved_by, p.approved_at, p.status = actor, self.clock(), "PENDING"
            order.human_interventions += 1
            audit(s, "PAYMENT_APPROVED", p.id, actor=actor, new={"amount": p.amount}, correlation_id=order.correlation_id)
            enqueue(s, "payment.execute", p.business_key, {"payment_id": p.id})

    def execute_payment(self, payment_id):
        with self.factory() as s:
            p = s.get(Payment, payment_id); order = s.get(Order, p.order_id)
            market, external_id = order.marketplace, order.external_id
        if self.registry.marketplace(market).get_order(external_id)["status"] == "CANCELLED":
            self.cancel(order.id, actor="marketplace"); return
        with self.factory.begin() as s:
            lock_treasury(s); p = s.get(Payment, payment_id); order = s.get(Order, p.order_id)
            if p.status in {"SUCCEEDED", "CANCELLED", "MANUAL_APPROVAL", "UNKNOWN"}: return
            if p.status == "SENDING":
                p.status = "UNKNOWN"; review(s, "PAYMENT_RESULT_UNKNOWN", p.id); return
            if p.status != "PENDING": raise DomainError("PAYMENT_NOT_DISPATCHABLE")
            if order.cancel_requested:
                p.status = "CANCELLED"; return
            try:
                _, _, supplier, _, _ = self.validate_order(s, order, already_reserved=True)
                if not supplier.destination_approved or supplier.destination_fingerprint != p.destination_fingerprint:
                    raise DomainError("DESTINATION_CHANGED")
                if order.state != "SUPPLIER_ORDERED": raise DomainError("ORDER_NOT_PAYABLE")
            except (DomainError, ValidationError) as exc:
                p.status = "MANUAL_APPROVAL"; self.hold(s, order, getattr(exc, "code", "ADDRESS_ERROR")); return
            if not p.approved_by and daily_commitments(s, p.id, self.clock()) + p.amount > self.settings.daily_payment_limit:
                p.status = "MANUAL_APPROVAL"; review(s, "PAYMENT_APPROVAL", p.id, {"amount": p.amount}); return
            p.status, p.dispatched_at = "SENDING", self.clock()
            key = p.business_key
            payload = {"amount": p.amount, "destination_fingerprint": p.destination_fingerprint, "supplier_order_id": p.supplier_order_id}
        try:
            receipt = self.registry.payment().pay_supplier(payload, key)
        except IntegrationError:
            with self.factory.begin() as s:
                lock_treasury(s); p = s.get(Payment, payment_id); p.status = "UNKNOWN"
                review(s, "PAYMENT_RESULT_UNKNOWN", p.id)
            return  # Never blindly retry a money request, even on a timeout.
        self.finalize_payment(payment_id, receipt["reference"])

    def finalize_payment(self, payment_id, reference):
        with self.factory.begin() as s:
            lock_treasury(s); p = s.get(Payment, payment_id); order = s.get(Order, p.order_id)
            if p.status == "SUCCEEDED": return
            settle_payment(s, p, reference)
            if order.cancel_requested:
                review(s, "CANCELLATION_AFTER_PAYMENT", order.id)
            else:
                transition(s, order, "SUPPLIER_PAID"); transition(s, order, "SHIPMENT_PENDING")

    def reconcile_payment(self, payment_id):
        with self.factory() as s:
            p = s.get(Payment, payment_id)
            if p.status not in {"SENDING", "UNKNOWN", "SUCCEEDED"}: raise DomainError("PAYMENT_NOT_RECONCILABLE")
            key = p.business_key
        receipt = self.registry.payment().get_transaction(key)
        if receipt["status"] == "SUCCEEDED": self.finalize_payment(payment_id, receipt["reference"])
        else:
            with self.factory.begin() as s:
                lock_treasury(s); review(s, "PAYMENT_NOT_FOUND_REVERIFY_REQUIRED", payment_id)
        return receipt

    def cancel(self, order_id, actor="operator"):
        with self.factory.begin() as s:
            lock_treasury(s); order = s.get(Order, order_id)
            if order is None: raise DomainError("ORDER_NOT_FOUND", 404)
            if order.state == "CANCELLED" or order.cancel_requested: return
            order.cancel_requested = True
            if actor != "marketplace": order.human_interventions += 1
            audit(s, "CANCELLATION_REQUESTED", order.id, actor=actor, correlation_id=order.correlation_id)
            so = s.scalar(select(SupplierOrder).where(SupplierOrder.order_id == order_id))
            payment = s.scalar(select(Payment).where(Payment.order_id == order_id))
            if payment and payment.status in {"SENDING", "UNKNOWN", "SUCCEEDED"}:
                if order.state not in {"SETTLED", "CLOSED", "SETTLEMENT_PENDING"}: transition(s, order, "CANCEL_REQUESTED")
                review(s, "CANCELLATION_AFTER_PAYMENT", order.id); return
            if payment: payment.status = "CANCELLED"
            if order.state in {"SETTLED", "CLOSED", "SETTLEMENT_PENDING"}:
                review(s, "LATE_CANCELLATION", order.id); return
            transition(s, order, "CANCEL_REQUESTED")
            if so and so.status in {"SENDING", "ACCEPTED"}:
                enqueue(s, "supplier.cancel", f"cancel:{so.id}", {"supplier_order_id": so.id})
                review(s, "CANCELLATION_AFTER_SUPPLIER_ORDER", order.id)
            else:
                if so: so.status = "CANCELLED"
                release(s, order); transition(s, order, "CANCELLED")

    def cancel_supplier(self, supplier_order_id):
        with self.factory() as s:
            so = s.get(SupplierOrder, supplier_order_id); order = s.get(Order, so.order_id)
            _, _, supplier, _ = context(s, order)
            payload, mode = {"supplier_order_key": so.business_key}, supplier.mode
        receipt = self.registry.supplier(mode).cancel_order(payload, f"cancel:{supplier_order_id}")
        with self.factory.begin() as s:
            lock_treasury(s); so = s.get(SupplierOrder, supplier_order_id); order = s.get(Order, so.order_id)
            payment = s.scalar(select(Payment).where(Payment.order_id == order.id))
            if payment and payment.status in {"SENDING", "UNKNOWN", "SUCCEEDED"}:
                review(s, "CANCELLATION_AFTER_PAYMENT", order.id); return
            so.status = "CANCELLED"; release(s, order)
            transition(s, order, "CANCELLED")
            audit(s, "SUPPLIER_CANCELLATION_CONFIRMED", order.id, correlation_id=order.correlation_id)

    def add_shipment(self, s, raw, supplier_id=None):
        row = ShipmentRow.model_validate(raw)
        so = s.get(SupplierOrder, row.supplier_order_id)
        if so is None: raise DomainError("SUPPLIER_ORDER_NOT_FOUND")
        order = s.get(Order, so.order_id)
        if order.external_id != row.marketplace_order_id: raise DomainError("SHIPMENT_ORDER_MISMATCH")
        if supplier_id and context(s, order)[2].id != supplier_id: raise DomainError("SHIPMENT_SUPPLIER_MISMATCH")
        existing = s.scalar(select(Shipment).where(Shipment.order_id == order.id))
        if existing:
            if existing.courier != row.courier or existing.tracking != row.tracking: raise DomainError("TRACKING_CONFLICT")
            return existing
        if s.scalar(select(Shipment).where(Shipment.courier == row.courier, Shipment.tracking == row.tracking)):
            raise DomainError("DUPLICATE_TRACKING")
        if order.state != "SHIPMENT_PENDING" or order.cancel_requested: raise DomainError("ORDER_NOT_SHIPPABLE")
        shipment = Shipment(order_id=order.id, courier=row.courier, tracking=row.tracking)
        s.add(shipment); s.flush(); transition(s, order, "SHIPPED")
        enqueue(s, "marketplace.shipment", f"shipment:{shipment.id}", {"shipment_id": shipment.id})
        return shipment

    def sync_shipment(self, shipment_id):
        with self.factory() as s:
            row = s.get(Shipment, shipment_id); order = s.get(Order, row.order_id)
            payload = {"external_id": order.external_id, "external_line_id": order.external_line_id,
                       "courier": row.courier, "tracking": row.tracking}
            channel = order.marketplace
        self.registry.marketplace(channel).mark_shipped(payload, f"shipment:{shipment_id}")
        with self.factory.begin() as s:
            lock_treasury(s); row = s.get(Shipment, shipment_id); row.marketplace_synced = True
            audit(s, "MARKETPLACE_SHIPMENT_UPDATED", row.order_id, correlation_id=s.get(Order, row.order_id).correlation_id)

    def delivered(self, order_id):
        with self.factory.begin() as s:
            lock_treasury(s); order = s.get(Order, order_id)
            if order.delivered_at: return
            transition(s, order, "DELIVERED"); order.delivered_at = self.clock()
            revenue = order.gross_sale - order.discount
            post(s, f"sale:{order.id}", "SALE_RECOGNIZED", {"MARKETPLACE_RECEIVABLE": revenue-order.fee-order.promotion_cost,
                "REVENUE": -revenue, "MARKETPLACE_FEES": order.fee, "PROMOTION_EXPENSE": order.promotion_cost}, order.id, order.correlation_id)

    def sync_listing(self, listing_id, revision, desired_state, price):
        with self.factory() as s:
            listing = s.get(MarketplaceListing, listing_id)
            if listing.sync_revision != revision: return
            channel = listing.marketplace
        try:
            self.registry.marketplace(channel).invoke("sync_listing", {"listing_id": listing_id,
                "revision": revision, "state": desired_state, "price": price}, f"listing:{listing_id}:{revision}")
        except IntegrationError as exc:
            with self.factory.begin() as s:
                lock_treasury(s); listing = s.get(MarketplaceListing, listing_id)
                if listing.sync_revision == revision:
                    listing.remote_state = "UNCONFIRMED"
                    if listing.desired_state != "PAUSED": pause_listing(s, listing, "PRICE_SYNC_FAILED")
                review(s, "PRICE_SYNC_FAILED", listing_id, {"code": exc.code, "remote_pause_confirmed": False})
            raise
        with self.factory.begin() as s:
            lock_treasury(s); listing = s.get(MarketplaceListing, listing_id)
            if listing.sync_revision == revision:
                listing.remote_state, listing.last_synced_at = desired_state, self.clock()
                audit(s, "LISTING_SYNC_CONFIRMED", listing_id, new={"state": desired_state, "demo": self.settings.app_mode != "production"})
