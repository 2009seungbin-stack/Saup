from decimal import Decimal
from sqlalchemy import select, func
from packages.domain.errors import DomainError
from packages.domain.pricing import margin, required_price
from packages.domain.schemas import PriceRow
from packages.infrastructure.models import Product, ProductVariant, SupplierProduct, SupplierPriceHistory, MarketplaceListing, Supplier, Order, Reservation
from packages.infrastructure.schema_v1 import now
from packages.infrastructure.db import aware
from .common import audit, enqueue, review


def pause_listing(s, listing, reason: str):
    previous = listing.desired_state
    listing.desired_state = "PAUSED"
    listing.remote_state = "UNCONFIRMED"
    listing.sync_revision += 1
    enqueue(s, "listing.sync", f"listing:{listing.id}:{listing.sync_revision}",
            {"listing_id": listing.id, "revision": listing.sync_revision, "desired_state": "PAUSED", "price": listing.price})
    audit(s, "LISTING_PAUSED", listing.id, old={"state": previous}, new={"desired_state":"PAUSED", "remote_confirmed":False}, reason=reason)


def apply_price(s, settings, supplier_id: str, raw: dict, source_hash: str, sku_map=None):
    data = PriceRow.model_validate(raw)
    supplier = s.get(Supplier, supplier_id)
    if not supplier:
        raise DomainError("SUPPLIER_NOT_FOUND", 404)
    sp = s.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id, SupplierProduct.supplier_sku == data.supplier_sku))
    if sp:
        product = s.get(Product, sp.product_id)
        old = sp.cost
        # Preserve internal identity and flag significant supplier metadata changes.
        critical = any(getattr(product, k) != getattr(data, k) for k in ("origin", "tax_type", "grade", "weight_grams"))
    else:
        internal_sku = (sku_map or {}).get(data.supplier_sku, f"{supplier_id[:8]}:{data.supplier_sku}")
        product = s.scalar(select(Product).where(Product.sku == internal_sku))
        if product:
            raise DomainError("SKU_MAPPING_CONFLICT")
        product = Product(sku=internal_sku, **data.model_dump(include={"title", "category", "origin", "tax_type", "weight_grams", "grade", "unit"}))
        s.add(product); s.flush()
        s.add(ProductVariant(product_id=product.id, sku=internal_sku, attributes={"unit": data.unit, "weight_grams": data.weight_grams}))
        sp = SupplierProduct(supplier_id=supplier_id, product_id=product.id, supplier_sku=data.supplier_sku,
            cost=data.cost, shipping=data.shipping, stock=data.stock, stock_status="UNKNOWN")
        s.add(sp); s.flush()
        old, critical = None, False
    if old is None or old != data.cost:
        s.add(SupplierPriceHistory(supplier_product_id=sp.id, old_cost=old, new_cost=data.cost, source_hash=source_hash))
        audit(s, "PRODUCT_PRICE_CHANGED", sp.id, old={"cost":old}, new={"cost":data.cost}, reason="SUPPLIER_FILE")
    sp.cost, sp.shipping = data.cost, data.shipping
    # Conservative subtraction of unresolved supplier commitments from refreshed stock.
    committed = s.scalar(select(func.coalesce(func.sum(Order.quantity),0)).join(MarketplaceListing,Order.listing_id==MarketplaceListing.id)
        .join(Reservation,Reservation.order_id==Order.id).where(MarketplaceListing.supplier_product_id==sp.id,
        Reservation.status.in_(["HELD","SPENT"]), Order.state.notin_(["SHIPPED","DELIVERED","SETTLEMENT_PENDING","SETTLED","CLOSED","CANCELLED"])))
    sp.stock = None if data.stock is None else max(0, data.stock - committed)
    sp.stock_status = "UNKNOWN" if sp.stock is None else "OUT_OF_STOCK" if sp.stock == 0 else "LOW" if sp.stock <= 5 else "AVAILABLE"
    sp.last_inventory_at = now()
    if not critical:
        for key in ("title", "category", "origin", "tax_type", "weight_grams", "grade", "unit"):
            setattr(product,key,getattr(data,key))
    else:
        review(s, "PRODUCT_METADATA_REVERIFY", product.id)
    spike = old is not None and data.cost > old and (old == 0 or Decimal(data.cost-old)/old >= settings.price_spike)
    for listing in s.scalars(select(MarketplaceListing).where(MarketplaceListing.supplier_product_id==sp.id)):
        m=margin(listing.price, sp.cost+sp.shipping, listing.fee_rate, listing.claim_allowance, listing.promotion_cost)
        reason = "PRODUCT_METADATA_REVERIFY" if critical else "PRICE_SPIKE" if spike else "MARGIN_BELOW_THRESHOLD" if m.percentage < settings.min_margin else "OUT_OF_STOCK" if not sp.stock else None
        if reason:
            pause_listing(s,listing,reason)
            review(s,reason,listing.id,{"required_price":required_price(sp.cost+sp.shipping,listing.fee_rate,settings.min_margin,listing.claim_allowance,listing.promotion_cost)})
    s.flush()
    return sp


def create_listing(s, settings, sp, marketplace: str, fee_rate: Decimal, demo=False):
    if marketplace not in {"coupang","temu","aliexpress"}:
        raise DomainError("UNKNOWN_MARKETPLACE",422)
    existing=s.scalar(select(MarketplaceListing).where(MarketplaceListing.supplier_product_id==sp.id,MarketplaceListing.marketplace==marketplace))
    if existing: return existing
    product=s.get(Product,sp.product_id)
    price=required_price(sp.cost+sp.shipping,fee_rate,settings.min_margin)
    active=demo and sp.stock and product.tax_type != "UNKNOWN"
    listing=MarketplaceListing(supplier_product_id=sp.id,marketplace=marketplace,external_id=None,
       price=price,fee_rate=fee_rate,desired_state="ACTIVE" if active else "PAUSED",remote_state="UNKNOWN")
    s.add(listing);s.flush()
    enqueue(s,"listing.sync",f"listing:{listing.id}:0",{"listing_id":listing.id,"revision":0,"desired_state":listing.desired_state,"price":listing.price})
    return listing


def inventory_guard(s, settings, at=None):
    at=at or now(); paused=0
    for listing in s.scalars(select(MarketplaceListing).where(MarketplaceListing.desired_state=="ACTIVE")):
        sp=s.get(SupplierProduct,listing.supplier_product_id)
        product=s.get(Product,sp.product_id)
        if sp.stock is None or not sp.stock or (at-aware(sp.last_inventory_at)).total_seconds()>settings.inventory_max_age_seconds or product.season_state!="OPEN":
            pause_listing(s,listing,"INVENTORY_STALE_OR_UNAVAILABLE")
            paused+=1
    return paused
