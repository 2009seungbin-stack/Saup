# Mission

You are the lead architect and senior full-stack engineer responsible for building a production-oriented commerce automation system from scratch inside this repository:

`2009seungbin-stack/Saup`

The repository is currently empty.

Do not merely create a prototype or mock dashboard.

Build a real, modular, testable foundation for a multi-market consignment commerce operating system designed to automate approximately 95% of day-to-day operations.

The initial business domain is:

**Korean domestic food/agricultural consignment sales**

Initial sales channels:

- Temu Korea Local Seller
- Coupang Marketplace
- AliExpress Korea Local Seller / K-Venue where supported

Initial suppliers may not provide APIs and may instead provide:

- Excel price sheets
- Excel order forms
- Excel shipment/tracking files
- manually replenished deposit balances
- web-based seller portals

Therefore the architecture MUST support both:

1. official API integrations
2. Excel/file-based fallback adapters

The system must NEVER fabricate or guess undocumented marketplace API endpoints.

If actual credentials, API approval, partner permissions, or documentation are unavailable, implement the adapter interface, mock/sandbox implementation, validation, configuration and integration tests, and clearly mark the production connector as `BLOCKED_BY_CREDENTIALS` or `BLOCKED_BY_PROVIDER_ACCESS`.

Do not use brittle browser automation for banking or financial transfers.

Financial actions must use only officially supported payment/banking APIs or supplier-supported billing/deposit systems.

---

# Core Business Objective

Build a system that can perform this workflow:

```text
Supplier product/price/stock data
        ↓
Product normalization
        ↓
Market opportunity evaluation
        ↓
Pricing + margin validation
        ↓
Listing creation/update
        ↓
Coupang / Temu / AliExpress
        ↓
Order ingestion
        ↓
Order validation
        ↓
Risk + cash-flow check
        ↓
Supplier order creation
        ↓
Supplier payment
        ↓
Supplier direct shipment
        ↓
Tracking ingestion
        ↓
Marketplace shipment update
        ↓
Delivery
        ↓
Claims / refund handling
        ↓
Marketplace settlement
        ↓
Financial reconciliation
        ↓
Profit/loss analytics
```

Normal orders should require almost no human intervention.

Humans should only handle exceptional cases such as:

- unusually large payments
- supplier disputes
- ambiguous food quality claims
- legal disputes
- API outages
- suspicious orders
- large settlement discrepancies
- new supplier bank account approval
- marketplace policy changes

Target operational automation:

**95%+ of ordinary transactions.**

---

# Mandatory Engineering Principles

## 1. Database is the source of truth

Excel files are NOT the source of truth.

Marketplace APIs are NOT the source of truth.

Supplier portals are NOT the source of truth.

Normalize all external data into our own database first.

Every external system must communicate through an Adapter.

Use a ports-and-adapters / hexagonal architecture.

Example:

```text
MarketplaceAdapter
SupplierAdapter
PaymentAdapter
NotificationAdapter
```

Implementations might include:

```text
CoupangMarketplaceAdapter
TemuMarketplaceAdapter
AliExpressMarketplaceAdapter

SupplierExcelAdapter
SupplierApiAdapter

MockPaymentAdapter
OfficialPaymentProviderAdapter
```

The business logic must not know whether the external source uses REST, Excel or another supported mechanism.

---

# Recommended Technology Stack

Use this unless there is a strong technical reason to deviate.

## Backend

Python 3.12+

FastAPI

SQLAlchemy 2.x

Alembic

Pydantic v2

## Database

PostgreSQL

## Async / Jobs

Redis

Celery or an equivalently robust queue system

Do not run long marketplace synchronization jobs inside HTTP request handlers.

## Frontend

Next.js

TypeScript

React

Keep the admin interface desktop-first, dense and operational rather than consumer-style.

## Excel

openpyxl

Use pandas only when actually useful.

## Testing

pytest

Frontend tests where appropriate.

## Local development

Docker Compose.

One command should start:

- PostgreSQL
- Redis
- backend
- worker
- frontend

---

# Repository Structure

Create a clean monorepo similar to:

```text
Saup/
├─ apps/
│  ├─ api/
│  ├─ worker/
│  └─ web/
│
├─ packages/
│  ├─ domain/
│  ├─ integrations/
│  │  ├─ marketplaces/
│  │  ├─ suppliers/
│  │  ├─ payments/
│  │  └─ notifications/
│  └─ shared/
│
├─ migrations/
├─ scripts/
├─ tests/
├─ fixtures/
├─ docs/
├─ docker/
├─ .env.example
├─ docker-compose.yml
├─ README.md
└─ ARCHITECTURE.md
```

