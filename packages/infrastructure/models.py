from sqlalchemy.orm import DeclarativeBase
from . import schema_v3 as schema

class Base(DeclarativeBase):
    metadata = schema.metadata

class User(Base): __table__ = schema.users
class AuthSession(Base): __table__ = schema.sessions
class AuditEvent(Base): __table__ = schema.audit
class Review(Base): __table__ = schema.reviews
class Job(Base): __table__ = schema.jobs
class Heartbeat(Base): __table__ = schema.heartbeats
class Command(Base): __table__ = schema.commands
class Supplier(Base): __table__ = schema.suppliers
class Product(Base): __table__ = schema.products
class ProductVariant(Base): __table__ = schema.variants
class SupplierProduct(Base): __table__ = schema.supplier_products
class SupplierPriceHistory(Base): __table__ = schema.price_history
class MarketplaceListing(Base): __table__ = schema.listings
class Order(Base): __table__ = schema.orders
class SupplierOrder(Base): __table__ = schema.supplier_orders
class Account(Base): __table__ = schema.accounts
class Journal(Base): __table__ = schema.journals
class Posting(Base): __table__ = schema.postings
class Reservation(Base): __table__ = schema.reservations
class Payment(Base): __table__ = schema.payments
class Shipment(Base): __table__ = schema.shipments
class Claim(Base): __table__ = schema.claims
class Refund(Base): __table__ = schema.refunds
class Settlement(Base): __table__ = schema.settlements
class SupplierExcelProfile(Base): __table__ = schema.profiles
class ImportBatch(Base): __table__ = schema.imports
class ExternalRecord(Base): __table__ = schema.external_records
class Experiment(Base): __table__ = schema.experiments

class SupplierOrderIntent(Base): __table__ = schema.supplier_intents
class SupplierOrderBatch(Base): __table__ = schema.supplier_batches
class SupplierOrderBatchItem(Base): __table__ = schema.supplier_batch_items
class SupplierBatchAcknowledgement(Base): __table__ = schema.supplier_acknowledgements
class SupplierPaymentEvidence(Base): __table__ = schema.supplier_payment_evidence
class SupplierPaymentConfirmation(Base): __table__ = schema.supplier_payment_confirmations
class SupplierCancellation(Base): __table__ = schema.supplier_cancellations
class OperationalIntervention(Base): __table__ = schema.operational_interventions

class SupplierEvidenceRevision(Base): __table__ = schema.evidence_revisions
class SupplierEvidenceConfirmationBinding(Base): __table__ = schema.evidence_confirmation_bindings
class SupplierCancellationRecovery(Base): __table__ = schema.cancellation_recoveries
class ReviewResolution(Base): __table__ = schema.review_resolutions
