# Supplier Excel integration

## Profiles

`SupplierExcelProfile` stores supplier identity, version and JSON mapping. The mapping contains sheet/header row, price columns, explicit defaults, SKU map, order columns and shipment columns. Imports capture the exact profile snapshot/version, so editing a profile cannot reinterpret an existing upload. Current profile API creates new profiles; an audited profile-version update UI is not implemented.

`fixtures/supplier-profile.json` and `fixtures/prices.xlsx` are synthetic examples. Price identifiers are text, including leading zeroes. Do not let Excel convert SKU, order IDs or tracking numbers into numeric cells; such cells are rejected because lost zeroes cannot safely be inferred.

`date_formats` is reserved profile metadata; current normalized price/shipment schemas do not contain free-form date columns, so generalized supplier date/template transformation is not implemented. Export supports supplier-specific headers/order, not arbitrary preservation of complex styled vendor templates.

## Import safety and workflow

An authenticated upload records encrypted XLSX bytes and a content hash, then enqueues work. HTTP does not run the spreadsheet normalization job. The worker validates archive limits, sheet/headers/row counts and individual fields before database mutation.

Hard limits are 5 MB input, 25 MB expanded ZIP, 150 ZIP members, 5,000 data rows and 64 columns. Formulas, macros, external links, encrypted ZIP members, duplicate headers, invalid numeric values and numeric identifiers are rejected. Conventional comma-separated integer prices are supported; NaN, infinity, fractional won and negative values are not.

All same-file duplicate price SKUs are quarantined. Duplicate supplier-order or tracking identities in shipment files are quarantined. Good rows can commit while bad rows create `SUPPLIER_FILE_ERROR` entries with batch/row/error code, never copied customer data. Row writes use savepoints. A repeated profile/version/kind/content hash returns the existing batch.

Catalog normalization preserves price history only when price changes. Unknown/new critical product metadata must be reviewed. Inventory refresh conservatively subtracts unresolved commitments. Restoring a cancelled reservation into a newer stock snapshot is prohibited.

## Supplier order export

The export uses exact decrypted original marketplace address and validates it without modifying it. Cells are explicitly text where appropriate, protecting leading zeroes and strings beginning with formula characters. Export is a privileged, audited PII action with no-store response headers.

**FILE_READY is not ACCEPTED.** A supplier in Excel mode remains waiting for manual/provider acknowledgement. This release does not include a complete manual acknowledgement/payment-proof workflow. The end-to-end demo uses the explicit simulated supplier; the exporter remains useful for real file-format validation but is not claimed production-complete.

## Shipment import

A row must identify the internal supplier-order ID and matching marketplace-order ID, courier and text tracking number. It must belong to the profile's supplier. Only a paid shipment-pending line without cancellation may ship. A repeated identical tracking operation is idempotent; conflicting tracking requires review. No split shipments are supported yet.
