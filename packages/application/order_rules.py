"""Shared order helpers; intentionally independent of orchestration services."""
from packages.domain.state_machine import validate_transition
from packages.infrastructure.models import MarketplaceListing, SupplierProduct, Supplier, Product
from .common import audit

def transition(s, order, target, reason="RULE"):
    validate_transition(order.state, target)
    if order.state == target: return
    before = order.state
    order.state = target
    audit(s, "ORDER_TRANSITION", order.id, old={"state": before}, new={"state": target},
          reason=reason, correlation_id=order.correlation_id)


def context(s, order):
    listing = s.get(MarketplaceListing, order.listing_id)
    sp = s.get(SupplierProduct, listing.supplier_product_id)
    return listing, sp, s.get(Supplier, sp.supplier_id), s.get(Product, sp.product_id)


