import base64
import hashlib
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
from packages.domain.errors import DomainError
from packages.infrastructure.models import ImportBatch, SupplierExcelProfile, SupplierOrder, Order, Supplier
from packages.integrations.suppliers.excel import ExcelProfile, parse, export_orders
from .catalog import apply_price
from .commerce import context
from .common import lock_treasury, enqueue, review, audit

class Files:
    def __init__(self, commerce):
        self.c, self.factory = commerce, commerce.factory

    def submit(self, profile_id, kind, data):
        if kind not in {"price", "shipment"}: raise DomainError("INVALID_IMPORT_KIND", 422)
        if len(data) > self.c.settings.upload_max_bytes: raise DomainError("FILE_TOO_LARGE", 413)
        hashed = hashlib.sha256(data).hexdigest()
        with self.factory.begin() as s:
            lock_treasury(s); profile = s.get(SupplierExcelProfile, profile_id)
            if profile is None: raise DomainError("PROFILE_NOT_FOUND", 404)
            prior = s.scalar(select(ImportBatch).where(ImportBatch.profile_id == profile.id,
                ImportBatch.profile_version == profile.version, ImportBatch.file_hash == hashed, ImportBatch.kind == kind))
            if prior: return prior.id
            row = ImportBatch(profile_id=profile.id, kind=kind, file_hash=hashed, profile_version=profile.version,
                profile_snapshot=profile.mapping, ciphertext=self.c.cipher.encrypt(base64.b64encode(data).decode()), status="QUEUED")
            s.add(row); s.flush()
            enqueue(s, "file.import", f"import:{row.id}", {"batch_id": row.id})
            return row.id

    def process(self, batch_id):
        with self.factory() as s:
            batch = s.get(ImportBatch, batch_id)
            if batch.status in {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}: return
            data = base64.b64decode(self.c.cipher.decrypt(batch.ciphertext))
            profile = ExcelProfile.model_validate(batch.profile_snapshot)
            kind = batch.kind
        try:
            parsed = parse(data, profile, kind)
        except (DomainError, ValidationError) as exc:
            with self.factory.begin() as s:
                lock_treasury(s); batch = s.get(ImportBatch, batch_id); batch.status = "FAILED"; batch.rejected = 1
                review(s, "SUPPLIER_FILE_ERROR", batch.id, {"code": getattr(exc, "code", "INVALID_PROFILE")})
            return
        with self.factory.begin() as s:
            lock_treasury(s); batch = s.get(ImportBatch, batch_id)
            if batch.status in {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}: return
            supplier_id = s.get(SupplierExcelProfile, batch.profile_id).supplier_id
            errors = list(parsed.errors); accepted = 0
            for index, row in parsed.rows:
                try:
                    with s.begin_nested():
                        if kind == "price": apply_price(s, self.c.settings, supplier_id, row, batch.file_hash, profile.sku_map)
                        else: self.c.add_shipment(s, row, supplier_id)
                        s.flush()
                    accepted += 1
                except (DomainError, ValidationError, IntegrityError) as exc:
                    errors.append({"row": index, "code": getattr(exc, "code", "ROW_VALIDATION_FAILED")})
            for error in errors:
                review(s, "SUPPLIER_FILE_ERROR", batch.id, error, key=f"file:{batch.id}:{error.get('row',0)}")
            batch.accepted, batch.rejected = accepted, len(errors)
            batch.status = "COMPLETED_WITH_ERRORS" if errors else "COMPLETED"
            audit(s, "SUPPLIER_FILE_IMPORTED", batch.id, new={"accepted": accepted, "rejected": len(errors)})

    def export(self, profile_id, actor):
        with self.factory.begin() as s:
            lock_treasury(s); profile = s.get(SupplierExcelProfile, profile_id)
            if profile is None: raise DomainError("PROFILE_NOT_FOUND", 404)
            if s.get(Supplier, profile.supplier_id).mode == "excel":
                raise DomainError("SUPPLIER_BATCH_REQUIRED")
            rows = []
            for so in s.scalars(select(SupplierOrder).where(SupplierOrder.status.in_(["FILE_READY", "ACCEPTED"]))):
                order = s.get(Order, so.order_id); _, sp, supplier, _ = context(s, order)
                if supplier.id != profile.supplier_id or order.cancel_requested: continue
                rows.append({"supplier_order_id": so.id, "marketplace_order_id": order.external_id,
                    "supplier_sku": sp.supplier_sku, "quantity": order.quantity,
                    **self.c.cipher.decrypt(order.pii_ciphertext)["original_address"]})
            data = export_orders(ExcelProfile.model_validate(profile.mapping), rows)
            audit(s, "SUPPLIER_ORDER_FILE_EXPORTED", profile_id, actor=actor, new={"rows": len(rows)}, reason="PII_EXPORT")
            return data
