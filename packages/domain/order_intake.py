"""Explicit file-source contracts. Importing a file is not marketplace confirmation."""
from datetime import datetime
from typing import Literal
from pydantic import Field, field_validator
from .supplier_operations import Strict, Hash, Reference

Market = Literal["coupang", "temu", "aliexpress"]


class ImportConfirmation(Strict):
    marketplace: Market
    preview_token: str = Field(min_length=40, max_length=3000)
    source_reference: Reference
    confirmed_authorized_source: Literal[True]

    @field_validator("confirmed_authorized_source", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("EXPLICIT_TRUE_REQUIRED")
        return value


class VerifyImportedOrder(Strict):
    idempotency_key: Reference
    snapshot_hash: Hash
    source_reference: Reference
    evidence_hash: Hash
    observed_at: datetime
    confirmed_current_order_open: Literal[True]

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("TIMEZONE_REQUIRED")
        return value

    @field_validator("confirmed_current_order_open", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("EXPLICIT_TRUE_REQUIRED")
        return value
