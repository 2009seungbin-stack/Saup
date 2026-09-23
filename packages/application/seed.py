from decimal import Decimal
from sqlalchemy import select
from packages.domain.errors import DomainError
from packages.infrastructure.models import User, Supplier, SupplierExcelProfile, SupplierProduct, MarketplaceListing
from packages.infrastructure.security import hash_password, fingerprint
from packages.integrations.suppliers.excel import ExcelProfile, workbook_bytes
from .common import audit, lock_treasury
from .finance import initialize_accounts, post
from .catalog import apply_price, create_listing

DEMO_PRODUCTS = [("001", "황금향 3kg", 13300), ("002", "감귤 3kg", 10500), ("003", "고구마 3kg", 9000),
                 ("004", "배 3kg", 15000), ("005", "단감 3kg", 11000)]

def demo_profile():
    return ExcelProfile(columns={"supplier_sku":"SKU", "title":"상품명", "cost":"원가", "shipping":"배송비", "stock":"재고"},
        defaults={"category":"농산물", "origin":"대한민국(합성 데모 데이터)", "tax_type":"EXEMPT",
                  "weight_grams":3000, "grade":"합성 데모 등급", "unit":"상자"})

def seed(settings, factory, *, demo=False):
    if demo and settings.app_mode not in {"demo", "test"}: raise DomainError("DEMO_DISABLED", 403)
    with factory.begin() as s:
        initialize_accounts(s); lock_treasury(s)
        username = settings.admin_username
        if not s.scalar(select(User).where(User.username == username)):
            password = settings.admin_password.get_secret_value()
            if not password: raise DomainError("ADMIN_PASSWORD_REQUIRED")
            s.add(User(username=username, password_hash=hash_password(password), role="admin", active=True))
        if not demo: return {}
        supplier = s.scalar(select(Supplier).where(Supplier.name == "DEMO 합성 농산물 공급사"))
        if not supplier:
            supplier = Supplier(name="DEMO 합성 농산물 공급사", mode="demo", cutoff="23:59",
                destination_fingerprint=fingerprint("DEMO-NO-BANK-ACCOUNT"), destination_approved=True,
                destination_approved_by="demo-seed")
            s.add(supplier); s.flush()
            audit(s, "DEMO_SUPPLIER_CREATED", supplier.id, new={"no_real_bank_account": True})
        post(s, "demo-opening-cash", "DEMO_OPENING", {"BANK": 1000000, "EQUITY": -1000000})
        profile = s.scalar(select(SupplierExcelProfile).where(SupplierExcelProfile.supplier_id == supplier.id))
        mapping = demo_profile()
        if profile is None:
            profile = SupplierExcelProfile(supplier_id=supplier.id, name="DEMO 기본 엑셀", mapping=mapping.model_dump())
            s.add(profile); s.flush()
        ids = []
        for sku, title, cost in DEMO_PRODUCTS:
            sp = s.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == supplier.id, SupplierProduct.supplier_sku == sku))
            if sp is None:
                raw = {**mapping.defaults, "supplier_sku":sku, "title":title, "cost":cost, "shipping":3000, "stock":100}
                sp = apply_price(s, settings, supplier.id, raw, fingerprint(raw))
            listing = create_listing(s, settings, sp, "coupang", Decimal("0.10"), demo=True)
            ids.append(listing.id)
        return {"supplier_id":supplier.id, "profile_id":profile.id, "listing_ids":ids}

def price_fixture(spike=False):
    rows = [[sku, title, cost*2 if spike and sku == "001" else cost, 3000, 100] for sku,title,cost in DEMO_PRODUCTS]
    return workbook_bytes(["SKU","상품명","원가","배송비","재고"], rows)
