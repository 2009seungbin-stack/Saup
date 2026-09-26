"""Guarded recovery is not a force-state mechanism."""
import importlib
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select, func, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from alembic.operations import Operations
from alembic.migration import MigrationContext
import pytest
from test_supplier_operations import (excel_env, make_order, batch, send, ack, payment, accepted_order,
    record, confirm, proof_payload, OP, ADMIN)
from packages.domain.errors import DomainError
from packages.domain.supplier_operations import validate_supplier_transition
from packages.infrastructure.models import (SupplierOrder, SupplierOrderIntent, SupplierProduct,
    Order, Payment, Reservation, Review, MarketplaceListing, SupplierPaymentEvidence,
    SupplierPaymentConfirmation, ExternalRecord, OperationalIntervention)
from packages.infrastructure import schema_v1, schema_v2
from packages.application.catalog import pause_listing
from packages.application.common import lock_treasury
from packages.application.after_sales import AfterSales


def test_terms_change_recovery_requires_admin_and_original_economics(excel_env, order_input):
    e=excel_env; so=make_order(e,order_input); b=batch(e,[so]);send(e,b)
    with e['factory']() as s: amount=s.get(SupplierOrder,so).amount
    ack(e,b,changes=[{'supplier_order_id':so,'amount':amount+1}])
    cmd={'reference':'original-terms-verified-001','original_terms_reconfirmed':True}
    with pytest.raises(DomainError):e['ops'].revalidate_original_terms(so,cmd,OP)
    first=e['ops'].revalidate_original_terms(so,cmd,ADMIN)
    assert first==e['ops'].revalidate_original_terms(so,cmd,ADMIN)
    with e['factory']() as s:
        assert s.get(SupplierOrder,so).amount==amount
        p=s.scalar(select(Payment)); assert p.amount==amount and p.status=='EVIDENCE_PENDING'
        assert s.scalar(select(Reservation)).status=='HELD'
        assert s.scalar(select(Review).where(Review.entity_id==so,Review.category=='SUPPLIER_TERMS_CHANGED')).status=='RESOLVED'
        assert s.get(MarketplaceListing,order_input['listing_id']).remote_state=='UNCONFIRMED'


def test_revalidation_cannot_bypass_other_listing_risk(excel_env, order_input):
    e=excel_env;so=make_order(e,order_input);b=batch(e,[so]);send(e,b)
    ack(e,b,rejected=[{'supplier_order_id':so,'reason':'PRICE_CHANGED'}],accepted=[])
    with e['factory'].begin() as s:
        lock_treasury(s);pause_listing(s,s.get(MarketplaceListing,order_input['listing_id']),'CLAIM_LOSS_KILL_SWITCH')
    with pytest.raises(DomainError):
        e['ops'].revalidate_original_terms(so,{'reference':'terms-restored','original_terms_reconfirmed':True},ADMIN)
    assert payment(e,so) is None


def test_revalidation_rejects_mutated_current_price(excel_env, order_input):
    e=excel_env;so=make_order(e,order_input);b=batch(e,[so]);send(e,b)
    ack(e,b,accepted=[],rejected=[{'supplier_order_id':so,'reason':'PRICE_CHANGED'}])
    with e['factory'].begin() as s:
        sp=s.get(SupplierProduct,s.get(MarketplaceListing,order_input['listing_id']).supplier_product_id);sp.cost+=100
    with pytest.raises(DomainError):
        e['ops'].revalidate_original_terms(so,{'reference':'not-original','original_terms_reconfirmed':True},ADMIN)
    assert payment(e,so) is None


def test_unknown_demo_payment_cannot_be_replaced_by_manual_evidence(excel_env,order_input):
    e=excel_env;so,b,p=accepted_order(e,order_input,path='DEMO_PROVIDER')
    e['commerce'].registry.mock_payment.fail_next['pay_supplier']='timeout_after'
    e['commerce'].execute_payment(p.id)
    assert payment(e,so).status=='UNKNOWN'
    with pytest.raises(DomainError):record(e,p)
    e['commerce'].execute_payment(p.id)
    e['commerce'].reconcile_payment(p.id)
    with e['factory']() as s:
        assert s.get(Payment,p.id).status=='SUCCEEDED'
        assert s.get(SupplierOrder,so).status=='SHIPMENT_PENDING'
        assert s.scalar(select(func.count()).select_from(ExternalRecord).where(ExternalRecord.namespace=='payment:pay_supplier'))==1
        assert not s.scalar(select(SupplierPaymentEvidence))


def test_different_evidence_conflicts_without_overwriting(excel_env,order_input):
    e=excel_env;_,_,p=accepted_order(e,order_input);proof=record(e,p)
    with pytest.raises(DomainError,match='PAYMENT_EVIDENCE_CONFLICT'):record(e,p,evidence_hash='b'*64)
    with e['factory']() as s:
        assert s.get(SupplierPaymentEvidence,proof['id']).evidence_hash=='a'*64
        assert s.get(Payment,p.id).status=='EVIDENCE_PENDING'


def test_evidence_reference_cannot_pay_two_orders(excel_env,order_input):
    e=excel_env; one=make_order(e,order_input,name='one');two=make_order(e,order_input,name='two')
    b=batch(e,[one,two]);send(e,b);ack(e,b)
    record(e,payment(e,one))
    with pytest.raises((DomainError,IntegrityError)):record(e,payment(e,two))
    with e['factory']() as s:assert s.scalar(select(func.count()).select_from(SupplierPaymentEvidence))==1


