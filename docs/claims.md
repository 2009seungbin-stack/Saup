# Claims and quality risk

Supported categories: ROTTEN, BROKEN, BRUISED, WRONG_ITEM, MISSING_WEIGHT, DELIVERY_DELAY, CHANGE_OF_MIND, TASTE_COMPLAINT, ADDRESS_ERROR, MISSING_ITEM, OTHER.

Flow implemented: claim ingestion → deterministic category/evidence checks → supplier deadline check → supplier submission job → accepted/rejected response → refund eligibility or review → bounded customer refund → ledger adjustment. Evidence kinds for food quality claims are parcel label, entire contents and damage close-up. These are reference-kind checks, **not a complete media upload/storage/evidence-verification system**. The console notification identifies missing evidence; automatic customer messaging is not implemented.

Taste/change-of-mind/other or late claims require review. Supplier rejection creates a separate review. Rules cannot determine statutory consumer rights: deadlines are supplier operational rules, not a claim that consumers lose legal remedies after that period. No automatic legal decisions are made.

Accepted supplier compensation is stored separately from confirmed recovery. Only an explicit confirmed receipt credits supplier deposit cash. Recovery is capped by supplier accepted amount and total paid to that supplier for the order. Customer refunds are capped both by claim requested amount and order net sale, including pending/unknown/manual refund commitments.

Large or ambiguous refunds create MANUAL_APPROVAL unless an administrator explicitly approves that decision. The current API supports explicit administrator creation; approving a previously created manual refund and provider-specific uncertain refund reconciliation still need a fuller operational workflow. Do not create a second refund to bypass a pending manual one.

A marketplace-mediated refund debits refund expense and reduces marketplace receivables. It does not also debit bank cash. Post-settlement refunds and negative settlement outcomes go to manual reconciliation; their full financial workflows are not yet implemented.

Rolling claim controls use a configured delivered-order cohort, sample minimum, warning/pause rates and seller-funded loss/net-revenue rate. Small samples do not trigger quality claims or scaling. Default policy values are examples, not verified optimal commercial thresholds. Stats report window/sample/method/update time. The system pauses listings when configured loss thresholds are exceeded; graduated stock reduction and reshipment optimization remain future work.

No AI message classifier, reply generator or autonomous quality judgment is implemented. The financial logic does not depend on AI.
