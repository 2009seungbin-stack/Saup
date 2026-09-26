"""Read-only effective evidence projection; original proof stays immutable."""
from sqlalchemy import select
from packages.infrastructure.models import SupplierPaymentEvidence, SupplierEvidenceRevision, Review


def effective_evidence(s, proof):
    revision = s.scalar(select(SupplierEvidenceRevision).where(
        SupplierEvidenceRevision.evidence_id == proof.id).order_by(SupplierEvidenceRevision.revision.desc()).limit(1))
    return {"revision_id": revision.id if revision else None, "version": revision.revision if revision else 0,
        "reference": revision.reference if revision else proof.reference,
        "evidence_hash": revision.evidence_hash if revision else proof.evidence_hash}


def correction_pending(s, evidence_id):
    return s.scalar(select(Review.id).where(Review.entity_id == evidence_id,
        Review.category == "SUPPLIER_PAYMENT_EVIDENCE_CORRECTION", Review.status != "RESOLVED")) is not None


def reference_in_use(s, supplier_id, reference, payment_id):
    if s.scalar(select(SupplierPaymentEvidence.id).where(SupplierPaymentEvidence.supplier_id == supplier_id,
            SupplierPaymentEvidence.reference == reference, SupplierPaymentEvidence.payment_id != payment_id)):
        return True
    return s.scalar(select(SupplierEvidenceRevision.id).join(SupplierPaymentEvidence,
        SupplierEvidenceRevision.evidence_id == SupplierPaymentEvidence.id).where(
            SupplierPaymentEvidence.supplier_id == supplier_id, SupplierPaymentEvidence.payment_id != payment_id,
            SupplierEvidenceRevision.reference == reference)) is not None
