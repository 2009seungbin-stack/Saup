"""Bounded operator inputs. Every external confirmation is an explicit boolean."""
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, StrictBool, SecretStr, field_validator
from .supplier_operations import Strict, Identifier, Reference, Hash, Money, PositiveMoney
from .marketplace_cancellation import _literal_true


class SupplierInput(Strict):
    name: str = Field(min_length=1, max_length=120, pattern=r'^\S(?:[^\r\n\t]*\S)?$')
    mode: Literal['excel'] = 'excel'
    cutoff: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    claim_days: Annotated[int, Field(strict=True, ge=1, le=90)]
    active: StrictBool


class UserInput(Strict):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]+$')
    role: Literal['viewer', 'operator', 'admin']
    password: SecretStr = Field(min_length=12, max_length=128)


class ListingInput(Strict):
    supplier_product_id: Identifier
    marketplace: Literal['coupang', 'temu', 'aliexpress']
    fee_rate: Decimal = Field(ge=0, lt=1, max_digits=7, decimal_places=6)


class Evidence(Strict):
    reference: Reference
    evidence_hash: Hash
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit(cls, value):
        return _literal_true(value)


class FundsInput(Evidence):
    amount: PositiveMoney


class ListingActivation(Evidence):
    price: PositiveMoney
    external_id: str = Field(min_length=1, max_length=100)


class ShipmentConfirmation(Evidence):
    marketplace: Literal['coupang', 'temu', 'aliexpress']
    external_order_id: str = Field(min_length=1, max_length=100)
    external_line_id: str = Field(min_length=1, max_length=100)
    tracking_hash: Hash


class ClaimInput(Strict):
    external_id: Reference = Field(max_length=120)
    category: Literal['ROTTEN', 'BROKEN', 'BRUISED', 'WRONG_ITEM', 'MISSING_WEIGHT', 'DELIVERY_DELAY',
                      'CHANGE_OF_MIND', 'TASTE_COMPLAINT', 'ADDRESS_ERROR', 'MISSING_ITEM', 'OTHER']
    amount: PositiveMoney
    evidence: list[Literal['parcel_label', 'entire_contents', 'damage_closeup']] = Field(max_length=3)


class ClaimResponse(Evidence):
    accepted: StrictBool
    amount: Money


class RefundRequest(Strict):
    amount: PositiveMoney
    key: Reference


class RefundConfirmation(Evidence):
    order_id: Identifier
    claim_id: Identifier
    amount: PositiveMoney
    marketplace: Literal['coupang', 'temu', 'aliexpress']
    confirmed_customer_refunded: Literal[True]

    @field_validator('confirmed_customer_refunded', mode='before')
    @classmethod
    def explicit_refund(cls, value):
        return _literal_true(value)


class SettlementInput(Evidence):
    external_id: Reference = Field(max_length=120)
    actual: Money
    adjustment: Annotated[int, Field(strict=True, ge=-10**9, le=10**9)]


class CashConfirmation(FundsInput):
    amount: Money
    expected_revision: Annotated[int, Field(strict=True, ge=0)]


class SettlementCorrection(SettlementInput):
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    reason: Literal['WRONG_AMOUNT', 'WRONG_REFERENCE', 'WRONG_ADJUSTMENT', 'REPLACEMENT_STATEMENT']