The exact structure may be improved if needed, but keep strict separation between:

- domain logic
- infrastructure
- integrations
- UI

---

# Core Domain Entities

At minimum implement these models.

## Products

```text
Product
SupplierProduct
MarketplaceListing
ProductVariant
```

Important fields:

- internal SKU
- supplier SKU
- title
- category
- origin
- tax type
- weight
- grade
- unit
- supplier cost
- shipping cost
- stock status
- supplier cutoff time
- marketplace-specific listing IDs

---

## Supplier price history

Create:

```text
SupplierPriceHistory
```

Every detected supplier-price change must be retained.

Never overwrite history.

Example:

```text
2026-09-20 13,300 KRW
2026-09-21 13,300 KRW
2026-09-22 14,800 KRW
```

This is essential for:

- margin risk
- volatility calculations
- pricing decisions
- supplier evaluation

---

## Orders

Create a proper state machine.

Do NOT use only:

`pending / shipped / done`.

Use states similar to:

```text
RECEIVED
VALIDATING
VALIDATED
RISK_CHECKED
PAYMENT_RESERVED
SUPPLIER_ORDER_PENDING
SUPPLIER_ORDERED
SUPPLIER_PAID
SHIPMENT_PENDING
SHIPPED
DELIVERED
SETTLEMENT_PENDING
SETTLED
CLOSED
```

Exception states:

```text
CANCEL_REQUESTED
CANCELLED
CLAIM_OPEN
SUPPLIER_CLAIM_OPEN
REFUND_PENDING
REFUNDED
PAYMENT_FAILED
SUPPLIER_FAILED
MANUAL_REVIEW
FAILED
```

All transitions must be explicit and validated.

---

# Idempotency

This is CRITICAL.

Every external operation must have an idempotency key.

Especially:

- supplier orders
- marketplace order ingestion
- payments
- refunds
- shipment updates

Example:

```text
supplier_order_id
payment_id
marketplace_event_id
refund_id
```

Unique constraints must prevent:

- duplicate supplier orders
- duplicate payments
- duplicate refunds

Network retry must never cause money to be sent twice.

---

# Marketplace Integration Layer

Create the common interface:

```text
MarketplaceAdapter

list_products()
create_product()
update_product()
update_price()
update_stock()

list_orders()
get_order()
acknowledge_order()

mark_shipped()
update_tracking()

list_claims()
get_claim()

list_settlements()
```

Do not assume every marketplace supports every function.

Each adapter should expose capability metadata.

Example:

```text
supports_price_update
supports_stock_update
supports_claim_api
supports_webhooks
supports_settlement_api
```

---

# Coupang

Build the Coupang adapter around official Open API documentation only.

Support where available:

- listing/product management
- price updates
- inventory
- orders
- shipping/tracking
- cancellations
- claims/returns
- settlement data

Credentials must come from environment variables or secure secret storage.

Never commit API secrets.

---

# Temu

Build the Temu Partner / Local Seller adapter around officially documented functionality only.

Support capabilities available to our account such as:

- product synchronization
- inventory
- orders
- shipment confirmation
- tracking
- order-status events
- after-sales events

Some APIs may require whitelist permissions.

The system must gracefully expose:

```text
NOT_AUTHORIZED
NOT_SUPPORTED
BLOCKED_BY_PROVIDER_ACCESS
```

instead of faking functionality.

---

# AliExpress

Create the adapter architecture for AliExpress Korea.

Only implement production endpoints that are verifiably available for our seller account.

If Korean Local Seller permissions cannot currently be verified, implement:

- OAuth/config scaffolding
- adapter contract
- mocked integration
- fixtures
- tests
- `BLOCKED_BY_PROVIDER_ACCESS`

Do not invent endpoints.

---

# Supplier Integration

This system MUST work before suppliers provide APIs.

Implement:

```text
SupplierAdapter

get_catalog()
get_prices()
get_inventory()

create_orders()
cancel_order()

get_shipments()
get_claim_status()

get_balance()
```

---

# Excel Supplier Adapter

Build a flexible Excel ingestion/export subsystem.

Do NOT hardcode everything to one supplier.

Create mapping profiles.

Example:

```text
SupplierExcelProfile

supplier_name
order_template
price_template
shipment_template

column mappings
date formats
SKU mappings
```

