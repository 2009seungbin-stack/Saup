"""Operator-complete local setup and truthful external handoffs; no provider calls."""
from sqlalchemy import select, func, or_
from packages.domain import operations as inputs
from packages.domain.errors import DomainError
from packages.domain.pricing import required_price, margin
from packages.infrastructure.models import (User, Supplier, SupplierProduct, Product, MarketplaceListing,
    SupplierExcelProfile, OperationalReceipt, Order, Shipment, Claim, Refund, Settlement, SettlementRevision,
    Journal, Posting, Account, Review, Payment, SupplierCancellationRecovery, SupplierPaymentEvidence,
    MarketplaceRefundEvidence, SupplierEvidenceRevision, MarketplaceCancellationStatement, CancellationStatementRevision)
from packages.infrastructure.security import hash_password, fingerprint
from packages.infrastructure.db import aware
from .common import lock_treasury, execute_command, audit, review
from .finance import post, balance, treasury
from .supplier_operations import intervention, resolve_reviews
from .after_sales import AfterSales


def get(s, model, identifier):
    row = s.get(model, identifier)
    if row is None:
        raise DomainError(model.__name__.upper() + '_NOT_FOUND', 404)
    return row


def safe(row, fields):
    return {key: getattr(row, key) for key in fields.split()}


def unused_evidence(s, namespace, reference, evidence_hash):
    if s.scalar(select(OperationalReceipt.id).where(or_(OperationalReceipt.evidence_hash == evidence_hash,
            (OperationalReceipt.namespace == namespace) & (OperationalReceipt.reference == reference)))):
        raise DomainError('EXTERNAL_EVIDENCE_ALREADY_USED')
    for cls in (SupplierCancellationRecovery, SupplierPaymentEvidence, SupplierEvidenceRevision,
                MarketplaceRefundEvidence, MarketplaceCancellationStatement, SettlementRevision, CancellationStatementRevision):
        if s.scalar(select(cls.id).where(cls.evidence_hash == evidence_hash)):
            raise DomainError('EXTERNAL_EVIDENCE_ALREADY_USED')


