"""Ledger and treasury functions. Call under lock_treasury in a single transaction."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func, select, or_
from packages.domain.errors import DomainError
from packages.domain.pricing import krw
from packages.infrastructure.models import Account, Journal, Posting, Reservation, Payment, Order, SupplierProduct, MarketplaceListing
from packages.infrastructure.schema_v1 import uid
from packages.infrastructure.security import fingerprint
from packages.infrastructure.db import aware
from .common import audit, lock_treasury

ACCOUNTS = ("CONTROL", "BANK", "EQUITY", "SUPPLIER_EXPENSE", "MARKETPLACE_RECEIVABLE",
            "REVENUE", "MARKETPLACE_FEES", "PROMOTION_EXPENSE", "REFUND_EXPENSE",
            "SUPPLIER_RECOVERY", "SETTLEMENT_CLEARING", "SETTLEMENT_VARIANCE")


def initialize_accounts(s):
    for code in ACCOUNTS:
        if s.scalar(select(Account).where(Account.code == code)) is None:
            s.add(Account(code=code, balance=0))
    s.flush()


def account(s, code: str):
    row = s.scalar(select(Account).where(Account.code == code))
    if row is None:
        row = Account(code=code, balance=0)
        s.add(row)
        s.flush()
    return row


def post(s, key: str, kind: str, entries: dict[str, int], order_id=None, correlation_id=None):
    entries = {code: amount for code, amount in entries.items() if amount != 0}
    if len(entries) < 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in entries.values()) or sum(entries.values()) != 0:
        raise DomainError("UNBALANCED_JOURNAL")
    if any(abs(v) > 10**12 for v in entries.values()):
        raise DomainError("INVALID_KRW")
    hashed = fingerprint({"kind": kind, "entries": entries, "order_id": order_id})
    existing = s.scalar(select(Journal).where(Journal.business_key == key))
    if existing:
        if existing.payload_hash != hashed:
            raise DomainError("IDEMPOTENCY_CONFLICT")
        return existing
    journal = Journal(business_key=key, kind=kind, payload_hash=hashed, order_id=order_id, correlation_id=correlation_id or uid())
    s.add(journal)
    s.flush()
    for code, delta in sorted(entries.items()):
        a = account(s, code)
        a.balance += delta
        s.add(Posting(journal_id=journal.id, account_id=a.id, delta=delta))
    audit(s, "LEDGER_POSTED", journal.id, new={"kind": kind, "entry_count": len(entries)}, correlation_id=journal.correlation_id)
    s.flush()
    return journal


def balance(s, code: str) -> int:
    result = s.scalar(select(Account.balance).where(Account.code == code))
    return result or 0


def treasury(s, settings, supplier_id=None) -> dict:
    bank_held = s.scalar(select(func.coalesce(func.sum(Reservation.bank_amount), 0)).where(Reservation.status == "HELD"))
    reserves = settings.safety_reserve + settings.refund_reserve + settings.tax_reserve
    bank = balance(s, "BANK")
    free_bank = bank - bank_held - reserves
    deposit = balance(s, f"DEPOSIT:{supplier_id}") if supplier_id else 0
    deposit_held = s.scalar(select(func.coalesce(func.sum(Reservation.deposit_amount), 0)).where(
        Reservation.supplier_id == supplier_id, Reservation.status == "HELD")) if supplier_id else 0
    free_deposit = max(0, deposit - deposit_held)
    # A deposit cannot pay unrelated suppliers or fund a missing liquid refund reserve.
    spendable = max(0, free_bank) + free_deposit if free_bank >= 0 else 0
    return {"bank_balance": bank, "bank_committed": bank_held, "supplier_deposit": deposit,
        "supplier_deposit_committed": deposit_held, "refund_reserve": settings.refund_reserve,
        "tax_reserve": settings.tax_reserve, "safety_reserve": settings.safety_reserve,
        "free_bank": free_bank, "free_supplier_deposit": free_deposit, "available_cash": spendable,
        "marketplace_receivable": balance(s, "MARKETPLACE_RECEIVABLE"),
        "settlement_awaiting_bank_confirmation": balance(s, "SETTLEMENT_CLEARING")}


def capacity(s, settings, supplier_id: str, cost_per_order: int) -> int:
    krw(cost_per_order)
    if not cost_per_order:
        return 0
    return treasury(s, settings, supplier_id)["available_cash"] // cost_per_order


def reserve(s, settings, order, supplier_product, amount: int):
    krw(amount)
    existing = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
    if existing and existing.status == "HELD":
        if existing.bank_amount + existing.deposit_amount != amount:
            raise DomainError("RESERVATION_AMOUNT_CHANGED")
        return existing
    if existing:
        raise DomainError("RESERVATION_ALREADY_FINAL")
    position = treasury(s, settings, supplier_product.supplier_id)
    if amount > position["available_cash"]:
        raise DomainError("INSUFFICIENT_CASH")
    if supplier_product.stock is None or supplier_product.stock < order.quantity:
        raise DomainError("OUT_OF_STOCK")
    deposit = min(amount, position["free_supplier_deposit"])
    row = Reservation(order_id=order.id, supplier_id=supplier_product.supplier_id,
        bank_amount=amount - deposit, deposit_amount=deposit, status="HELD",
        inventory_snapshot_at=supplier_product.last_inventory_at)
    supplier_product.stock -= order.quantity
    if supplier_product.stock == 0:
        supplier_product.stock_status = "OUT_OF_STOCK"
    s.add(row)
    audit(s, "CASH_RESERVED", order.id, new={"bank": amount-deposit, "deposit": deposit}, correlation_id=order.correlation_id)
    s.flush()
    return row


def release(s, order, *, restore_inventory=True):
    row = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
    if row is None or row.status == "RELEASED":
        return
    if row.status != "HELD":
        raise DomainError("PAID_RESERVATION_CANNOT_BE_RELEASED")
    listing = s.get(MarketplaceListing, order.listing_id)
    sp = s.get(SupplierProduct, listing.supplier_product_id)
    # Do not restore stock into a newer supplier snapshot; that could double-count.
    if restore_inventory and sp.stock is not None and aware(sp.last_inventory_at) == aware(row.inventory_snapshot_at):
        sp.stock += order.quantity
        sp.stock_status = "AVAILABLE" if sp.stock > 5 else "LOW"
    row.status = "RELEASED"
    audit(s, "CASH_RESERVATION_RELEASED", order.id, correlation_id=order.correlation_id)


def daily_commitments(s, exclude_id=None, at=None) -> int:
    at = at or datetime.now(timezone.utc)
    local = at.astimezone(ZoneInfo("Asia/Seoul"))
    start = datetime.combine(local.date(), time.min, ZoneInfo("Asia/Seoul")).astimezone(timezone.utc)
    query = select(func.coalesce(func.sum(Payment.amount), 0)).where(or_(Payment.status.in_(["PENDING", "EVIDENCE_PENDING", "SENDING", "UNKNOWN"]),
        (Payment.status == "SUCCEEDED") & (Payment.dispatched_at >= start)))
    if exclude_id:
        query = query.where(Payment.id != exclude_id)
    return s.scalar(query)


def settle_payment(s, payment, provider_reference: str, *, source="DEMO_PROVIDER"):
    if payment.status == "SUCCEEDED":
        return
    order = s.get(Order, payment.order_id)
    reservation = s.scalar(select(Reservation).where(Reservation.order_id == order.id))
    if reservation is None or reservation.status != "HELD":
        raise DomainError("PAYMENT_WITHOUT_RESERVATION")
    if reservation.bank_amount + reservation.deposit_amount != payment.amount:
        raise DomainError("PAYMENT_RESERVATION_MISMATCH")
    if balance(s, "BANK") < reservation.bank_amount or balance(s, f"DEPOSIT:{reservation.supplier_id}") < reservation.deposit_amount:
        raise DomainError("PAYMENT_WOULD_OVERDRAW_ACCOUNT")
    entries = {"SUPPLIER_EXPENSE": payment.amount, "BANK": -reservation.bank_amount,
               f"DEPOSIT:{reservation.supplier_id}": -reservation.deposit_amount}
    post(s, f"supplier-payment:{payment.id}", "SUPPLIER_PAYMENT", entries, order.id, order.correlation_id)
    reservation.status = "SPENT"
    payment.status = "SUCCEEDED"
    payment.provider_reference = provider_reference
    audit(s, "SUPPLIER_PAYMENT_CREATED", order.id, new={"amount": payment.amount, "demo": source == "DEMO_PROVIDER", "source": source}, correlation_id=order.correlation_id)
