import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Money = Annotated[StrictInt, Field(ge=0, le=10**12)]
PositiveMoney = Annotated[StrictInt, Field(gt=0, le=10**12)]
Identifier = Annotated[str, Field(min_length=1, max_length=100)]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Address(StrictModel):
    recipient: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=9, max_length=20)
    postal_code: str = Field(pattern=r"^\d{5}$")
    address1: str = Field(min_length=5, max_length=200)
    address2: str = Field(default="", max_length=200)

    @field_validator("recipient", "address1", "address2")
    @classmethod
    def no_control(cls, value):
        if any(ord(x) < 32 for x in value) or (value and not value.strip()):
            raise ValueError("INVALID_ADDRESS")
        return value  # Validation only; never rewrite the user's address.

    @field_validator("phone")
    @classmethod
    def phone_valid(cls, value):
        if not re.fullmatch(r"0[0-9-]{8,14}", value):
            raise ValueError("INVALID_PHONE")
        digits = value.replace("-", "")
        if not 9 <= len(digits) <= 11:
            raise ValueError("INVALID_PHONE")
        return value

class OrderInput(StrictModel):
    marketplace: Literal["coupang", "temu", "aliexpress"]
    external_id: Identifier
    external_line_id: Identifier = "1"
    listing_id: str = Field(min_length=1, max_length=36)
    quantity: Annotated[StrictInt, Field(ge=1, le=1000)]
    gross_sale: PositiveMoney
    discount: Money = 0
    address: dict

    @model_validator(mode="after")
    def amounts(self):
        if self.discount >= self.gross_sale:
            raise ValueError("NONPOSITIVE_NET_REVENUE")
        return self

class PriceRow(StrictModel):
    supplier_sku: Identifier
    title: str = Field(min_length=1, max_length=200)
    cost: Money
    shipping: Money
    stock: Annotated[StrictInt, Field(ge=0, le=1000000)] | None
    category: str = Field(min_length=1, max_length=100)
    origin: str = Field(min_length=1, max_length=100)
    tax_type: Literal["TAXABLE", "EXEMPT", "UNKNOWN"]
    weight_grams: Annotated[StrictInt, Field(gt=0, le=1000000)]
    grade: str = Field(min_length=1, max_length=80)
    unit: str = Field(min_length=1, max_length=40)

class ShipmentRow(StrictModel):
    supplier_order_id: Identifier
    marketplace_order_id: Identifier
    courier: str = Field(min_length=1, max_length=60)
    tracking: str = Field(min_length=5, max_length=100)

    @field_validator("tracking")
    @classmethod
    def tracking_safe(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9-]+", value):
            raise ValueError("INVALID_TRACKING")
        return value
