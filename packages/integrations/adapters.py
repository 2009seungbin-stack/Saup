"""Persistent demo provider, isolated from application transactions for retry testing."""
import logging
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from packages.domain.errors import DomainError, IntegrationError
from packages.infrastructure.models import ExternalRecord
from packages.infrastructure.security import fingerprint
from .ports import Capabilities, MARKETPLACE_OPERATIONS, SUPPLIER_OPERATIONS, PAYMENT_OPERATIONS

class BlockedAdapter:
    def __init__(self, name: str, code="BLOCKED_BY_PROVIDER_ACCESS"):
        self.name, self.code = name, code
        self.capabilities = Capabilities(frozenset(), code, "production")

    def invoke(self, operation: str, payload: dict, idempotency_key: str) -> dict:
        raise IntegrationError(self.code)

    def get_order(self, order_id): return self.invoke("get_order", {"id": order_id}, order_id)
    def mark_shipped(self, payload, idempotency_key): return self.invoke("mark_shipped", payload, idempotency_key)
    def create_orders(self, payload, idempotency_key): return self.invoke("create_orders", payload, idempotency_key)
    def cancel_order(self, payload, idempotency_key): return self.invoke("cancel_order", payload, idempotency_key)
    def pay_supplier(self, payload, idempotency_key): return self.invoke("pay_supplier", payload, idempotency_key)
    def get_transaction(self, idempotency_key): return self.invoke("get_transaction", {}, idempotency_key)

class CoupangMarketplaceAdapter(BlockedAdapter):
    def __init__(self): super().__init__("coupang", "BLOCKED_BY_CREDENTIALS")
class TemuMarketplaceAdapter(BlockedAdapter):
    def __init__(self): super().__init__("temu")
class AliExpressMarketplaceAdapter(BlockedAdapter):
    def __init__(self): super().__init__("aliexpress")
class ManualApprovalPaymentAdapter(BlockedAdapter):
    def __init__(self): super().__init__("manual_payment", "MANUAL_APPROVAL_REQUIRED")

class PersistentMockAdapter:
    """A simulated external system, not a production API connector.

    Store only request hashes and non-PII receipts, not plaintext customer payloads.
    A separate committed receipt survives an application-side failure/retry.
    """
    def __init__(self, factory, namespace: str, operations: frozenset[str]):
        self.factory, self.namespace = factory, namespace
        self.capabilities = Capabilities(operations, "DEMO_ONLY", "demo")
        self.fail_next: dict[str, str] = {}  # Explicit fault injection for tests only.

    def invoke(self, operation, payload, idempotency_key):
        if operation not in self.capabilities.operations:
            raise IntegrationError("NOT_SUPPORTED")
        if not idempotency_key or len(idempotency_key) > 200:
            raise DomainError("IDEMPOTENCY_KEY_REQUIRED")
        failure = self.fail_next.pop(operation, None)
        if failure == "timeout_before":
            raise IntegrationError("INTEGRATION_TIMEOUT", retryable=True)
        namespace = f"{self.namespace}:{operation}"
        hashed = fingerprint(payload)
        try:
            with self.factory.begin() as s:
                row = s.scalar(select(ExternalRecord).where(ExternalRecord.namespace == namespace,
                    ExternalRecord.business_key == idempotency_key))
                if row:
                    if row.payload_hash != hashed:
                        raise DomainError("IDEMPOTENCY_CONFLICT")
                    return row.result
                result = {"reference": "demo-" + fingerprint([namespace, idempotency_key])[:24],
                          "status": "SUCCEEDED", "demo": True}
                s.add(ExternalRecord(namespace=namespace, business_key=idempotency_key,
                    payload_hash=hashed, result=result))
        except IntegrityError:
            # A racing identical provider request is read after the winner commits.
            with self.factory() as s:
                row = s.scalar(select(ExternalRecord).where(ExternalRecord.namespace == namespace,
                    ExternalRecord.business_key == idempotency_key))
                if row is None or row.payload_hash != hashed:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return row.result
        if failure == "timeout_after":
            raise IntegrationError("PROVIDER_RESULT_UNKNOWN", uncertain=True)
        return result

    def get_order(self, order_id):
        with self.factory() as s:
            row = s.scalar(select(ExternalRecord).where(ExternalRecord.namespace == f"{self.namespace}:order_status",
                ExternalRecord.business_key == order_id))
            return row.result if row else {"status": "OPEN", "demo": True}

    def set_order_status(self, order_id, status):
        if status not in {"OPEN", "CANCELLED"}: raise DomainError("INVALID_EXTERNAL_ORDER_STATUS")
        with self.factory.begin() as s:
            row = s.scalar(select(ExternalRecord).where(ExternalRecord.namespace == f"{self.namespace}:order_status",
                ExternalRecord.business_key == order_id))
            result = {"status": status, "demo": True}
            if row: row.result = result
            else: s.add(ExternalRecord(namespace=f"{self.namespace}:order_status", business_key=order_id,
                payload_hash=fingerprint(result), result=result))

    def get_transaction(self, idempotency_key):
        with self.factory() as s:
            row = s.scalar(select(ExternalRecord).where(ExternalRecord.namespace == f"{self.namespace}:pay_supplier",
                ExternalRecord.business_key == idempotency_key))
            return row.result if row else {"status": "NOT_FOUND", "demo": True}

    def mark_shipped(self, payload, idempotency_key): return self.invoke("mark_shipped", payload, idempotency_key)
    def create_orders(self, payload, idempotency_key): return self.invoke("create_orders", payload, idempotency_key)
    def cancel_order(self, payload, idempotency_key): return self.invoke("cancel_order", payload, idempotency_key)
    def pay_supplier(self, payload, idempotency_key): return self.invoke("pay_supplier", payload, idempotency_key)

class ConsoleNotificationAdapter:
    def send(self, category, entity_id, idempotency_key):
        logging.getLogger("saup.notifications").info(json.dumps({"event":"notification", "category":category, "entity_id":entity_id, "idempotency_key":idempotency_key}))

class Registry:
    def __init__(self, settings, factory):
        self.settings = settings
        self.live_markets = {"coupang": CoupangMarketplaceAdapter(), "temu": TemuMarketplaceAdapter(),
                             "aliexpress": AliExpressMarketplaceAdapter()}
        self.mocks = {name: PersistentMockAdapter(factory, name, MARKETPLACE_OPERATIONS) for name in self.live_markets}
        self.mock_supplier = PersistentMockAdapter(factory, "supplier", SUPPLIER_OPERATIONS)
        self.mock_payment = PersistentMockAdapter(factory, "payment", PAYMENT_OPERATIONS)
        self.notification = ConsoleNotificationAdapter()

    def marketplace(self, name):
        if name not in self.live_markets: raise DomainError("UNKNOWN_MARKETPLACE")
        return self.mocks[name] if self.settings.app_mode in {"demo", "test"} else self.live_markets[name]

    def supplier(self, supplier_mode):
        if supplier_mode == "demo" and self.settings.app_mode in {"demo", "test"}: return self.mock_supplier
        return BlockedAdapter("supplier", "BLOCKED_BY_SUPPLIER_API")

    def payment(self):
        if self.settings.app_mode in {"demo", "test"}: return self.mock_payment
        return ManualApprovalPaymentAdapter()

    def statuses(self):
        return [{"name": name, "active": self.marketplace(name).capabilities.public(),
                 "production": live.capabilities.public()} for name, live in self.live_markets.items()]