The system must support:

### Price file import

Example:

```text
supplier SKU
product name
previous cost
current cost
tax
origin
courier
order cutoff
stock
```

Normalize into our DB.

### Order export

Generate supplier-specific Excel files from normalized orders.

### Shipment import

Read:

```text
supplier order ID
marketplace order ID
courier
tracking number
shipping status
```

and automatically associate shipments with orders.

Provide fixtures and tests for malformed Excel files.

Never silently accept:

- missing SKU
- invalid address
- missing quantity
- unexpected numeric values
- duplicate orders

Invalid rows must enter an error queue.

---

# Pricing Engine

Implement deterministic pricing.

AI MUST NOT decide financial values.

Pricing must be rule-based.

Example concept:

```text
required_price =
supplier_cost
+ shipping
+ marketplace_fee
+ expected_claim_cost
+ promotion_cost
+ target_margin
```

Marketplace-specific pricing is allowed.

Example:

```text
Temu: lower due to lower marketplace cost
Ali: medium
Coupang: higher due to fees
```

All pricing formulas must be configurable.

---

# Margin Guard

Before publishing or accepting an order calculate:

```text
expected_contribution_margin
expected_margin_percentage
```

Default rule:

```text
if expected margin < configured threshold:
    stop selling
```

Example threshold:

15%

Make this configurable.

---

# Automatic Price Kill Switch

If supplier price changes significantly:

```text
supplier cost +10%
```

immediately:

1. recalculate price
2. check competitiveness
3. update marketplace price if appropriate
4. OR set stock to 0 / pause listing

Never continue selling below required margin just because marketplace updates failed.

If price synchronization fails:

**pause the affected listing.**

Fail closed, not open.

---

# Inventory Engine

Maintain:

```text
AVAILABLE
LOW
OUT_OF_STOCK
UNKNOWN
```

If supplier inventory becomes unknown for too long:

pause marketplace sales.

Do not oversell unknown food inventory.

---

# Treasury Engine

This is one of the most important modules.

Track separately:

```text
bank balance
supplier deposit balance
marketplace unsettled balance
refund reserve
tax reserve
safety reserve
pending supplier payments
```

NEVER count unsettled marketplace revenue as spendable cash.

Calculate:

```text
AVAILABLE_CASH =
confirmed liquid cash
+ confirmed supplier deposit
- refund reserve
- tax reserve
- safety reserve
- committed supplier payments
```

---

# Automatic Order Capacity

Calculate how many additional orders can safely be accepted.

Example dashboard output:

```text
Available operating cash: ₩823,000
Committed supplier orders: ₩240,000
Refund reserve: ₩150,000

Safe additional order capacity:
37 orders
```

If safe capacity is exceeded:

automatically reduce inventory or pause affected listings.

---

# Payment Automation

Target 95% automation, but financial safety overrides automation.

Production payment automation MUST use:

- supplier-supported deposit API
- supplier-supported registered-card/billing API
- approved payment-provider API
- approved banking API

Never automate:

- internet banking login
- password entry
- OTP
- browser-click account transfers

Implement a generic:

```text
PaymentAdapter

authorize()
pay_supplier()
refund()
get_transaction()
get_balance()
```

Initially implement:

```text
MockPaymentAdapter
ManualApprovalPaymentAdapter
```

And production adapters only where official access is available.

---

# Payment Safety Rules

Implement configurable tiers.

Example:

```text
single supplier payment <= 30,000 KRW
→ automatic

daily supplier payments <= 300,000 KRW
→ automatic if all checks pass

daily total above threshold
→ additional risk check

large payment
→ MANUAL_APPROVAL
```

Do not hardcode the sample values.

Make them settings.

Supplier destination accounts must be whitelisted.

Changing supplier bank details must require:

- manual admin approval
- audit log
- re-verification

---

# Claims Engine

Food claims are a core feature, not an afterthought.

Support categories:

```text
ROTTEN
BROKEN
BRUISED
WRONG_ITEM
MISSING_WEIGHT
DELIVERY_DELAY
CHANGE_OF_MIND
TASTE_COMPLAINT
ADDRESS_ERROR
MISSING_ITEM
OTHER
```

For quality complaints automatically request evidence such as:

1. parcel box with tracking label
2. entire contents
3. close-up of damaged products

Rules must be supplier-configurable.

Example supplier rule:

```text
claims must be submitted within N days after delivery
```

---

