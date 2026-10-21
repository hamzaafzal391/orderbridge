# Concepts, in easy words

Short notes on the ideas behind OrderBridge. Each page has the same shape: the idea, a real-life
comparison, a tiny example, where it lives in this project, and one question to answer in your
own words.

**How to use them:** read a page, close it, then answer the "Check yourself" question out loud
or on paper. If you can explain it without looking, you know it.

New to a word? See the [glossary](glossary.md).

## Reading order

| # | Page | The idea in a few words |
|---|---|---|
| 01 | [Adapters and translators](01-adapters-and-translators.md) | One piece of code per vendor hides its quirks |
| 02 | [Vendor-independent models](02-vendor-independent-models.md) | Our own data shape, not ERPNext's or GoHighLevel's |
| 03 | [Dependency injection and protocols](03-dependency-injection-and-protocols.md) | Receive your helpers instead of building them |
| 04 | [Validation with Pydantic](04-validation-with-pydantic.md) | Check data at the door |
| 05 | [Classified errors](05-classified-errors.md) | Say what kind of failure it was |
| 06 | [Retries, backoff and jitter](06-retries-backoff-and-jitter.md) | Try again, politely |
| 07 | [Idempotency and duplicates](07-idempotency-and-duplicates.md) | Doing it twice must equal doing it once |
| 08 | [Dry run and safe defaults](08-dry-run-and-safe-defaults.md) | Show first, change only on request |
| 09 | [Exit codes](09-exit-codes.md) | Tell scripts how it went with a number |
| 10 | [Reads versus writes](10-reads-vs-writes.md) | Repeating a read is harmless; repeating a write is not |
| 11 | [Partial failures](11-partial-failures.md) | When a two-step job stops halfway |
| 12 | [Fake servers versus live checks](12-fake-servers-vs-live-checks.md) | A test is only as good as its fake |
| 13 | [CI and branch protection](13-ci-and-branch-protection.md) | A robot checks every change |
| 14 | [Pull requests and decision records](14-pull-requests-and-adrs.md) | Small changes, written reasons |
| 15 | [Idempotency keys and the database](15-idempotency-keys-and-the-database.md) | A shared row decides who does the work |
| 16 | [Webhooks and shared secrets](16-webhooks-and-shared-secrets.md) | A doorbell, and a password at the door |

Planned but not built yet (so not covered here as facts): creating the Sales Order, the credit
check, writing back to the CRM, Docker and AWS deployment.

The project's decision records live in [`../adr/`](../adr/); these notes explain the ideas behind
them in plainer words.
