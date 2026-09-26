"""Acceptance setup cannot silently target production or existing business data."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from sqlalchemy import select
from packages.infrastructure.models import Supplier, User
from scripts.acceptance_fixture import guard, seed_fixture, verify_completed


def settings(**changes):
    return SimpleNamespace(**{'database_url': 'postgresql+psycopg://test:unused@db/saup',
                              'app_mode': 'demo', 'real_payments_enabled': False, **changes})


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv('SAUP_ACCEPTANCE', '1')
    monkeypatch.setenv('COMPOSE_PROJECT_NAME', 'saup-acceptance-unit')


@pytest.mark.parametrize('change', [
    {'app_mode': 'production'}, {'app_mode': 'test'}, {'real_payments_enabled': True},
    {'database_url': 'sqlite:///saup.db'},
    {'database_url': 'postgresql+psycopg://test:unused@production-db/saup'},
    {'database_url': 'postgresql+psycopg://test:unused@db/production'},
])
def test_acceptance_guard_rejects_wrong_environment(isolated, change):
    with pytest.raises(RuntimeError, match='REQUIRES_ISOLATED_DEMO_COMPOSE'):
        guard(settings(**change))


@pytest.mark.parametrize('key', ['SAUP_ACCEPTANCE', 'COMPOSE_PROJECT_NAME'])
def test_acceptance_guard_needs_both_explicit_flags(isolated, monkeypatch, key):
    monkeypatch.delenv(key)
    with pytest.raises(RuntimeError, match='REQUIRES_ISOLATED_DEMO_COMPOSE'):
        guard(settings())


def test_acceptance_guard_allows_only_declared_demo(isolated):
    guard(settings())


@pytest.mark.parametrize('payload', [{}, {'operator_password': 'x'*24},
    {'operator_password': 'weak', 'viewer_password': 'weak'}])
def test_acceptance_credentials_checked_before_database(payload):
    factory = Mock()
    with pytest.raises(RuntimeError, match='CREDENTIAL'):
        seed_fixture(factory, payload)
    factory.begin.assert_not_called()


def test_acceptance_seed_is_synthetic_and_one_shot(env):
    credentials = {'operator_password': 'x'*24, 'viewer_password': 'y'*24}
    result = seed_fixture(env['factory'], credentials)
    assert result['synthetic_only'] and result['profile_version'] == 1
    with env['factory']() as s:
        assert s.get(Supplier, result['supplier_id']).mode == 'excel'
        assert s.scalar(select(User).where(User.username == 'e2e-operator')).role == 'operator'
        assert s.scalar(select(User).where(User.username == 'e2e-viewer')).role == 'viewer'
    assert not any('password' in k for k in result)
    with pytest.raises(RuntimeError, match='REFUSES_NON_PRISTINE_SUPPLIERS'):
        seed_fixture(env['factory'], credentials)


def test_acceptance_seed_refuses_existing_orders(env, order_input):
    env['commerce'].ingest(order_input)
    with pytest.raises(RuntimeError, match='REFUSES_EXISTING_ORDERS'):
        seed_fixture(env['factory'], {'operator_password': 'x'*24, 'viewer_password': 'y'*24})


def completed():
    return {'schema_revision': '0003', 'balanced_journals': True, 'orders': {'one': {
        'supplier_state':'SHIPPED', 'payment_id':'payment-one', 'payment_status':'SUCCEEDED',
        'marketplace_synced':True, 'shipment_jobs':1, 'shipment_job_statuses':['DONE']}}}


@pytest.mark.parametrize('changes', [
    {'shipment_jobs':2}, {'payment_status':'UNKNOWN'}, {'marketplace_synced':False},
    {'shipment_job_statuses':['PENDING']}, {'supplier_state':'REJECTED'},
])
def test_acceptance_verifier_cannot_pass_incomplete_or_duplicate_effects(changes):
    result = deepcopy(completed()); result['orders']['one'].update(changes)
    with pytest.raises(RuntimeError): verify_completed(result)


def test_acceptance_verifier_requires_ledger_balance():
    result = completed(); result['balanced_journals'] = False
    with pytest.raises(RuntimeError, match='SCHEMA_OR_LEDGER'):
        verify_completed(result)


def test_acceptance_verifier_accepts_completed_synthetic_effects():
    verify_completed(completed())
