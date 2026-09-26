"""Isolated Compose acceptance fixture and read-only verification. Never an API.

Requires an explicit test flag, a uniquely named test Compose project, the demo
mode and the demo database. Seed refuses existing orders/non-demo suppliers.
Credentials enter over stdin; neither credentials nor customer PII are returned.
"""
import argparse
import json
import os
import sys
from sqlalchemy import select, func, text
from sqlalchemy.engine import make_url
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.infrastructure.models import (
    User, Supplier, SupplierExcelProfile, MarketplaceListing, Order, SupplierOrder,
    Payment, SupplierPaymentEvidence, SupplierPaymentConfirmation, Shipment, Job,
    Reservation, AuditEvent, Journal, Posting, Account, ImportBatch,
)
from packages.infrastructure.security import hash_password
from packages.application.common import lock_treasury, audit


def guard(settings):
    url = make_url(settings.database_url)
    if (os.environ.get('SAUP_ACCEPTANCE') != '1'
            or not os.environ.get('COMPOSE_PROJECT_NAME', '').startswith('saup-acceptance-')
            or settings.app_mode != 'demo' or settings.real_payments_enabled
            or url.drivername != 'postgresql+psycopg' or url.host != 'db' or url.database != 'saup'):
        raise RuntimeError('ACCEPTANCE_FIXTURE_REQUIRES_ISOLATED_DEMO_COMPOSE')


def seed_fixture(factory, payload):
    if set(payload) != {'operator_password', 'viewer_password'}:
        raise RuntimeError('ACCEPTANCE_CREDENTIAL_KEYS_REQUIRED')
    if any(not isinstance(v, str) or len(v) < 20 for v in payload.values()):
        raise RuntimeError('ACCEPTANCE_RANDOM_CREDENTIALS_REQUIRED')
    with factory.begin() as s:
        lock_treasury(s)
        if s.scalar(select(func.count()).select_from(Order)):
            raise RuntimeError('ACCEPTANCE_SEED_REFUSES_EXISTING_ORDERS')
        suppliers = list(s.scalars(select(Supplier)))
        if len(suppliers) != 1 or suppliers[0].name != 'DEMO 합성 농산물 공급사' or suppliers[0].mode != 'demo':
            raise RuntimeError('ACCEPTANCE_SEED_REFUSES_NON_PRISTINE_SUPPLIERS')
        if any(not row.username.startswith('e2e-') and row.role != 'admin' for row in s.scalars(select(User))):
            raise RuntimeError('ACCEPTANCE_SEED_REFUSES_NON_DEMO_USERS')
        supplier = suppliers[0]
        supplier.mode = 'excel'
        for role in ('operator', 'viewer'):
            username = f'e2e-{role}'
            if s.scalar(select(User).where(User.username == username)):
                raise RuntimeError('ACCEPTANCE_SEED_IS_ONE_SHOT')
            s.add(User(username=username, password_hash=hash_password(payload[f'{role}_password']), role=role, active=True))
        profile = s.scalar(select(SupplierExcelProfile).where(SupplierExcelProfile.supplier_id == supplier.id))
        audit(s, 'ACCEPTANCE_FIXTURE_CREATED', supplier.id, actor='acceptance-fixture', new={'synthetic_only': True})
        return {'synthetic_only': True, 'supplier_id': supplier.id, 'profile_id': profile.id,
                'profile_version': profile.version, 'listing_ids': list(s.scalars(select(MarketplaceListing.id)))}


def snapshot(factory):
    with factory() as s:
        result = {'synthetic_only': True, 'schema_revision': s.scalar(text('SELECT version_num FROM alembic_version')),
                  'accounts': {a.code: a.balance for a in s.scalars(select(Account))}, 'orders': {}, 'counts': {}}
        for cls in (Order, SupplierOrder, Payment, SupplierPaymentEvidence, SupplierPaymentConfirmation, Shipment, ImportBatch):
            result['counts'][cls.__table__.name] = s.scalar(select(func.count()).select_from(cls))
        for order in s.scalars(select(Order).order_by(Order.id)):
            so = s.scalar(select(SupplierOrder).where(SupplierOrder.order_id == order.id))
            p = s.scalar(select(Payment).where(Payment.order_id == order.id))
            shipment = s.scalar(select(Shipment).where(Shipment.order_id == order.id))
            reservation = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
            jobs = [j for j in s.scalars(select(Job).where(Job.kind == 'marketplace.shipment'))
                    if shipment and j.payload.get('shipment_id') == shipment.id]
            evidence = s.scalar(select(SupplierPaymentEvidence).where(SupplierPaymentEvidence.payment_id == p.id)) if p else None
            confirmation = s.scalar(select(SupplierPaymentConfirmation).where(SupplierPaymentConfirmation.payment_id == p.id)) if p else None
            result['orders'][order.id] = {
                'state': order.state, 'supplier_state': so.status if so else None,
                'payment_id': p.id if p else None, 'payment_status': p.status if p else None,
                'amount': p.amount if p else None, 'evidence_id': evidence.id if evidence else None,
                'confirmation_id': confirmation.id if confirmation else None,
                'shipment_id': shipment.id if shipment else None,
                'marketplace_synced': shipment.marketplace_synced if shipment else False,
                'shipment_jobs': len(jobs), 'shipment_job_statuses': [j.status for j in jobs],
                'reservation_status': reservation.status if reservation else None,
                'human_interventions': order.human_interventions,
            }
        unbalanced = s.execute(select(Posting.journal_id).group_by(Posting.journal_id).having(func.sum(Posting.delta) != 0)).all()
        result['balanced_journals'] = not unbalanced
        result['journal_count'] = s.scalar(select(func.count()).select_from(Journal))
        result['audit_counts'] = dict(s.execute(select(AuditEvent.event, func.count()).group_by(AuditEvent.event)).all())
        return result


def verify_completed(result):
    if result['schema_revision'] != '0002' or not result['balanced_journals']:
        raise RuntimeError('ACCEPTANCE_SCHEMA_OR_LEDGER_INVARIANT_FAILED')
    shipped = [o for o in result['orders'].values() if o['supplier_state'] == 'SHIPPED']
    if not shipped:
        raise RuntimeError('ACCEPTANCE_NO_COMPLETED_SUPPLIER_TRANSACTION')
    for order in shipped:
        if not (order['payment_status'] == 'SUCCEEDED' and order['marketplace_synced']
                and order['shipment_jobs'] == 1 and order['shipment_job_statuses'] == ['DONE']):
            raise RuntimeError('ACCEPTANCE_COMPLETED_EFFECTS_INCONSISTENT')
    for order in result['orders'].values():
        if order['supplier_state'] in {'REJECTED', 'MANUAL_REVIEW'} and order['payment_id']:
            raise RuntimeError('ACCEPTANCE_BLOCKED_LINE_CREATED_PAYMENT')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('operation', choices=['seed', 'snapshot', 'verify'])
    args = parser.parse_args(); settings = Settings(); guard(settings)
    engine, factory = database(settings.database_url)
    try:
        result = seed_fixture(factory, json.load(sys.stdin)) if args.operation == 'seed' else snapshot(factory)
        if args.operation == 'verify': verify_completed(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == '__main__': main()
