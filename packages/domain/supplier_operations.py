"""Provider-neutral supplier states and strict operator commands."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .errors import DomainError

Reference = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")]
Identifier = Annotated[str, Field(min_length=1, max_length=36)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Money = Annotated[int, Field(strict=True, ge=0, le=10**12)]
PositiveMoney = Annotated[int, Field(strict=True, gt=0, le=10**12)]

@dataclass(frozen=True)
class Actor:
    username: str
    role: str

    def require(self, minimum="operator"):
        ranks = {"viewer": 0, "operator": 1, "admin": 2}
        if not self.username or len(self.username) > 80 or ranks.get(self.role, -1) < ranks[minimum]:
            raise DomainError("FORBIDDEN", 403)

class RejectionReason(StrEnum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PRICE_CHANGED = "PRICE_CHANGED"
    SKU_NOT_FOUND = "SKU_NOT_FOUND"
    ORDER_NOT_ACCEPTED = "ORDER_NOT_ACCEPTED"
    DELIVERY_UNAVAILABLE = "DELIVERY_UNAVAILABLE"
    CUTOFF_EXCEEDED = "CUTOFF_EXCEEDED"
    OTHER = "OTHER"

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class BatchCreate(Strict):
    supplier_id: Identifier
    profile_id: Identifier
    supplier_order_ids: list[Identifier] = Field(min_length=1, max_length=500)
    idempotency_key: Reference
    payment_path: Literal["MANUAL_EVIDENCE", "DEMO_PROVIDER"] = "MANUAL_EVIDENCE"

class MarkSent(Strict):
    send_channel: Literal["EMAIL", "PORTAL", "MESSENGER", "MANUAL", "OTHER"]
    send_reference: Reference
    file_hash: Hash

class RejectedLine(Strict):
    supplier_order_id: Identifier
    reason: RejectionReason

class ReportedChange(Strict):
    supplier_order_id: Identifier
    amount: PositiveMoney | None = None
    shipping: Money | None = None
    quantity: Annotated[int, Field(strict=True, ge=1, le=1000)] | None = None
    sku: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    destination_changed: bool = False

class Acknowledge(Strict):
    accepted_order_ids: list[Identifier] = Field(default_factory=list, max_length=500)
    rejected: list[RejectedLine] = Field(default_factory=list, max_length=500)
    reported_changes: list[ReportedChange] = Field(default_factory=list, max_length=500)
    reference: Reference

    def canonical(self):
        value = self.model_dump(mode="json")
        value["accepted_order_ids"].sort()
        for key in ("rejected", "reported_changes"):
            value[key].sort(key=lambda row: row["supplier_order_id"])
        return value

class EvidenceRecord(Strict):
    supplier_id: Identifier
    method: Literal["SUPPLIER_DEPOSIT", "MANUAL_TRANSFER", "PROVIDER_RECEIPT", "OTHER_APPROVED_METHOD"]
    amount: PositiveMoney
    bank_amount: Money
    deposit_amount: Money
    destination_fingerprint: Hash
    reference: Reference
    evidence_hash: Hash

    @model_validator(mode="after")
    def allocations(self):
        if self.bank_amount + self.deposit_amount != self.amount:
            raise ValueError("EVIDENCE_ALLOCATION_MISMATCH")
        if self.method == "SUPPLIER_DEPOSIT" and self.bank_amount:
            raise ValueError("DEPOSIT_METHOD_BANK_MISMATCH")
        if self.method == "MANUAL_TRANSFER" and self.deposit_amount:
            raise ValueError("TRANSFER_METHOD_DEPOSIT_MISMATCH")
        return self

class EvidenceConfirm(Strict):
    evidence_revision_id: Identifier | None = None
    amount: PositiveMoney
    destination_fingerprint: Hash
    reference: Reference
    confirmed_money_moved: Literal[True]

class CancellationConfirm(Strict):
    reference: Reference
    supplier_confirmed_cancelled: Literal[True]

class LegacyAdopt(Strict):
    reference: Reference
    verified_never_sent: Literal[True]

class Revalidate(Strict):
    reference: Reference
    original_terms_reconfirmed: Literal[True]

# These are supplier states, not marketplace Order.state. API-mode ACCEPTED and
# SENDING remain in their existing adapter lifecycle and never enter this graph.
TRANSITIONS = {
    "PENDING": {"BATCHED", "CANCELLED", "MANUAL_REVIEW"},
    "BATCHED": {"FILE_READY", "CANCELLED", "MANUAL_REVIEW"},
    "FILE_READY": {"EXPORTED", "SENT", "PENDING", "CANCELLED", "MANUAL_REVIEW"},
    "EXPORTED": {"SENT", "PENDING", "CANCELLED", "MANUAL_REVIEW"},
    "SENT": {"ACKNOWLEDGED", "REJECTED", "MANUAL_REVIEW", "CANCEL_PENDING"},
    "ACKNOWLEDGED": {"PAYMENT_PENDING", "MANUAL_REVIEW", "CANCEL_PENDING"},
    "PAYMENT_PENDING": {"PAID", "MANUAL_REVIEW", "CANCEL_PENDING"},
    "PAID": {"SHIPMENT_PENDING", "CANCEL_PENDING"},
    "SHIPMENT_PENDING": {"SHIPPED", "CANCEL_PENDING"},
    "SHIPPED": {"CANCEL_PENDING"},
    "REJECTED": {"CANCELLED"},
    "CANCEL_PENDING": {"CANCELLED"},
    "CANCELLED": set(),
    "MANUAL_REVIEW": {"ACKNOWLEDGED", "PENDING", "REJECTED", "CANCEL_PENDING", "CANCELLED"},
}

def validate_supplier_transition(current: str, target: str):
    if current != target and target not in TRANSITIONS.get(current, set()):
        raise DomainError("INVALID_SUPPLIER_ORDER_TRANSITION")