# Claims Automation

Workflow:

```text
marketplace claim
↓
classify claim
↓
collect evidence
↓
validate deadline
↓
submit supplier claim
↓
wait supplier response
↓
determine refund / reship / manual review
↓
marketplace action
↓
ledger update
```

AI may classify messages and draft responses.

AI may NOT independently decide large financial refunds.

---

# Claim Loss Tracking

For every SKU calculate:

```text
claim rate
supplier accepted claim rate
seller-paid claim rate
refund loss
claim loss per order
```

True effective cost should include claim losses.

Example:

```text
supplier cost: ₩13,300
average seller-funded claim loss/order: ₩286

effective cost:
₩13,586
```

---

# Claim Kill Switch

Configurable examples:

```text
claim_rate > X
→ warning

seller_loss_rate > Y
→ reduce sales

seller_loss_rate > Z
→ pause SKU
```

Use rolling windows.

Do not blindly use lifetime averages.

---

# Cancellation Race Protection

Prevent this:

```text
marketplace order
↓
supplier paid
↓
customer cancels
```

Before final supplier order/payment:

1. verify order status again
2. check cancellation flag
3. validate shipping address
4. validate stock
5. validate margin
6. validate cash
7. validate supplier cutoff

Support a configurable short order hold where appropriate.

---

# Address Safety

Addresses must NEVER be modified or “corrected” by an LLM.

Marketplace address data must pass deterministically into supplier ordering.

Perform validation only.

Preserve original marketplace address.

Store:

```text
original_address
normalized_address
```

Never discard the original.

---

# Settlement Engine

Expected revenue is not enough.

Implement marketplace settlement reconciliation.

For every order store:

```text
gross_sale
discount
marketplace_fee
promotion_cost
refund
adjustment
expected_settlement
actual_settlement
settlement_difference
```

Automatically flag anomalies.

Example:

```text
Expected: ₩24,900
Actual: ₩23,680
Difference: -₩1,220
```

Large unexplained differences → manual review.

---

# Ledger

Implement double-entry-inspired internal ledgers at minimum.

Tables/modules for:

```text
cash_ledger
supplier_payment_ledger
marketplace_receivable_ledger
refund_ledger
settlement_ledger
```

Every monetary action must be traceable.

Do not rely only on current bank balance.

---

# Market Discovery Engine

This is essential for cold start.

Do NOT assume low reviews mean opportunity.

Separate:

## Demand Score

Potential inputs:

```text
recent marketplace purchase signals
review velocity
search interest
active seller count
seasonality
market price stability
```

## Competition Score

Potential inputs:

```text
review barrier
seller concentration
price competition
promotion saturation
shipping competition
product sameness
```

## Supplier Economics

```text
supplier cost
shipping
fees
claim risk
expected margin
```

Output:

```text
ENTER
TEST
WATCH
DROP
```

Do not scrape sites in violation of policies.

Use authorized APIs, approved data exports or manually supplied market data.

Build the scoring engine so inputs can initially be entered manually.

---

# Cold Start Experiment Engine

Support launching a small group of SKUs as controlled experiments.

Example:

```text
5-SKU probe
```

Track:

```text
impressions
CTR
add-to-cart
orders
conversion rate
claim rate
actual contribution profit
```

Automatically compare SKUs.

Possible states:

```text
PROBE
REWORK
SCALE
PAUSE
DROP
```

Do not automatically scale based only on revenue.

Require positive contribution economics.

---

# Product Quality / Selection Engine

Long term the competitive advantage is removing bad products, not uploading the most products.

Track supplier + SKU performance:

```text
shipment delay rate
claim rate
supplier claim acceptance
seller-funded loss
supplier price volatility
stock availability
repeat purchase
rating
```

Create a Supplier Score and Product Score.

---

# Consumer-facing future data support

Design DB support for future features such as:

```text
current batch/passport data
origin
size/grade
expected count
cutoff
expected shipment date
last information update

recent fulfillment success
recent claim rate
```

Do NOT display unsupported claims.

Every consumer-facing statistic must have:

```text
calculation method
sample size
time window
last updated
```

---

# Seasonal Product Rotation

Support product availability windows.

Example:

```text
OPEN
WAIT
COMING_SOON
HOLD
```

A product may be paused automatically because:

- cost too high
- claim rate too high
- supplier stock unstable
- out of season

---

# AI Layer

AI is permitted for:

