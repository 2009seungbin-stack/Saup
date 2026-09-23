"""Provider-neutral ports. Unsupported capabilities are explicit, never fake success."""
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass(frozen=True)
class Capabilities:
    operations: frozenset[str]
    status: str
    mode: str
    supports_webhooks: bool = False

    def public(self):
        return {"operations": sorted(self.operations), "status": self.status, "mode": self.mode,
                "supports_webhooks": self.supports_webhooks}

class Adapter(Protocol):
    capabilities: Capabilities
    def invoke(self, operation: str, payload: dict[str, Any], idempotency_key: str) -> dict: ...

class MarketplaceAdapter(Adapter, Protocol):
    def get_order(self, order_id: str) -> dict: ...
    def mark_shipped(self, payload: dict, idempotency_key: str) -> dict: ...

class SupplierAdapter(Adapter, Protocol):
    def create_orders(self, payload: dict, idempotency_key: str) -> dict: ...
    def cancel_order(self, payload: dict, idempotency_key: str) -> dict: ...

class PaymentAdapter(Adapter, Protocol):
    def pay_supplier(self, payload: dict, idempotency_key: str) -> dict: ...
    def get_transaction(self, idempotency_key: str) -> dict: ...

class NotificationAdapter(Protocol):
    def send(self, category: str, entity_id: str, idempotency_key: str) -> None: ...

MARKETPLACE_OPERATIONS = frozenset({"list_products", "create_product", "update_product", "update_price", "update_stock",
    "list_orders", "get_order", "acknowledge_order", "mark_shipped", "update_tracking", "list_claims", "get_claim",
    "list_settlements", "refund", "sync_listing"})
SUPPLIER_OPERATIONS = frozenset({"get_catalog", "get_prices", "get_inventory", "create_orders", "cancel_order",
    "get_shipments", "get_claim_status", "get_balance", "submit_claim"})
PAYMENT_OPERATIONS = frozenset({"authorize", "pay_supplier", "refund", "get_transaction", "get_balance"})
