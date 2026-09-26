"""Typed review resolution endpoints reuse the existing auth/CSRF boundary."""
from fastapi import APIRouter, Depends, Query
from packages.domain.supplier_operations import Actor
from packages.domain.review_resolution import CorrectionRequest, EvidenceCorrection, CancellationRecoveryConfirm
from packages.domain.marketplace_cancellation import (
    MarketplaceRefundReceipt, MarketplaceCancellationStatementInput, MarketplaceCancellationCompletion)


def create_review_resolution_router(service, viewer, operator, admin):
    router = APIRouter(prefix="/v1", tags=["review-resolution"])

    def actor(user):
        return Actor(user["username"], user["role"])

    @router.get("/review-resolutions")
    def reviews(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0, le=100000), user=Depends(viewer)):
        return service.list_reviews(limit, offset)

    @router.get("/review-resolutions/{review_id}")
    def detail(review_id: str, user=Depends(operator)):
        return service.get_review(review_id)

    @router.post("/supplier-payment-evidence/{evidence_id}/correction-request", status_code=201)
    def request(evidence_id: str, data: CorrectionRequest, user=Depends(operator)):
        return service.request_correction(evidence_id, data.model_dump(), actor(user))

    @router.post("/review-resolutions/{review_id}/correct-payment-evidence")
    def correction(review_id: str, data: EvidenceCorrection, user=Depends(admin)):
        return service.correct_evidence(review_id, data.model_dump(), actor(user))

    @router.post("/review-resolutions/{review_id}/confirm-supplier-recovery")
    def recovery(review_id: str, data: CancellationRecoveryConfirm, user=Depends(admin)):
        return service.confirm_recovery(review_id, data.model_dump(), actor(user))

    # Phase 11B records EXTERNAL marketplace refund/statement evidence; none of these send money.
    @router.post("/review-resolutions/{review_id}/record-marketplace-refund")
    def marketplace_refund(review_id: str, data: MarketplaceRefundReceipt, user=Depends(admin)):
        return service.record_marketplace_refund(review_id, data.model_dump(), actor(user))

    @router.post("/review-resolutions/{review_id}/record-marketplace-statement")
    def marketplace_statement(review_id: str, data: MarketplaceCancellationStatementInput, user=Depends(admin)):
        return service.record_marketplace_statement(review_id, data.model_dump(), actor(user))

    @router.post("/review-resolutions/{review_id}/complete-marketplace-cancellation")
    def marketplace_complete(review_id: str, data: MarketplaceCancellationCompletion, user=Depends(admin)):
        return service.complete_marketplace_cancellation(review_id, data.model_dump(), actor(user))

    return router