- product-title drafts
- descriptions
- FAQ drafts
- customer-service classification
- customer-service draft replies
- review sentiment analysis
- internal market research summaries

AI is NOT permitted to autonomously decide:

- prices
- supplier payment amount
- bank destination
- refund amount above safe automated rules
- inventory quantity
- legal claims
- product origin
- food grade
- food quality metrics
- tax classification

These require deterministic data and rules.

---

# Admin Dashboard

Build a serious operational dashboard.

Main overview should show:

```text
TODAY

Gross sales
Contribution profit
Orders
Claims
Pending supplier orders
Pending payments
Shipment failures

CASH

Bank balance
Supplier deposit
Marketplace receivables
Safety reserve
Refund reserve
Available cash

RISK

SKUs paused
Margin alerts
Price spikes
Claim spikes
Settlement anomalies
Supplier failures

MARKETPLACES

Coupang
Temu
AliExpress

SUPPLIERS

Status
Latest import
Price changes
Stock changes
Pending shipment files
```

Avoid decorative charts unless they are operationally useful.

---

# Manual Review Queue

Create one unified exception queue.

Examples:

```text
PAYMENT_APPROVAL
AMBIGUOUS_CLAIM
SUPPLIER_REJECTED_CLAIM
SETTLEMENT_ANOMALY
ADDRESS_ERROR
LISTING_SYNC_FAILED
PRICE_SYNC_FAILED
MARKETPLACE_AUTH_FAILED
SUPPLIER_FILE_ERROR
```

Normal operation should ideally only require checking this queue.

---

# Notifications

Implement abstraction for:

```text
NotificationAdapter
```

Initially support at least:

- email or console/dev notification
- webhook-ready interface

Important notifications:

```text
large payment approval
margin below threshold
supplier price spike
supplier stock lost
marketplace sync failed
claim deadline approaching
supplier claim rejected
settlement mismatch
daily cash risk
```

---

# Security

This application handles money and customer PII.

Mandatory requirements:

- no secrets in Git
- `.env.example`
- encrypt sensitive values where appropriate
- minimize stored PII
- role-based admin access
- audit logs
- supplier account whitelist
- marketplace credential isolation
- payment credential isolation
- CSRF protection where applicable
- rate limiting
- secure sessions
- no sensitive info in logs

Create a data-retention strategy.

Never log full customer phone/address unless explicitly necessary.

---

# Audit Log

Every important operation must produce an immutable audit event.

Examples:

```text
PRODUCT_PRICE_CHANGED
LISTING_PAUSED
SUPPLIER_ORDER_CREATED
SUPPLIER_PAYMENT_CREATED
PAYMENT_APPROVED
REFUND_CREATED
CLAIM_DECIDED
BANK_ACCOUNT_CHANGED
MARKETPLACE_SYNC_FAILED
```

Store:

```text
actor
timestamp
old value
new value
reason
source
correlation ID
```

---

# Reliability

Implement:

- retries with exponential backoff
- dead-letter handling
- rate-limit handling
- timeout handling
- circuit breakers where useful
- health checks
- integration status
- last successful sync
- replayable external events

Never endlessly retry a payment.

---

# Observability

Structured logging.

Correlation IDs across:

```text
marketplace order
internal order
supplier order
payment
shipment
settlement
claim
```

Create `/health` and integration-status endpoints.

---

# Demo / Fixture Mode

Since real seller API credentials may not yet exist, create a full DEMO mode.

Include synthetic fixtures for:

```text
황금향 3kg
감귤 3kg
고구마 3kg
배 3kg
단감 3kg
```

Simulate:

- supplier cost change
- marketplace order
- cancellation
- claim
- supplier refund
- shipment import
- marketplace settlement
- low cash
- price kill switch

The entire workflow should be testable locally without real money or marketplace accounts.

---

# Safety Rule for Real Money

Real supplier payment must be disabled by default.

Use environment flag:

```text
REAL_PAYMENTS_ENABLED=false
```

Production payment implementation must refuse to operate unless:

```text
REAL_PAYMENTS_ENABLED=true
```

AND valid official provider credentials are present.

Never automatically switch this flag.

---

# Testing Requirements

Implement unit and integration tests covering at least:

1. duplicate marketplace webhook/order
2. duplicate supplier order prevention
3. duplicate payment prevention
4. supplier price spike
5. margin below threshold
6. supplier out of stock
7. customer cancellation before supplier order
8. cancellation after supplier order
9. invalid address
10. malformed supplier Excel
11. duplicate shipment rows
12. customer quality claim
13. supplier claim rejection
14. partial supplier refund
15. full customer refund
16. marketplace settlement mismatch
17. insufficient cash
18. payment above approval threshold
19. integration timeout
20. failed marketplace price update

