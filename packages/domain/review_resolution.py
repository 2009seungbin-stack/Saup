"""Typed, bounded review commands; there is deliberately no force-state command."""
from typing import Literal
from pydantic import field_validator
from .supplier_operations import Strict, Identifier, Reference, Hash, PositiveMoney, Money

CorrectionReason = Literal["WRONG_REFERENCE", "WRONG_ATTACHMENT", "REFERENCE_AND_ATTACHMENT"]


class CorrectionRequest(Strict):
    idempotency_key: Reference
    expected_revision_id: Identifier | None = None
    reason: CorrectionReason


class EvidenceCorrection(Strict):
    idempotency_key: Reference
    expected_revision_id: Identifier | None = None
    reference: Reference
    evidence_hash: Hash
    verified_same_payment: Literal[True]

    @field_validator("verified_same_payment", mode="before")
    @classmethod
    def explicit_attestation(cls, value):
        if value is not True:
            raise ValueError("EXPLICIT_TRUE_REQUIRED")
        return value


class CancellationRecoveryConfirm(Strict):
    idempotency_key: Reference
    supplier_id: Identifier
    payment_id: Identifier
    amount: PositiveMoney
    bank_amount: Money
    deposit_amount: Money
    destination_fingerprint: Hash
    reference: Reference
    evidence_hash: Hash
    confirmed_funds_received: Literal[True]

    @field_validator("confirmed_funds_received", mode="before")
    @classmethod
    def explicit_attestation(cls, value):
        if value is not True:
            raise ValueError("EXPLICIT_TRUE_REQUIRED")
        return value
