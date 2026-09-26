"""Operational file intake and narrowly guarded, evidence-backed order validation.

No new schema/framework: atomic Command receipts and immutable AuditEvent records
retain provenance. Uploads are parsed in memory; only the existing encrypted Order
address is persisted. Neither a preview nor import releases supplier work.
"""
import hashlib
from datetime import timedelta
from cryptography.fernet import InvalidToken
from pydantic import TypeAdapter
from sqlalchemy import select
from packages.domain.errors import DomainError
from packages.domain.schemas import OrderInput
from packages.domain.order_intake import ImportConfirmation, VerifyImportedOrder, Market
from packages.infrastructure.models import (Command, Order, MarketplaceListing, SupplierProduct,
    Supplier, Product, SupplierOrder, Payment, Reservation, Review, AuditEvent, MarketplaceRefundEvidence)
from packages.infrastructure.security import fingerprint
from packages.infrastructure.schema_v1 import uid
from packages.infrastructure.db import aware
from packages.integrations.marketplaces.order_file import parse_orders, VERSION, template
from packages.integrations.suppliers.excel import workbook_bytes
from .common import lock_treasury, execute_command, audit, review
from .supplier_operations import intervention, resolve_reviews
from .order_rules import context

IMPORT_SCOPE = "orders.file.commit"
VERIFY_SCOPE = "orders.file.verify"
SOURCE_REVIEW = "MARKETPLACE_ORDER_SOURCE_VERIFICATION_REQUIRED"
SOURCE_EVENT = "ORDER_IMPORTED_FROM_FILE"
# Only failures before any reservation/external work may be retried here.
RETRY_REVIEWS = {"ADDRESS_ERROR", "SUPPLIER_INACTIVE", "LISTING_PAUSED", "TAX_CLASSIFICATION_REQUIRED",
    "OUT_OF_SEASON", "UNKNOWN_INVENTORY", "OUT_OF_STOCK", "STALE_INVENTORY", "SUPPLIER_CUTOFF",
    "MARGIN_BELOW_THRESHOLD", "INSUFFICIENT_CASH"}