def test_cancel_rejected_line_and_superseded_batch_are_safe(excel_env,order_input):
    e=excel_env;one=make_order(e,order_input,name='one');two=make_order(e,order_input,name='two')
    b=batch(e,[one,two]);e['ops'].cancel_order(one,OP); b2=batch(e,[two],key='replacement')
    with pytest.raises(DomainError,match='BATCH_SUPERSEDED'):e['ops'].cancel_batch(b['id'],OP)
    send(e,b2);ack(e,b2,accepted=[],rejected=[{'supplier_order_id':two,'reason':'ORDER_NOT_ACCEPTED'}])
    assert e['ops'].cancel_order(two,OP)['status']=='CONFIRMED_LOCAL'
    with e['factory']() as s:assert s.get(SupplierOrder,two).status=='CANCELLED'


@pytest.mark.parametrize('current,target',[('PENDING','PAID'),('FILE_READY','ACKNOWLEDGED'),('SENT','SHIPPED'),('REJECTED','PAYMENT_PENDING'),('CANCELLED','PENDING')])
def test_supplier_illegal_transitions(current,target):
    with pytest.raises(DomainError,match='INVALID_SUPPLIER_ORDER_TRANSITION'):validate_supplier_transition(current,target)


def test_immutable_evidence_and_confirmation_orm(excel_env,order_input):
    e=excel_env;_,_,p=accepted_order(e,order_input);proof=record(e,p);result=confirm(e,p,proof)
    for cls,ident in [(SupplierPaymentEvidence,proof['id']),(SupplierPaymentConfirmation,result['id'])]:
        with pytest.raises(ValueError,match='APPEND_ONLY'):
            with e['factory'].begin() as s:s.get(cls,ident).amount+=1
    with e['factory']() as s:assert s.get(Payment,p.id).status=='SUCCEEDED'


def test_schema_v1_remains_frozen_and_empty_migration_roundtrip(tmp_path):
    from packages.infrastructure.db import database
    engine,_=database(f"sqlite:///{tmp_path/'migration.db'}")
    assert len(schema_v1.metadata.tables)==28 and len(schema_v2.metadata.tables)==36
    assert 'resolved_at' not in schema_v1.reviews.c
    with engine.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            initial=importlib.import_module('migrations.versions.0001_initial')
            phase=importlib.import_module('migrations.versions.0002_supplier_operations')
            initial.upgrade();phase.upgrade();phase.downgrade();initial.downgrade()
    engine.dispose()


def test_legacy_migration_conservative_review_and_guarded_adoption(excel_env,order_input):
    # Recreate a genuine v1 DB, create an old Excel intent without using the v2 ORM,
    # then migrate. Do not assert that historical FILE_READY means never-sent.
    e=excel_env;so=make_order(e,order_input)
    with e['factory']() as s:oid=s.get(SupplierOrder,so).order_id
    engine=e['engine']
    with engine.begin() as c:
        # Fixture used create_all, so no immutable DB triggers yet. Remove only
        # the synthetic new intent to emulate the historic v1 row.
        c.execute(text('DELETE FROM supplier_order_intents'))
        c.execute(text("UPDATE supplier_orders SET status='FILE_READY' WHERE id=:id"),{'id':so})
        for table in reversed(schema_v2.PHASE10_TABLES):table.drop(c)
        with Operations.context(MigrationContext.configure(c)):
            from alembic import op
            for column in ('resolution_code','resolved_by','resolved_at'):op.drop_column('reviews',column)
            importlib.import_module('migrations.versions.0002_supplier_operations').upgrade()
    with e['factory']() as s:
        assert s.get(SupplierOrder,so).status=='MANUAL_REVIEW'
        assert s.scalar(select(Reservation)).status=='HELD'
        assert not s.scalar(select(SupplierOrderIntent))
    cmd={'reference':'supplier-never-received-verified','verified_never_sent':True}
    with pytest.raises(DomainError):e['ops'].adopt_verified_unsent_legacy(so,cmd,OP)
    result=e['ops'].adopt_verified_unsent_legacy(so,cmd,ADMIN)
    assert result==e['ops'].adopt_verified_unsent_legacy(so,cmd,ADMIN)
    assert result['status']=='PENDING'
    b=batch(e,[so]);assert b['status']=='FILE_READY'
    with pytest.raises(RuntimeError,match='PHASE10_DATA_PRESENT_DOWNGRADE_BLOCKED'):
        with engine.begin() as c:
            with Operations.context(MigrationContext.configure(c)):
                importlib.import_module('migrations.versions.0002_supplier_operations').downgrade()
    with pytest.raises(DatabaseError,match='APPEND_ONLY'):
        with engine.begin() as c:c.execute(text('UPDATE supplier_order_intents SET amount=amount+1'))


def test_manual_after_sales_categories_recorded_once(env,order_input):
    from test_workflows import delivered
    oid=delivered(env,order_input);after=AfterSales(env['commerce'])
    with env['factory']() as s:o=s.get(Order,oid);expected=o.gross_sale-o.discount-o.fee-o.promotion_cost
    sid=after.reconcile_settlement(oid,'manual-statement',expected,actor='operator')
    after.reconcile_settlement(oid,'manual-statement',expected,actor='operator')
    after.confirm_settlement_cash(sid,'bank-evidence-ref',actor='admin')
    after.confirm_settlement_cash(sid,'bank-evidence-ref',actor='admin')
    with env['factory']() as s:
        kinds=list(s.scalars(select(OperationalIntervention.category).where(OperationalIntervention.order_id==oid)))
        assert kinds.count('SETTLEMENT_RECONCILED_MANUALLY')==1
        assert kinds.count('SETTLEMENT_CASH_CONFIRMED_MANUALLY')==1
