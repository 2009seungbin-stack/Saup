# Security and retention

## Implemented controls

Secrets come from environment variables / `.env` in local development. Bootstrap creates a random admin password and random Fernet key in a new mode-0600 file and refuses to replace an existing file. Neither file nor key is part of the delivery ZIP. Provider config uses SecretStr; it is not a production secret manager.

Passwords use scrypt with a per-password salt. Sessions are random tokens stored only as hashes, revocable and expiry-checked in the DB. Cookies are HttpOnly/SameSite Strict and Secure in production. Unsafe authenticated requests require the stored CSRF token and exact configured Origin. Session tokens are never placed in browser localStorage. Roles are admin/operator/viewer; API authorization is independent of hidden UI buttons.

Login/session endpoints are rate limited. Memory limits are demo-only; production settings require Redis and fail closed if that backend is unavailable. Request bytes, including chunked bodies, are bounded before parsing. Spreadsheet decompression and row limits apply independently. Add reverse-proxy header/connection/concurrency limits before public exposure.

Original address is encrypted and retained unchanged. Basic reads exclude phone/address/encrypted payload; order export is an authorized, audited PII action. Logs record safe event codes, request/job/correlation identifiers and status, not bodies, cookies, provider response bodies or SQL parameters. SQLAlchemy hide_parameters is enabled. Error responses suppress Pydantic input values and raw database exceptions.

Audit/history/journal/posting ORM edits are rejected; migrations add DB update/delete triggers. PostgreSQL also checks nonempty balanced journals with deferred triggers. A database owner/superuser can still change/drop triggers or truncate data. Use separate migration/runtime roles, revoke schema/DDL/TRUNCATE capabilities and export audit records to a protected external store before production. Those external controls are not deployed by this package.

## Retention strategy — policy gate, not a legal retention claim

Classify session records, encrypted source spreadsheets, order PII, claims evidence, accounting records and immutable audit identifiers separately. Assign an approved retention duration and legal-hold policy per class after obtaining applicable legal/accounting guidance. Do not assume one period is valid for every type of food-commerce record.

Expired sessions can be removed after their security retention window. Source uploads should be removed after successful normalization, reconciliation and the approved dispute window, subject to legal hold. Completed-order PII should be minimized/anonymized when no longer required; immutable financial references remain pseudonymous. A closure timestamp/legal-hold model and a production purge job are **not yet implemented**, so retention deletion is not enabled automatically.

Fernet encryption keys must be backed up separately from database snapshots. Rotate keys with an audited re-encryption process and verify old backups can still be restored. Key rotation automation is not implemented. A lost key makes addresses/uploads unrecoverable; a leaked key compromises them.

## Deployment blockers

No SSO/MFA, external secret manager, production database role separation, append-only off-host audit storage, backup restoration drill, vulnerability/penetration review or installed frontend dependency audit has been completed. The local PostgreSQL password in Compose is deliberately a development-only value on an unexposed container network. Do not expose this Compose deployment publicly or put real customer data in the demo.

Browser security headers include nosniff/frame denial/referrer restrictions. A strict application-specific CSP, TLS termination and production access-log redaction must be validated with a real Next build and browser tests; no CSP compliance claim is made.


## Phase 10 boundary

General supplier list/detail/trail endpoints are PII-minimal; they never serialize Order.pii_ciphertext, encrypted file/row bytes or customer address/phone. The file endpoint is an operator/admin PII export, audited per download and returned no-store. Frozen XLSX and row data use the existing application cipher at rest. Raw evidence screenshots are not uploaded: the console can compute a local hash and records a bounded reference/hash only. Free-form PII notes are deliberately omitted.

Viewer cannot mutate workflow. Operator can batch/export/mark send/record supplier response and payment evidence; only admin can confirm payment or exceptional recovery. Existing session/CSRF/origin/rate-limit checks remain in the extracted auth router. New evidence, confirmation, acceptance and intervention records have ORM and migrated DB append-only protection. Reference hashes and safe typed codes are used in audits. Broader least-privilege DB roles, retention, key rotation and MFA remain deployment gates.