class OrderIntake:
    def __init__(self, commerce):
        self.c, self.factory = commerce, commerce.factory

    def _parse(self, data, marketplace):
        TypeAdapter(Market).validate_python(marketplace)
        if len(data) > self.c.settings.upload_max_bytes:
            raise DomainError("FILE_TOO_LARGE", 413)
        return parse_orders(data, marketplace)

    def _preview(self, s, parsed, file_hash, marketplace):
        rows, errors = [], list(parsed.errors)
        for row_no, raw in parsed.rows:
            listing = s.get(MarketplaceListing, raw["listing_id"])
            sp = s.get(SupplierProduct, listing.supplier_product_id) if listing else None
            supplier = s.get(Supplier, sp.supplier_id) if sp else None
            product = s.get(Product, sp.product_id) if sp else None
            existing = s.scalar(select(Order).where(Order.marketplace == marketplace,
                Order.external_id == raw["external_id"], Order.external_line_id == raw["external_line_id"]))
            code = None
            if listing is None or listing.marketplace != marketplace:
                code = "INVALID_LISTING"
            elif supplier is None or supplier.mode != "excel":
                code = "ORDER_FILE_REQUIRES_EXCEL_SUPPLIER"
            elif existing and existing.input_hash != fingerprint(raw):
                code = "ORDER_IDENTITY_PAYLOAD_CONFLICT"
            if code:
                errors.append({"row": row_no, "code": code})
            # No address, phone, encrypted address or raw Pydantic error in any view.
            rows.append({"row": row_no, "external_id": raw["external_id"], "external_line_id": raw["external_line_id"],
                "listing_id": raw["listing_id"], "product_title": product.title if product else None,
                "quantity": raw["quantity"], "net_amount": raw["gross_sale"]-raw["discount"],
                "status": "ERROR" if code else "DUPLICATE" if existing else "READY",
                "order_id": existing.id if existing else None, "existing_state": existing.state if existing else None})
        result = {"template_version": VERSION, "marketplace": marketplace, "file_hash": file_hash,
            "rows": rows, "errors": sorted(errors, key=lambda x: (x["row"], x["code"])),
            "new_count": sum(r["status"] == "READY" for r in rows),
            "duplicate_count": sum(r["status"] == "DUPLICATE" for r in rows), "error_count": len(errors),
            "can_commit": not errors, "supplier_acceptance": "NOT_CONFIRMED", "money_moved": False}
        return result

    def preview(self, data: bytes, marketplace: str, actor):
        actor.require()
        parsed = self._parse(data, marketplace)
        hashed = hashlib.sha256(data).hexdigest()
        with self.factory() as s:
            result = self._preview(s, parsed, hashed, marketplace)
        # Ticket contains only hashes and operator identity, never encrypted PII.
        # A signature/integrity-protected token is not a persisted draft file.
        token = {"purpose": "order-file-preview", "version": VERSION, "file_hash": hashed,
            "marketplace": marketplace, "actor": actor.username, "preview_hash": fingerprint(result),
            "expires_at": (self.c.clock()+timedelta(minutes=10)).timestamp()}
        return result | {"preview_token": self.c.cipher.encrypt(token), "preview_expires_at": token["expires_at"]}

    def commit(self, data: bytes, raw: dict, actor):
        actor.require()
        cmd = ImportConfirmation.model_validate(raw)
        parsed = self._parse(data, cmd.marketplace)
        file_hash = hashlib.sha256(data).hexdigest()
        try:
            ticket = self.c.cipher.decrypt(cmd.preview_token)
            if (ticket["purpose"] != "order-file-preview" or ticket["version"] != VERSION or
                    ticket["marketplace"] != cmd.marketplace or ticket["file_hash"] != file_hash or
                    ticket["actor"] != actor.username):
                raise ValueError("mismatch")
        except (InvalidToken, KeyError, TypeError, ValueError, UnicodeError):
            raise DomainError("ORDER_PREVIEW_TOKEN_INVALID", 409) from None
        key = fingerprint([VERSION, cmd.marketplace, file_hash])
        payload = {"file_hash": file_hash, "marketplace": cmd.marketplace, "template_version": VERSION,
            "source_reference": cmd.source_reference, "confirmed_authorized_source": True}
        with self.factory.begin() as s:
            lock_treasury(s)
            existing = s.scalar(select(Command).where(Command.scope == IMPORT_SCOPE, Command.key == key))
            if existing:
                if existing.payload_hash != fingerprint(payload):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return existing.result | {"replayed": True}
            if ticket["expires_at"] < self.c.clock().timestamp():
                raise DomainError("ORDER_PREVIEW_EXPIRED")
            current = self._preview(s, parsed, file_hash, cmd.marketplace)
            if current["error_count"]:
                raise DomainError("ORDER_FILE_HAS_ERRORS", 422)
            if ticket["preview_hash"] != fingerprint(current):
                raise DomainError("ORDER_PREVIEW_STALE")
            def action():
                import_id, items = uid(), []
                for row_no, order_raw in parsed.rows:
                    item = self.c.ingest_in_session(s, OrderInput.model_validate(order_raw), enqueue_processing=False)
                    items.append({"row": row_no, **item})
                    order = s.get(Order, item["id"])
                    if not item["duplicate"]:
                        audit(s, SOURCE_EVENT, order.id, actor=actor.username, source="manual_marketplace_file",
                            new={"import_id": import_id, "file_hash": file_hash, "template_version": VERSION,
                                "source_reference_hash": fingerprint(cmd.source_reference), "row": row_no,
                                "input_hash": order.input_hash, "marketplace_status_verified": False},
                            correlation_id=order.correlation_id)
                        review(s, SOURCE_REVIEW, order.id, {"import_id": import_id, "file_hash": file_hash})
                        intervention(s, "ORDER_IMPORTED_MANUALLY", f"order-file:{order.id}", actor.username,
                            self.c.clock(), order=order)
                result = {"id": import_id, "file_hash": file_hash, "marketplace": cmd.marketplace,
                    "template_version": VERSION, "created_by": actor.username, "created_at": self.c.clock().isoformat(),
                    "new_count": sum(not x["duplicate"] for x in items),
                    "duplicate_count": sum(x["duplicate"] for x in items), "items": items,
                    "next_step": "VERIFY_CURRENT_MARKETPLACE_STATUS", "money_moved": False}
                audit(s, "MARKETPLACE_ORDER_FILE_IMPORTED", import_id, actor=actor.username,
                    new={"file_hash": file_hash, "new_count": result["new_count"], "duplicate_count": result["duplicate_count"]})
                return result
            return execute_command(s, IMPORT_SCOPE, key, payload, action) | {"replayed": False}

    def history(self, limit=50):
        with self.factory() as s:
            # General history deliberately omits receipts, order details and source references.
            fields = {"id", "file_hash", "marketplace", "template_version", "created_by", "created_at", "new_count", "duplicate_count"}
            return [{k: v for k, v in row.result.items() if k in fields} for row in s.scalars(select(Command)
                .where(Command.scope == IMPORT_SCOPE).order_by(Command.created_at.desc(), Command.id).limit(limit))]

    def catalog_file(self, marketplace, actor):
        actor.require(); TypeAdapter(Market).validate_python(marketplace)
        with self.factory() as s:
            rows = []
            for listing, product, supplier in s.execute(select(MarketplaceListing, Product, Supplier)
                    .join(SupplierProduct, MarketplaceListing.supplier_product_id == SupplierProduct.id)
                    .join(Product, SupplierProduct.product_id == Product.id)
                    .join(Supplier, SupplierProduct.supplier_id == Supplier.id)
                    .where(MarketplaceListing.marketplace == marketplace, Supplier.mode == "excel")
                    .order_by(MarketplaceListing.id).limit(1000)):
                rows.append([listing.id, product.sku, product.title, supplier.name, listing.price, listing.desired_state])
            return workbook_bytes(["판매상품ID", "내부SKU", "상품명", "공급사", "현재판매가", "내부상태"], rows, "판매상품")

    def _source(self, s, order):
        source = s.scalar(select(AuditEvent).where(AuditEvent.entity_id == order.id, AuditEvent.event == SOURCE_EVENT)
            .order_by(AuditEvent.created_at, AuditEvent.id).limit(1))
        if source is None or source.new_value.get("input_hash") != order.input_hash:
            raise DomainError("ORDER_NOT_FROM_VERIFIED_IMPORT")
        return source

    def _eligible(self, s, order):
        self._source(s, order)
        if order.cancel_requested or order.state not in {"RECEIVED", "MANUAL_REVIEW"}:
            raise DomainError("ORDER_NOT_VALIDATABLE")
        if any(s.scalar(select(cls.id).where(cls.order_id == order.id)) for cls in (SupplierOrder, Reservation, Payment)):
            raise DomainError("ORDER_ALREADY_HAS_BUSINESS_EFFECTS")
        if context(s, order)[2].mode != "excel":
            raise DomainError("ORDER_FILE_REQUIRES_EXCEL_SUPPLIER")
        if s.scalar(select(MarketplaceRefundEvidence.id).where(MarketplaceRefundEvidence.marketplace == order.marketplace,
                MarketplaceRefundEvidence.external_order_id == order.external_id)):
            raise DomainError("MARKETPLACE_LINE_AFTER_CANCELLATION_EVIDENCE")
        categories = list(s.scalars(select(Review.category).where(Review.entity_id == order.id, Review.status != "RESOLVED")))
        if any(x not in RETRY_REVIEWS | {SOURCE_REVIEW} for x in categories):
            raise DomainError("ORDER_HAS_UNSUPPORTED_REVIEW")
        if self.c.clock() < aware(order.hold_until):
            raise DomainError("ORDER_HOLD")

    def _snapshot(self, s, order):
        listing, sp, supplier, product = context(s, order)
        return fingerprint({"order_id": order.id, "input_hash": order.input_hash, "state": order.state,
            "cancel_requested": order.cancel_requested, "hold_until": aware(order.hold_until).isoformat(),
            "listing": [listing.id, listing.desired_state, listing.price, str(listing.fee_rate), listing.claim_allowance, listing.promotion_cost],
            "supplier": [supplier.id, supplier.mode, supplier.active, supplier.cutoff, supplier.destination_fingerprint, supplier.destination_approved],
            "stock": [sp.id, sp.cost, sp.shipping, sp.stock, sp.stock_status, aware(sp.last_inventory_at).isoformat()],
            "product": [product.tax_type, product.season_state],
            "reviews": sorted(s.scalars(select(Review.id).where(Review.entity_id == order.id, Review.status != "RESOLVED")))})

    def _view(self, s, order):
        reasons = []
        try:
            self._eligible(s, order)
        except DomainError as exc:
            reasons.append(exc.code)
        source = s.scalar(select(AuditEvent).where(AuditEvent.entity_id == order.id, AuditEvent.event == SOURCE_EVENT).limit(1))
        return {"id": order.id, "marketplace": order.marketplace, "external_id": order.external_id,
            "external_line_id": order.external_line_id, "state": order.state, "cancel_requested": order.cancel_requested,
            "quantity": order.quantity, "net_amount": order.gross_sale-order.discount,
            "snapshot_hash": self._snapshot(s, order), "can_verify_and_validate": not reasons, "blocked_reasons": reasons,
            "file_hash": source.new_value["file_hash"] if source else None,
            "hold_until": aware(order.hold_until).isoformat(),
            "reviews": [{"category": r.category, "status": r.status} for r in s.scalars(select(Review)
                .where(Review.entity_id == order.id, Review.status != "RESOLVED").order_by(Review.category))]}

    def pending_orders(self, limit=100):
        with self.factory() as s:
            query = select(Order).where(Order.state.in_(["RECEIVED", "MANUAL_REVIEW"]),
                select(AuditEvent.id).where(AuditEvent.entity_id == Order.id, AuditEvent.event == SOURCE_EVENT).exists())
            return [self._view(s, order) for order in s.scalars(query.order_by(Order.created_at, Order.id).limit(limit))]

    def order_details(self, order_id):
        with self.factory() as s:
            order = s.get(Order, order_id)
            if order is None: raise DomainError("ORDER_NOT_FOUND", 404)
            self._source(s, order)
            return self._view(s, order)

    def verify_and_validate(self, order_id, raw, actor):
        actor.require(); cmd = VerifyImportedOrder.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s)
            def action():
                order = s.get(Order, order_id)
                if order is None: raise DomainError("ORDER_NOT_FOUND", 404)
                self._eligible(s, order)
                if self._snapshot(s, order) != cmd.snapshot_hash:
                    raise DomainError("ORDER_VALIDATION_SNAPSHOT_STALE")
                age = (self.c.clock()-cmd.observed_at).total_seconds()
                if not 0 <= age <= 900:
                    raise DomainError("CURRENT_MARKETPLACE_EVIDENCE_REQUIRED")
                # Evidence attests only what the operator checked, never an API response.
                audit(s, "MARKETPLACE_ORDER_STATUS_VERIFIED_MANUALLY", order.id, actor=actor.username,
                    source="manual_marketplace_observation", new={"status": "OPEN", "evidence_hash": cmd.evidence_hash,
                        "reference_hash": fingerprint(cmd.source_reference), "observed_at": cmd.observed_at.isoformat(),
                        "snapshot_hash": cmd.snapshot_hash, "api_verified": False}, correlation_id=order.correlation_id)
                self.c.validate_received_in_session(s, order)
                resolve_reviews(s, order.id, [SOURCE_REVIEW], actor.username, self.c.clock(), "MANUAL_SOURCE_VERIFIED_NOT_SUPPLIER_ACCEPTED")
                if order.state == "SUPPLIER_ORDER_PENDING":
                    resolve_reviews(s, order.id, list(RETRY_REVIEWS), actor.username, self.c.clock(), "ORDER_VALIDATION_RETRIED")
                intervention(s, "ORDER_SOURCE_VERIFIED_MANUALLY", f"order-verify:{order.id}:{cmd.idempotency_key}",
                    actor.username, self.c.clock(), order=order)
                return {"id": order.id, "state": order.state, "supplier_accepted": False,
                    "money_moved": False, "api_verified": False}
            return execute_command(s, VERIFY_SCOPE, cmd.idempotency_key,
                {"order_id": order_id, **cmd.model_dump(mode="json")}, action)
