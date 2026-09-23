from datetime import datetime, timezone
from cryptography.fernet import Fernet
import pytest
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.infrastructure.models import Base
from packages.application.seed import seed
from packages.application.commerce import Commerce
from apps.worker.main import Worker

@pytest.fixture
def env(tmp_path):
    settings=Settings(_env_file=None, app_mode="test", database_url=f"sqlite:///{tmp_path/'test.db'}",
        pii_encryption_key=Fernet.generate_key().decode(), admin_password="test-admin-password",
        safety_reserve=100000, refund_reserve=50000)
    engine, factory=database(settings.database_url); Base.metadata.create_all(engine)
    ids=seed(settings,factory,demo=True)
    commerce=Commerce(settings,factory)
    worker=Worker(commerce); worker.drain()
    result={"settings":settings,"engine":engine,"factory":factory,"ids":ids,"commerce":commerce,"worker":worker}
    yield result
    engine.dispose()

@pytest.fixture
def order_input(env):
    from packages.infrastructure.models import MarketplaceListing
    with env['factory']() as s: listing=s.get(MarketplaceListing, env['ids']['listing_ids'][0]); price=listing.price
    return {"marketplace":"coupang","external_id":"DEMO-ORDER-001","external_line_id":"1",
        "listing_id":env['ids']['listing_ids'][0],"quantity":1,"gross_sale":price,
        "address":{"recipient":"합성 고객","phone":"010-0000-0000","postal_code":"01234",
                   "address1":"가상시 테스트로 123","address2":"101호"}}
