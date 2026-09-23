from dataclasses import dataclass
from decimal import Decimal
from .errors import DomainError


def score(values: dict[str, int], weights: dict[str, int]) -> Decimal:
    if set(values) != set(weights) or not weights or sum(weights.values()) <= 0:
        raise DomainError("INCOMPLETE_MARKET_INPUT", 422)
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100 for v in values.values()):
        raise DomainError("INVALID_MARKET_SIGNAL", 422)
    if any(w < 0 for w in weights.values()):
        raise DomainError("INVALID_WEIGHT", 422)
    return sum(Decimal(values[k]) * weights[k] for k in values) / sum(weights.values())


@dataclass(frozen=True)
class DiscoveryResult:
    demand: Decimal
    competition: Decimal
    action: str
    reason: str


def evaluate(demand: dict, competition: dict, expected_margin: Decimal,
             source: str, sample_size: int, min_margin=Decimal("0.15")) -> DiscoveryResult:
    d = score(demand, {"purchases": 3, "review_velocity": 2, "search_interest": 2, "seasonality": 1})
    c = score(competition, {"review_barrier": 2, "seller_concentration": 2, "price_pressure": 3, "sameness": 1})
    if not source or sample_size <= 0:
        return DiscoveryResult(d, c, "WATCH", "INSUFFICIENT_EVIDENCE")
    if expected_margin < min_margin:
        return DiscoveryResult(d, c, "DROP", "NEGATIVE_ECONOMICS")
    if d >= 70 and c <= 40 and sample_size >= 30:
        return DiscoveryResult(d, c, "ENTER", "CONTROLLED_ENTRY_ONLY")
    if d >= 45 and c < 75:
        return DiscoveryResult(d, c, "TEST", "RUN_SMALL_PROBE")
    return DiscoveryResult(d, c, "WATCH", "WEAK_DEMAND_OR_HIGH_COMPETITION")


def experiment_state(impressions: int, orders: int, contribution: int, claims: int) -> str:
    if min(impressions, orders, claims) < 0 or claims > orders or orders > impressions:
        raise DomainError("INVALID_EXPERIMENT_METRICS", 422)
    if orders >= 10 and Decimal(claims) / orders > Decimal("0.15"):
        return "PAUSE"
    if orders >= 10 and contribution <= 0:
        return "REWORK"
    if orders >= 30 and contribution > 0 and Decimal(claims) / orders <= Decimal("0.03"):
        return "SCALE"
    return "PROBE"
