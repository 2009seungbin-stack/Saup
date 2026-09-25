"""PII-minimal read models and explicitly privileged supplier commands."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from packages.domain.supplier_operations import (
    Actor, BatchCreate, MarkSent, Acknowledge, EvidenceRecord, EvidenceConfirm, CancellationConfirm, Revalidate, LegacyAdopt,
)
from packages.infrastructure.models import Supplier, AuditEvent, Payment, SupplierPaymentEvidence, SupplierCancellation


def create_supplier_operations_router(service, viewer, operator, admin):
    router = APIRouter(prefix="/v1", tags=["supplier-operations"])

    def actor(user):
        return Actor(username=user["username"], role=user["role"])

    @router.get("/suppliers")
    def suppliers(user=Depends(viewer)):
        with service.factory() as s:
            return [{"id": row.id, "name": row.name, "mode": row.mode, "active": row.active}
                    for row in s.scalars(select(Supplier).order_by(Supplier.id).limit(500))]

    @router.get("/supplier-orders/eligible")
    def eligible_orders(user=Depends(operator)):
        return service.candidates()

    @router.post("/supplier-order-batches", status_code=201)
    def create_batch(data: BatchCreate, user=Depends(operator)):
        return service.create_batch(data.model_dump(), actor(user))

    @router.get("/supplier-order-batches")
    def batches(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0, le=100000), user=Depends(viewer)):
        return service.list_batches(limit=limit, offset=offset)

    @router.get("/supplier-order-batches/{batch_id}")
    def batch(batch_id: str, user=Depends(viewer)):
        return service.get_batch(batch_id)

    @router.get("/supplier-order-batches/{batch_id}/file")
    def export_batch(batch_id: str, user=Depends(operator)):
        data, filename = service.export_batch(batch_id, actor(user))
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})

    @router.post("/supplier-order-batches/{batch_id}/mark-sent")
    def mark_sent(batch_id: str, data: MarkSent, user=Depends(operator)):
        return service.mark_sent(batch_id, data.model_dump(), actor(user))

    @router.post("/supplier-order-batches/{batch_id}/acknowledge")
    def acknowledge(batch_id: str, data: Acknowledge, user=Depends(operator)):
        return service.acknowledge(batch_id, data.model_dump(), actor(user))

    @router.post("/supplier-order-batches/{batch_id}/cancel")
    def cancel_batch(batch_id: str, user=Depends(operator)):
        return service.cancel_batch(batch_id, actor(user))

    @router.post("/supplier-order-batches/{batch_id}/resolve")
    def resolve_batch(batch_id: str, user=Depends(admin)):
        return service.resolve_batch(batch_id, actor(user))

    @router.post("/supplier-orders/{supplier_order_id}/cancel")
    def cancel_order(supplier_order_id: str, user=Depends(operator)):
        return service.cancel_order(supplier_order_id, actor(user))

    @router.post("/supplier-orders/{supplier_order_id}/cancellation/confirm")
    def confirm_cancel(supplier_order_id: str, data: CancellationConfirm, user=Depends(admin)):
        return service.confirm_cancellation(supplier_order_id, data.model_dump(), actor(user))

    @router.post("/supplier-orders/{supplier_order_id}/revalidate")
    def revalidate(supplier_order_id: str, data: Revalidate, user=Depends(admin)):
        return service.revalidate_original_terms(supplier_order_id, data.model_dump(), actor(user))

    @router.post("/supplier-orders/{supplier_order_id}/adopt-verified-unsent")
    def adopt_legacy(supplier_order_id: str, data: LegacyAdopt, user=Depends(admin)):
        return service.adopt_verified_unsent_legacy(supplier_order_id, data.model_dump(), actor(user))

    @router.get("/supplier-payments/{payment_id}")
    def payment(payment_id: str, user=Depends(operator)):
        return service.payment_details(payment_id, actor(user))

    @router.post("/supplier-payments/{payment_id}/evidence", status_code=201)
    def evidence(payment_id: str, data: EvidenceRecord, user=Depends(operator)):
        return service.record_evidence(payment_id, data.model_dump(), actor(user))

    @router.post("/supplier-payment-evidence/{evidence_id}/confirm")
    def confirm_evidence(evidence_id: str, data: EvidenceConfirm, user=Depends(admin)):
        return service.confirm_evidence(evidence_id, data.model_dump(), actor(user))

    @router.get("/supplier-operations/metrics")
    def metrics(user=Depends(viewer)):
        return service.metrics()

    @router.get("/supplier-order-batches/{batch_id}/trail")
    def trail(batch_id: str, user=Depends(viewer)):
        batch = service.get_batch(batch_id)
        ids = {batch_id}
        for row in batch["items"]:
            ids.update(row[key] for key in ("supplier_order_id", "order_id", "payment_id", "evidence_id") if row[key])
        with service.factory() as s:
            return [{"id": event.id, "event": event.event, "actor": event.actor,
                     "entity_id": event.entity_id, "created_at": event.created_at,
                     "old_value": event.old_value, "new_value": event.new_value, "reason": event.reason}
                    for event in s.scalars(select(AuditEvent).where(AuditEvent.entity_id.in_(ids))
                        .order_by(AuditEvent.created_at, AuditEvent.id).limit(1000))]

    return router
