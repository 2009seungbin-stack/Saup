"""Phase 11B typed commands: record an EXTERNAL marketplace cancellation, never send money.

Every attestation is a literal boolean true. Every settlement component is
required, even when zero: an omitted field is not silently treated as zero.
"""
from typing import Annotated, Literal
from pydantic import Field, field_validator
from .supplier_operations import Strict, Identifier, Reference, Hash, PositiveMoney, Money

Attestation = Literal[True]
# Marketplace identifiers are compared exactly with the stored order; they are not internal references.
Marketplace = Annotated[str, Field(min_length=1, max_length=24)]
ExternalId = Annotated[str, Field(min_length=1, max_length=100)]


def _literal_true(value):
    if value is not True:
        raise ValueError("EXPLICIT_TRUE_REQUIRED")
    return value


class MarketplaceRefundReceipt(Strict):
    idempotency_key: Reference
    snapshot_hash: Hash
    supplier_recovery_id: Identifier
    marketplace: Marketplace
    external_order_id: ExternalId
    external_line_id: ExternalId
    customer_refund_amount: PositiveMoney
    reference: Reference
    evidence_hash: Hash
    confirmed_customer_refunded: Attestation

    @field_validator("confirmed_customer_refunded", mode="before")
    @classmethod
    def explicit_attestation(cls, value):
        return _literal_true(value)


class MarketplaceCancellationStatementInput(Strict):
    idempotency_key: Reference
    snapshot_hash: Hash
    refund_evidence_id: Identifier
    customer_refund_amount: PositiveMoney
    seller_payout_amount: Money
    seller_debit_amount: Money
    retained_fee_amount: Money
    outstanding_balance: Money
    reference: Reference
    evidence_hash: Hash
    confirmed_final_statement: Attestation
    confirmed_marketplace_cancelled: Attestation

    @field_validator("confirmed_final_statement", "confirmed_marketplace_cancelled", mode="before")
    @classmethod
    def explicit_attestation(cls, value):
        return _literal_true(value)

    def residual(self) -> bool:
        return any((self.seller_payout_amount, self.seller_debit_amount, self.retained_fee_amount, self.outstanding_balance))


class MarketplaceCancellationCompletion(Strict):
    idempotency_key: Reference
    snapshot_hash: Hash
    refund_evidence_id: Identifier
    statement_id: Identifier
    confirmed_reconciliation: Attestation

    @field_validator("confirmed_reconciliation", mode="before")
    @classmethod
    def explicit_attestation(cls, value):
        return _literal_true(value)
