# Production gates — do not enable real operations yet

## Next highest-value implementation step

First run the provided PostgreSQL/Redis integration tests and complete the Next/Docker build in an environment with those services and dependency access. This tests the largest gap between the measured SQLite behavior and the intended deployment. Fix any failures and record source-versioned evidence before connecting live providers.

Then complete one real supplier file workflow: authorized supplier onboarding, validated vendor template/profile, explicit receipt acknowledgement, payout/deposit statement evidence and exception resolution. This is necessary even before marketplace APIs are available; successful XLSX parsing alone is not production-quality supplier operations.

## Internal completion gates

- PostgreSQL concurrent order/payment tests, deferred journal triggers, deadlock/restart/recovery and production-role privileges.
- Redis distributed-rate-limit test, outage behavior and scale/load limits.
- Frontend dependency lock/audit, `npm run typecheck`, `npm run build`, authenticated browser E2E, CSRF/session/accessibility checks.
- Compose clean start and restart, supported Python 3.12 test, image dependency audit, migration evolution, backup/restore drill.
- Reviewed live provider typed contracts, credential binding, webhook authenticity/replay validation, pagination, rate limits and circuit breakers.
- Supplier Excel acknowledgement/payment-evidence workflow, complex template/version editing and pending-cancellation confirmation.
- Multi-line marketplace aggregate rules, split shipments, reshipments, partial fulfillment, post-settlement refunds and negative settlements.
- Manual refund approval/reconciliation, unexplained statement correction and exception-resolution operations beyond acknowledgment.
- External evidence storage/requests, email/webhook transports, supplier-quality composite scores, seasonal scheduling and experiment launch orchestration.
- Approved data retention/legal hold, key rotation, SSO/MFA, least-privilege DB roles and external append-only audit storage.

## External blockers

Coupang seller account credentials and official API authorization; Temu Local Seller/partner whitelist and documented operations; verified AliExpress Korea seller/OAuth permissions; actual supplier file rules/APIs and balances; approved banking/payment/billing/deposit provider. None is fabricated or replaced by an unlabeled hardcoded production success response.

## Automation measurement gate

Define an ordinary-transaction cohort, exclusions, an observation window and the count of all operator interventions, including file collection/delivery, bank deposits, claims evidence and corrective actions. Record a denominator and successful end-to-end outcomes. Distinguish transactions automated without intervention from individual automated steps. The current local human_interventions counter is incomplete for this business-wide purpose. No 95% claim is justified from unit-test coverage or a single synthetic run.
