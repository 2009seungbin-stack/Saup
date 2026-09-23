"""Rolling-window rules. Small samples are not advertised as reliable quality scores."""
from decimal import Decimal
from datetime import timedelta
from sqlalchemy import select
from packages.infrastructure.models import SupplierProduct, MarketplaceListing, Order, Claim
from .common import review, audit
from .finance import capacity
from .catalog import pause_listing


def guard_cash_and_claims(s, commerce):
    settings=commerce.settings;since=commerce.clock()-timedelta(days=settings.claim_window_days)
    paused=0
    for sp in s.scalars(select(SupplierProduct)):
        listings=list(s.scalars(select(MarketplaceListing).where(MarketplaceListing.supplier_product_id==sp.id)))
        active=[row for row in listings if row.desired_state=='ACTIVE']
        if not active:continue
        reason=None
        if capacity(s,settings,sp.supplier_id,sp.cost+sp.shipping)<1:reason='CASH_CAPACITY_EXHAUSTED'
        ids=[x.id for x in listings]
        cohort=list(s.scalars(select(Order).where(Order.listing_id.in_(ids),Order.delivered_at>=since)))
        if len(cohort)>=settings.claim_min_samples:
            claims=list(s.scalars(select(Claim).where(Claim.order_id.in_([o.id for o in cohort]))))
            rate=Decimal(len({cl.order_id for cl in claims}))/len(cohort)
            losses=sum(max(0,cl.customer_refund-cl.supplier_recovery) for cl in claims)
            revenue=sum(o.gross_sale-o.discount for o in cohort)
            loss_rate=Decimal(losses)/revenue if revenue else Decimal(0)
            stats={'sample_size':len(cohort),'window_days':settings.claim_window_days,'claim_rate':str(rate),
                   'seller_loss_rate':str(loss_rate),'method':'delivered-order cohort; confirmed recovery only'}
            if rate>=settings.claim_warning_rate:review(s,'CLAIM_RATE_WARNING',sp.id,stats)
            if rate>=settings.claim_pause_rate or loss_rate>=settings.seller_loss_pause_rate:
                reason='CLAIM_LOSS_KILL_SWITCH';review(s,reason,sp.id,stats)
        if reason:
            for listing in active:pause_listing(s,listing,reason);paused+=1
    return paused
