from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from .errors import DomainError

D = Decimal
MAX_KRW = 10**12


def krw(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_KRW:
        raise DomainError("INVALID_KRW", 422)
    return value


def rate(value) -> Decimal:
    value = D(str(value))
    if not value.is_finite() or not D(0) <= value < D(1):
        raise DomainError("INVALID_RATE", 422)
    return value


def fee_for(revenue: int, fee_rate: Decimal) -> int:
    return int((D(krw(revenue)) * rate(fee_rate)).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class Margin:
    revenue: int
    supplier_total: int
    fee: int
    expected_claim: int
    promotion: int
    contribution: int
    percentage: Decimal


def margin(revenue: int, supplier_total: int, fee_rate: Decimal,
           claim_cost: int = 0, promotion_cost: int = 0) -> Margin:
    for value in (revenue, supplier_total, claim_cost, promotion_cost):
        krw(value)
    if not revenue:
        raise DomainError("ZERO_REVENUE", 422)
    fee = fee_for(revenue, fee_rate)
    profit = revenue - supplier_total - fee - claim_cost - promotion_cost
    return Margin(revenue, supplier_total, fee, claim_cost, promotion_cost,
                  profit, D(profit) / D(revenue))


def required_price(supplier_total: int, fee_rate: Decimal, target_margin: Decimal,
                   claim_cost: int = 0, promotion_cost: int = 0, step: int = 100) -> int:
    for value in (supplier_total, claim_cost, promotion_cost):
        krw(value)
    if not isinstance(step, int) or isinstance(step, bool) or step <= 0:
        raise DomainError("INVALID_PRICE_STEP", 422)
    fee_rate, target_margin = rate(fee_rate), rate(target_margin)
    denominator = D(1) - fee_rate - target_margin
    if denominator <= 0:
        raise DomainError("IMPOSSIBLE_MARGIN", 422)
    total = supplier_total + claim_cost + promotion_cost
    price = max(step, int((D(total) / denominator / step).to_integral_value(rounding=ROUND_CEILING)) * step)
    # Verify again after KRW fee rounding.
    while margin(price, supplier_total, fee_rate, claim_cost, promotion_cost).percentage < target_margin:
        price += step
    return krw(price)
