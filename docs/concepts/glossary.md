# Glossary

Short, plain-language meanings of the words used in this project. Where a word has its own page,
it is linked.

## The business words

- **CRM** (customer relationship management): where the sales team keeps contacts and deals.
  Here: GoHighLevel.
- **ERP** (enterprise resource planning): where the business keeps orders, stock, invoices and
  payments. Here: ERPNext.
- **Customer:** a business or person that buys. In OrderBridge, `Customer` is our own shape for
  one, the same whichever system it came from ([page 02](02-vendor-independent-models.md)).
- **Contact:** a person's card. In ERPNext a contact holds the email and links to a customer.
- **Deal (opportunity):** a possible sale in the CRM, with a stage such as Won.
- **Sales Order:** the ERP's record that a customer ordered something.
- **Credit limit:** the most a customer may owe at once.

## The code words

- **Adapter:** code that hides one outside system's quirks behind a simple, standard shape
  ([page 01](01-adapters-and-translators.md)).
- **Client:** code that talks to another system's API, like a waiter between the app and the
  kitchen. Not the same as a *customer* (someone who buys).
- **API:** the doorway a system offers for other programs to talk to it.
- **API key / token:** a password-like secret that proves who is calling an API. Never committed.
- **CLI** (command line interface): running the program by typing a command, for example
  `python -m app sync <contact_id>` ([page 09](09-exit-codes.md)).
- **Validation:** checking data the moment it arrives ([page 04](04-validation-with-pydantic.md)).
- **Pydantic:** the library that does that checking.
- **Dependency injection:** receiving the helpers a function needs instead of building them, so
  they can be swapped ([page 03](03-dependency-injection-and-protocols.md)).
- **Protocol:** a description of what a helper must be able to do, without naming what it is.
- **Timeout:** the longest we wait for a reply before giving up.

## Reliability words

- **Classified error:** an error that says what kind of failure it was
  ([page 05](05-classified-errors.md)).
- **Retry:** trying a failed request again. **Backoff:** waiting longer each time. **Jitter:** a
  little randomness in the wait ([page 06](06-retries-backoff-and-jitter.md)).
- **Rate limit:** a service saying "too many requests, slow down" (HTTP 429).
- **Idempotent:** doing it twice has the same effect as doing it once
  ([page 07](07-idempotency-and-duplicates.md)).
- **Key (idempotency key):** a piece of text that names one job, such as
  `ghl:opportunity-won:1234`. The database allows each key only once, so the job runs once
  ([page 15](15-idempotency-keys-and-the-database.md)). Not the same as an API key.
- **Primary key:** the database column that makes each row unique.
- **Race condition:** two things happening at the same moment and interfering, for example two runs
  both seeing "no customer yet" and both creating one.
- **Compare-and-swap:** an update that only works if the row is exactly as you last saw it, so only
  one of several simultaneous workers wins.
- **Dry run:** show what would happen, change nothing ([page 08](08-dry-run-and-safe-defaults.md)).
- **Exit code:** the number a command ends with, so scripts know how it went
  ([page 09](09-exit-codes.md)).
- **Partial failure:** a job with two steps that stops after the first
  ([page 11](11-partial-failures.md)).
- **Audit log:** a diary of what the system did and how it went.

## Testing words

- **Unit test:** a fast test of one piece, with no real services.
- **Integration test:** a slower test against a real service, such as PostgreSQL. Marked and run
  separately.
- **Fake (or mock):** a stand-in for a real service in tests. Only as good as the behaviour it
  copies ([page 12](12-fake-servers-vs-live-checks.md)).

## Git and GitHub words

- **Branch:** a separate line of work. **Commit:** a saved snapshot with a message.
- **Pull request (PR):** a proposal to merge a branch, with a description and checks.
- **Squash merge:** combine a PR's commits into one clean commit on `main`.
- **CI** (continuous integration): a robot that runs the checks on every change
  ([page 13](13-ci-and-branch-protection.md)).
- **ADR** (architecture decision record): a short note on why an important decision was made
  ([page 14](14-pull-requests-and-adrs.md)).
- **Tag:** a permanent label on one exact commit. **Release:** the notes page attached to a tag.
  Never move a published tag; publish a new release instead.

## Infrastructure words

- **Docker / container:** a packaged, isolated program, for example a local PostgreSQL.
- **Migration:** a versioned script that creates or changes database tables.
- **Webhook:** a message one system sends to another when something happens, for example "deal
  won". (Planned: OrderBridge's webhook endpoint.)