Critical money/order logic must have strong coverage.

---

# First Implementation Milestones

Do not attempt everything as one uncontrolled giant change.

Implement sequentially.

## Phase 1 — Foundation

- monorepo
- Docker
- FastAPI
- PostgreSQL
- Redis
- worker
- Next.js
- auth
- base models
- audit logging
- health checks

The application must run locally.

## Phase 2 — Domain

- products
- suppliers
- listings
- orders
- state machine
- price histories
- cash ledger
- claims
- settlements

## Phase 3 — Supplier Excel Automation

- supplier profiles
- price import
- SKU mapping
- order export
- shipment import
- malformed file handling

This phase must be production quality.

## Phase 4 — Financial and Risk Engines

- Pricing Engine
- Margin Guard
- Risk Engine
- Treasury Engine
- order capacity
- kill switches
- manual approval queue

## Phase 5 — Marketplace Adapters

- marketplace contract
- mock marketplace
- verified Coupang connector
- verified Temu connector where permissions allow
- Ali connector scaffolding/verified features

## Phase 6 — Claims and Settlement

- claim workflow
- supplier claim workflow
- refunds
- claim loss analytics
- settlement reconciliation

## Phase 7 — Discovery / Cold Start

- Demand Score
- Competition Score
- Supplier Economics
- SKU Probe
- experiment analytics

## Phase 8 — Dashboard

Full operations dashboard.

## Phase 9 — Production Hardening

- security
- observability
- failure testing
- replay tools
- backup/restore docs
- deployment docs

---

# Development Rules

Before coding each phase:

1. inspect existing code
2. document proposed changes
3. implement
4. run tests
5. fix failures
6. update documentation

Do not leave placeholder code silently.

Use explicit TODOs only for genuinely external blockers such as:

```text
TODO BLOCKED_BY_TEMU_PERMISSION
TODO BLOCKED_BY_SUPPLIER_API
```

Every TODO must explain:

- what is missing
- why it is blocked
- how to enable it later

---

# Do Not Do These

Do NOT:

- invent API endpoints
- store credentials in repository
- automate online banking UI
- use LLM decisions for money
- silently swallow Excel errors
- trust supplier files without validation
- treat pending settlement as cash
- send duplicate payments
- automatically refund ambiguous high-value claims
- assume all marketplaces have identical policies
- implement fake “production-ready” integrations using hardcoded responses
- claim 95% automation before measuring it

---

# Definition of Done for MVP

The local demo must allow me to:

1. import a supplier price Excel
2. see products and price changes
3. run margin calculations
4. automatically pause an unprofitable SKU
5. receive simulated marketplace orders
6. validate risk/cash
7. generate supplier order Excel
8. simulate supplier payment
9. import tracking Excel
10. mark marketplace order shipped
11. receive a simulated food-quality claim
12. submit a supplier claim
13. process a refund
14. ingest a settlement
15. reconcile actual vs expected profit
16. see the full transaction trail in the dashboard
17. prove duplicate order/payment requests do not execute twice
18. see all exceptions in one manual-review queue

A new developer must be able to clone the repository and run the entire demonstration through documented commands.

---

# Documentation Required

Create:

```text
README.md
ARCHITECTURE.md
docs/domain-model.md
docs/order-state-machine.md
docs/payment-safety.md
docs/supplier-excel.md
docs/marketplace-integrations.md
docs/claims.md
docs/settlement.md
docs/security.md
docs/deployment.md
```

README must contain:

```text
docker compose up
```

or an equivalently simple local startup process.

---

# Final Work Standard

Do not optimize for speed of generating code.

Optimize for:

- correctness
- financial safety
- traceability
- modularity
- testability
- resilience
- future API replacement of Excel
- ability to operate with minimal human intervention

The result should be a real operating-system foundation for a commerce business, not a UI demo.

Start by creating the architecture and Phase 1 foundation.

Then continue through the phases without asking for unnecessary confirmation.

When an external credential or provider permission prevents a real integration, finish every other part that can be completed, add mocks/tests, clearly record the blocker, and continue.

At the end provide:

1. what was implemented
2. tests executed and results
3. current automation coverage by workflow
4. remaining external blockers
5. security concerns
6. next highest-value implementation step