class Operations:
    def __init__(self, commerce):
        self.c, self.factory = commerce, commerce.factory
        self.after = AfterSales(commerce)

    def receipt(self, s, kind, target, namespace, cmd, actor, effect):
        """Treasury-locked, payload-bound replay plus immutable external evidence."""
        payload = cmd.model_dump(mode='json')
        hashed = fingerprint(payload)
        old = s.scalar(select(OperationalReceipt).where(OperationalReceipt.kind == kind, OperationalReceipt.target_id == target))
        if old:
            if old.payload_hash != hashed: raise DomainError('CONFIRMATION_CONFLICT')
            return {'receipt_id': old.id, 'target_id': target, 'kind': kind}
        unused_evidence(s, namespace, cmd.reference, cmd.evidence_hash)
        effect()
        row = OperationalReceipt(kind=kind, target_id=target, namespace=namespace, reference=cmd.reference,
            evidence_hash=cmd.evidence_hash, payload_hash=hashed, payload=payload, actor=actor.username)
        s.add(row); s.flush()
        order = s.get(Order, target)
        audit(s, kind, target, actor=actor.username, new={'receipt_id': row.id, 'evidence_hash': cmd.evidence_hash},
              correlation_id=order.correlation_id if order else None)
        intervention(s, kind, f'{kind}:{target}', actor.username, self.c.clock(), order=order)
        return {'receipt_id': row.id, 'target_id': target, 'kind': kind}

    def create_user(self, raw, actor):
        actor.require('admin'); cmd = inputs.UserInput.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s)
            if s.scalar(select(User.id).where(User.username == cmd.username)): raise DomainError('USERNAME_EXISTS')
            row = User(username=cmd.username, role=cmd.role, password_hash=hash_password(cmd.password.get_secret_value()))
            s.add(row); s.flush()
            audit(s, 'LOCAL_USER_CREATED', row.id, actor=actor.username, new={'role': row.role})
            return safe(row, 'id username role active')

    def supplier(self, raw, actor, supplier_id=None):
        actor.require('admin'); cmd = inputs.SupplierInput.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s)
            row = get(s, Supplier, supplier_id) if supplier_id else s.scalar(select(Supplier).where(Supplier.name == cmd.name))
            if row and not supplier_id:
                if safe(row, 'name mode cutoff claim_days active') != cmd.model_dump(): raise DomainError('SUPPLIER_EXISTS')
                return {'id': row.id}
            if row and row.mode != 'excel': raise DomainError('EXCEL_SUPPLIER_REQUIRED')
            old = safe(row, 'name mode cutoff claim_days active') if row else {}
            if row is None:
                row = Supplier(**cmd.model_dump(), destination_approved=False); s.add(row)
            else:
                for key, value in cmd.model_dump().items(): setattr(row, key, value)
            s.flush()
            audit(s, 'SUPPLIER_UPDATED' if supplier_id else 'SUPPLIER_CREATED', row.id,
                  actor=actor.username, old=old, new=cmd.model_dump())
            return {'id': row.id}

    def create_listing(self, raw, actor):
        actor.require(); cmd = inputs.ListingInput.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); sp = get(s, SupplierProduct, cmd.supplier_product_id)
            if get(s, Supplier, sp.supplier_id).mode != 'excel': raise DomainError('EXCEL_SUPPLIER_REQUIRED')
            old = s.scalar(select(MarketplaceListing).where(MarketplaceListing.supplier_product_id == sp.id,
                MarketplaceListing.marketplace == cmd.marketplace))
            if old:
                if old.fee_rate != cmd.fee_rate: raise DomainError('LISTING_EXISTS_WITH_DIFFERENT_FEE')
                return {'id': old.id}
            # Local configuration is not a remotely created listing; no sync job.
            row = MarketplaceListing(supplier_product_id=sp.id, marketplace=cmd.marketplace, fee_rate=cmd.fee_rate,
                price=required_price(sp.cost+sp.shipping, cmd.fee_rate, self.c.settings.min_margin),
                desired_state='PAUSED', remote_state='UNKNOWN')
            s.add(row); s.flush()
            audit(s, 'LOCAL_LISTING_CREATED', row.id, actor=actor.username, new={'fee_rate': str(cmd.fee_rate)})
            return {'id': row.id}

    def activate_listing(self, listing_id, raw, actor):
        actor.require(); cmd = inputs.ListingActivation.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); listing = get(s, MarketplaceListing, listing_id)
            def effect():
                sp = get(s, SupplierProduct, listing.supplier_product_id); product = get(s, Product, sp.product_id)
                supplier = get(s, Supplier, sp.supplier_id)
                if not supplier.active or not supplier.destination_approved: raise DomainError('SUPPLIER_DESTINATION_APPROVAL_REQUIRED')
                if not sp.stock or (self.c.clock()-aware(sp.last_inventory_at)).total_seconds() > self.c.settings.inventory_max_age_seconds:
                    raise DomainError('INVENTORY_STALE_OR_UNAVAILABLE')
                if product.tax_type == 'UNKNOWN' or product.season_state != 'OPEN': raise DomainError('PRODUCT_NOT_SELLABLE')
                if margin(cmd.price, sp.cost+sp.shipping, listing.fee_rate, listing.claim_allowance,
                          listing.promotion_cost).percentage < self.c.settings.min_margin: raise DomainError('MARGIN_BELOW_THRESHOLD')
                if treasury(s, self.c.settings, supplier.id)['available_cash'] < sp.cost+sp.shipping: raise DomainError('INSUFFICIENT_CASH')
                if s.scalar(select(Review.id).where(Review.entity_id.in_([listing.id, product.id]), Review.status != 'RESOLVED')):
                    raise DomainError('UNRESOLVED_LISTING_RISK')
                listing.price, listing.external_id = cmd.price, cmd.external_id
                listing.desired_state, listing.remote_state = 'ACTIVE', 'MANUALLY_CONFIRMED'
                listing.sync_revision += 1; listing.last_synced_at = self.c.clock()
            return self.receipt(s, 'LISTING_EXTERNALLY_CONFIRMED', f'{listing.id}:{fingerprint(cmd.reference)}', f'listing:{listing.marketplace}', cmd, actor, effect)

    def funds(self, raw, actor, supplier_id=None):
        actor.require('admin'); cmd = inputs.FundsInput.model_validate(raw)
        kind, target = ('SUPPLIER_DEPOSIT_CONFIRMED', supplier_id+':'+fingerprint(cmd.reference)) if supplier_id else ('OPENING_BANK_CONFIRMED', 'BANK')
        with self.factory.begin() as s:
            lock_treasury(s)
            def effect():
                if supplier_id:
                    get(s, Supplier, supplier_id)
                    if treasury(s, self.c.settings)['free_bank'] < cmd.amount: raise DomainError('INSUFFICIENT_UNCOMMITTED_BANK')
                    entries = {f'DEPOSIT:{supplier_id}': cmd.amount, 'BANK': -cmd.amount}
                else:
                    if balance(s, 'BANK') or s.scalar(select(Journal.id).limit(1)): raise DomainError('OPENING_REQUIRES_EMPTY_LEDGER')
                    entries = {'BANK': cmd.amount, 'EQUITY': -cmd.amount}
                post(s, f'{kind}:{target}', kind, entries)
            return self.receipt(s, kind, target, 'bank-evidence', cmd, actor, effect)

    def confirm_shipment(self, shipment_id, raw, actor):
        actor.require(); cmd = inputs.ShipmentConfirmation.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); shipment = get(s, Shipment, shipment_id); order = get(s, Order, shipment.order_id)
            def effect():
                if (cmd.marketplace, cmd.external_order_id, cmd.external_line_id, cmd.tracking_hash) != (
                    order.marketplace, order.external_id, order.external_line_id, fingerprint([shipment.courier, shipment.tracking])):
                    raise DomainError('SHIPMENT_IDENTITY_MISMATCH')
                if order.cancel_requested or order.state != 'SHIPPED': raise DomainError('ORDER_NOT_SHIPPED')
                # marketplace_synced remains a provider-only flag.
            return self.receipt(s, 'SHIPMENT_EXTERNALLY_CONFIRMED', shipment.id, f'shipment:{order.marketplace}', cmd, actor, effect)

    def delivered(self, order_id, raw, actor):
        actor.require(); cmd = inputs.Evidence.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); order = get(s, Order, order_id)
            def effect():
                shipment = s.scalar(select(Shipment).where(Shipment.order_id == order.id))
                manual = shipment and s.scalar(select(OperationalReceipt.id).where(OperationalReceipt.kind == 'SHIPMENT_EXTERNALLY_CONFIRMED', OperationalReceipt.target_id == shipment.id))
                if not shipment or not manual: raise DomainError('EXTERNAL_SHIPMENT_CONFIRMATION_REQUIRED')
                if order.cancel_requested: raise DomainError('CANCEL_REQUESTED')
                self.c.delivered(order.id, session=s)
            return self.receipt(s, 'DELIVERY_CONFIRMED', order.id, f'delivery:{order.marketplace}', cmd, actor, effect)

    def claim(self, order_id, raw, actor):
        actor.require(); cmd = inputs.ClaimInput.model_validate(raw)
        return {'claim_id': self.after.open_claim(order_id, cmd.external_id, cmd.category, cmd.amount,
            cmd.evidence, actor=actor.username, operational=True)}

    def response(self, claim_id, raw, actor):
        actor.require(); cmd = inputs.ClaimResponse.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); get(s, Claim, claim_id)
            return self.receipt(s, 'SUPPLIER_CLAIM_RESPONSE', claim_id, 'claim-response', cmd, actor,
                lambda: self.after.supplier_response(claim_id, cmd.amount, cmd.accepted, actor.username, operational=True, session=s))

    def recovery(self, claim_id, raw, actor):
        actor.require('admin'); cmd = inputs.FundsInput.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); claim = get(s, Claim, claim_id)
            from .order_rules import context
            supplier = context(s, get(s, Order, claim.order_id))[2]
            def effect():
                if claim.supplier_recovery: raise DomainError('RECOVERY_ALREADY_RECORDED')
                if s.scalar(select(Journal.id).where(Journal.business_key == f'supplier-recovery:{supplier.id}:{cmd.reference}')):
                    raise DomainError('RECOVERY_RECEIPT_IN_USE')
                # Same supplier receipt cannot also be a paid-cancellation recovery.
                if s.scalar(select(SupplierCancellationRecovery.id).where(SupplierCancellationRecovery.supplier_id == supplier.id,
                        SupplierCancellationRecovery.reference == cmd.reference)): raise DomainError('RECOVERY_RECEIPT_IN_USE')
                self.after.confirm_supplier_recovery(claim.id, cmd.amount, cmd.reference, actor.username, session=s)
            return self.receipt(s, 'CLAIM_RECOVERY_CONFIRMED', claim.id, f'supplier-recovery:{supplier.id}', cmd, actor, effect)

    def request_refund(self, claim_id, raw, actor):
        actor.require('admin'); cmd = inputs.RefundRequest.model_validate(raw)
        return {'refund_id': self.after.request_refund(claim_id, cmd.amount, cmd.key, actor.username, operational=True)}

    def confirm_refund(self, refund_id, raw, actor):
        actor.require('admin'); cmd = inputs.RefundConfirmation.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); refund = get(s, Refund, refund_id); claim = get(s, Claim, refund.claim_id); order = get(s, Order, refund.order_id)
            def effect():
                if (cmd.order_id, cmd.claim_id, cmd.amount, cmd.marketplace) != (order.id, claim.id, refund.amount, order.marketplace) or claim.order_id != order.id:
                    raise DomainError('REFUND_IDENTITY_MISMATCH')
                if refund.status != 'EVIDENCE_PENDING': raise DomainError('REFUND_NOT_AWAITING_MANUAL_EVIDENCE')
                if claim.status not in {'REFUND_ELIGIBLE', 'MANUAL_REVIEW', 'PARTIALLY_REFUNDED'}: raise DomainError('CLAIM_NOT_REFUNDABLE')
                if order.state != 'DELIVERED' or s.scalar(select(Settlement.id).where(Settlement.order_id == order.id)):
                    raise DomainError('POST_SETTLEMENT_REFUND_REQUIRES_MANUAL_RECONCILIATION')
                pending = ['PENDING', 'SENDING', 'UNKNOWN', 'SUCCEEDED', 'MANUAL_APPROVAL', 'EVIDENCE_PENDING']
                for criterion, ceiling in ((Refund.order_id == order.id, order.gross_sale-order.discount), (Refund.claim_id == claim.id, claim.requested_amount)):
                    total = s.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(criterion, Refund.status.in_(pending)))
                    if total > ceiling: raise DomainError('REFUND_EXCEEDS_SALE_OR_CLAIM')
                if claim.customer_refund+refund.amount > claim.requested_amount: raise DomainError('REFUND_EXCEEDS_SALE_OR_CLAIM')
                if not s.scalar(select(Journal.id).where(Journal.order_id == order.id, Journal.kind == 'SALE_RECOGNIZED')):
                    raise DomainError('SALE_ACCOUNTING_REQUIRED')
                # Full-sale refunds may require fee credits; keep those unsupported
                # negative-receivable cases blocked rather than spending other orders.
                refunded = int(s.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.order_id == order.id, Refund.status == 'SUCCEEDED')))
                if refunded+refund.amount > order.gross_sale-order.discount-order.fee-order.promotion_cost:
                    raise DomainError('REFUND_FEE_RECONCILIATION_REQUIRED')
                post(s, f'refund:{refund.id}', 'CUSTOMER_REFUND', {'REFUND_EXPENSE': refund.amount,
                    'MARKETPLACE_RECEIVABLE': -refund.amount}, order.id, order.correlation_id)
                refund.status = 'SUCCEEDED'  # provider_reference intentionally remains empty.
                claim.customer_refund += refund.amount
                claim.status = 'REFUNDED' if claim.customer_refund == claim.requested_amount else 'PARTIALLY_REFUNDED'
            return self.receipt(s, 'CUSTOMER_REFUND_CONFIRMED', refund.id, f'refund:{order.marketplace}', cmd, actor, effect)

    def settlement(self, order_id, raw, actor):
        actor.require(); cmd = inputs.SettlementInput.model_validate(raw)
        if cmd.adjustment: actor.require('admin')
        with self.factory.begin() as s:
            lock_treasury(s); order = get(s, Order, order_id)
            if s.scalar(select(Order.id).where(Order.marketplace == order.marketplace, Order.external_id == order.external_id, Order.id != order.id)):
                raise DomainError('MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED')
            def effect():
                if s.scalar(select(Claim.id).where(Claim.order_id == order.id,
                        or_(Claim.status != 'REFUNDED', Claim.supplier_recovery < Claim.supplier_accepted_amount))):
                    raise DomainError('OPEN_CLAIM_RECONCILIATION_REQUIRED')
                self.after.reconcile_settlement(order_id, cmd.external_id, cmd.actual, cmd.adjustment, tolerance=0, actor=actor.username, session=s)
            result = self.receipt(s, 'SETTLEMENT_STATEMENT_RECORDED', order.id, f'statement:{order.marketplace}', cmd, actor, effect)
            result['settlement_id'] = s.scalar(select(Settlement.id).where(Settlement.order_id == order.id))
            return result

    @staticmethod
    def revision(s, settlement_id):
        return s.scalar(select(func.coalesce(func.max(SettlementRevision.revision), 0)).where(SettlementRevision.settlement_id == settlement_id))

    def settlement_cash(self, settlement_id, raw, actor):
        actor.require('admin'); cmd = inputs.CashConfirmation.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); row = get(s, Settlement, settlement_id)
            def effect():
                if row.confirmed_cash: raise DomainError('CASH_ALREADY_CONFIRMED')
                if cmd.expected_revision != self.revision(s, row.id): raise DomainError('STALE_SETTLEMENT_REVISION')
                if cmd.amount != row.actual: raise DomainError('SETTLEMENT_RECEIPT_AMOUNT_MISMATCH')
                self.after.confirm_settlement_cash(row.id, cmd.reference, actor.username, session=s)
            return self.receipt(s, 'SETTLEMENT_CASH_CONFIRMED', row.id, 'bank-evidence', cmd, actor, effect)

    def correct_settlement(self, settlement_id, raw, actor):
        actor.require('admin'); cmd = inputs.SettlementCorrection.model_validate(raw)
        with self.factory.begin() as s:
            lock_treasury(s); row = get(s, Settlement, settlement_id); order = get(s, Order, row.order_id)
            def effect():
                if row.confirmed_cash or order.state != 'SETTLEMENT_PENDING': raise DomainError('CONFIRMED_SETTLEMENT_CORRECTION_BLOCKED')
                revision = self.revision(s, row.id)
                if cmd.expected_revision != revision: raise DomainError('STALE_SETTLEMENT_REVISION')
                unused_evidence(s, f'statement:{order.marketplace}', cmd.reference, cmd.evidence_hash)
                if s.scalar(select(Settlement.id).where(Settlement.external_id == cmd.external_id, Settlement.id != row.id)):
                    raise DomainError('SETTLEMENT_REFERENCE_IN_USE')
                if s.scalar(select(Refund.id).where(Refund.order_id == order.id, Refund.status != 'SUCCEEDED')):
                    raise DomainError('PENDING_REFUND_RECONCILIATION')
                refunded = int(s.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.order_id == order.id, Refund.status == 'SUCCEEDED')))
                expected = order.gross_sale-order.discount-order.fee-order.promotion_cost-refunded+cmd.adjustment
                if expected < 0: raise DomainError('NEGATIVE_SETTLEMENT_REQUIRES_MANUAL_RECONCILIATION')
                before = safe(row, 'external_id expected actual difference adjustment input_hash')
                # Explicit inverse + replacement postings, never edit/delete old journals.
                def journal(suffix, kind, entries):
                    if any(entries.values()): post(s, f'correction:{row.id}:{revision+1}:{suffix}', kind, entries, order.id, order.correlation_id)
                journal('reverse-statement', 'SETTLEMENT_REVERSAL', {'SETTLEMENT_CLEARING': -row.actual, 'MARKETPLACE_RECEIVABLE': row.expected, 'SETTLEMENT_VARIANCE': row.actual-row.expected})
                journal('reverse-adjustment', 'ADJUSTMENT_REVERSAL', {'MARKETPLACE_RECEIVABLE': -row.adjustment, 'SETTLEMENT_VARIANCE': row.adjustment})
                journal('adjustment', 'MARKETPLACE_ADJUSTMENT', {'MARKETPLACE_RECEIVABLE': cmd.adjustment, 'SETTLEMENT_VARIANCE': -cmd.adjustment})
                journal('statement', 'SETTLEMENT_STATEMENT', {'SETTLEMENT_CLEARING': cmd.actual, 'MARKETPLACE_RECEIVABLE': -expected, 'SETTLEMENT_VARIANCE': expected-cmd.actual})
                row.external_id, row.actual, row.adjustment, row.expected = cmd.external_id, cmd.actual, cmd.adjustment, expected
                row.difference = cmd.actual-expected; row.input_hash = fingerprint([order.id, cmd.external_id, cmd.actual, cmd.adjustment])
                record = SettlementRevision(settlement_id=row.id, revision=revision+1, before=before,
                    after=safe(row, 'external_id expected actual difference adjustment input_hash'), reason=cmd.reason,
                    reference=cmd.reference, evidence_hash=cmd.evidence_hash, actor=actor.username)
                s.add(record); s.flush()
                resolve_reviews(s, row.id, ['SETTLEMENT_ANOMALY'], actor.username, self.c.clock(), 'STATEMENT_CORRECTED')
                if row.difference: review(s, 'SETTLEMENT_ANOMALY', row.id, {'expected': expected, 'actual': cmd.actual})
                audit(s, 'SETTLEMENT_CORRECTED', row.id, actor=actor.username, old=before, new=record.after, reason=cmd.reason, correlation_id=order.correlation_id)
                intervention(s, 'SETTLEMENT_CORRECTED', f'settlement-correction:{record.id}', actor.username, self.c.clock(), order=order)
                return {'settlement_id': row.id, 'revision': revision+1}
            return execute_command(s, 'settlement.correct', f'{row.id}:{cmd.reference}', cmd.model_dump(mode='json'), effect)

    def setup_view(self):
        with self.factory() as s:
            suppliers = [safe(x, 'id name mode cutoff claim_days active destination_fingerprint destination_approved destination_proposed_by destination_approved_by') for x in s.scalars(select(Supplier))]
            products = []
            for sp in s.scalars(select(SupplierProduct)):
                products.append(safe(sp, 'id supplier_id supplier_sku cost shipping stock stock_status last_inventory_at') | {'title': get(s, Product, sp.product_id).title})
            listings = []
            for row in s.scalars(select(MarketplaceListing)):
                sp = get(s, SupplierProduct, row.supplier_product_id)
                m = margin(row.price, sp.cost+sp.shipping, row.fee_rate, row.claim_allowance, row.promotion_cost)
                listings.append(safe(row, 'id supplier_product_id marketplace price fee_rate desired_state remote_state external_id') | {
                    'required_price': required_price(sp.cost+sp.shipping, row.fee_rate, self.c.settings.min_margin, row.claim_allowance, row.promotion_cost),
                    'fee': m.fee, 'margin': str(m.percentage), 'last_inventory_at': sp.last_inventory_at})
            return {'suppliers': suppliers, 'products': products, 'listings': listings,
                'cash': treasury(s, self.c.settings), 'profiles': [safe(x, 'id name supplier_id mapping') for x in s.scalars(select(SupplierExcelProfile))]}

    def work_view(self):
        with self.factory() as s:
            shipments = []
            for row in s.scalars(select(Shipment)):
                order = get(s, Order, row.order_id)
                receipt = s.scalar(select(OperationalReceipt).where(OperationalReceipt.kind == 'SHIPMENT_EXTERNALLY_CONFIRMED', OperationalReceipt.target_id == row.id))
                shipments.append(safe(row, 'id order_id courier tracking marketplace_synced') | safe(order, 'marketplace external_line_id state') | {
                    'external_order_id': order.external_id, 'tracking_hash': fingerprint([row.courier, row.tracking]), 'manual_confirmation': receipt.id if receipt else None})
            settlements = [safe(x, 'id order_id external_id expected actual adjustment difference confirmed_cash') | {'revision': self.revision(s, x.id)} for x in s.scalars(select(Settlement))]
            return {'shipments': shipments, 'claims': [safe(x, 'id order_id external_id category status requested_amount supplier_accepted_amount supplier_recovery customer_refund') for x in s.scalars(select(Claim))],
                'refunds': [safe(x, 'id order_id claim_id amount status provider_reference') for x in s.scalars(select(Refund))], 'settlements': settlements,
                'orders': [safe(x, 'id external_id marketplace state gross_sale discount fee promotion_cost') for x in s.scalars(select(Order))],
                'receipts': [safe(x, 'id kind target_id reference evidence_hash actor created_at') for x in s.scalars(select(OperationalReceipt))],
                'settlement_history': [safe(x, 'id settlement_id revision before after reason reference evidence_hash actor created_at') for x in s.scalars(select(SettlementRevision))]}
