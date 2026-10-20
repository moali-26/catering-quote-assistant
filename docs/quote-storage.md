# Persistent Quotes — Integration Guide

**Selected deployment direction: Supabase PostgreSQL + Supabase Auth.** D and C will coordinate the schema and quote adapter; that integration is still pending.

This standard-library SQLite adapter is a local development option, not the planned production database. It saves full quote records and version history across process restarts. Use the same interface with the team's hosted database if needed.

## Server-only contract

Import `SQLiteQuoteStore`, `QuoteNotFound`, and `QuoteConflict` from `quote_engine.storage`.

| Method | Purpose |
| --- | --- |
| `insert(record, actor_id=...)` | Save a new draft created by `create_quote`; actor must match the bound customer |
| `get(quote_id, actor_id=...)` | Return only a quote belonging to that customer or owner |
| `list_quotes(actor_id=..., workspace="customer" or "owner", limit=50, offset=0)` | My Quotes or owner inbox, filtered by authenticated account ID |
| `save(record, actor_id=..., expected_revision=...)` | Persist a trusted workflow result with an atomic revision check |

A `workspace` argument selects a filter; it never grants ownership. Missing and inaccessible records both raise `QuoteNotFound`. Stale/duplicate writes raise `QuoteConflict`; the UI should reload and ask the user to review the latest state, not silently overwrite it.

**These methods are not HTTP endpoints.** Authenticate first. Obtain actor ID from the verified server session and business ownership from trusted records. Never accept complete quote records, roles, customer IDs, menu data, or owner IDs from the browser as authoritative. The adapter enforces participant access; the workflow functions enforce action-specific rules. Calling `save` directly on browser JSON would bypass those rules.

## Connecting an owner approval endpoint

```python
from quote_engine import approve_quote
from quote_engine.storage import SQLiteQuoteStore, QuoteConflict

store = SQLiteQuoteStore("var/quotes.sqlite3")  # create var/ first; do not commit DB files

# These values come from authenticated server code and trusted data sources:
# actor_id, now, current_menu, current_rules, current_capacity
# Browser sends quote_id, expected_revision and checked review codes only.
record = store.get(quote_id, actor_id=actor_id)
updated = approve_quote(
    record, current_menu, current_rules,
    actor_id=actor_id,
    expected_revision=expected_revision,
    now=now,
    acknowledged_reviews=checked_review_codes,
    capacity=current_capacity,
)
store.save(updated, actor_id=actor_id, expected_revision=expected_revision)
```

Creation follows `create_quote(...)` then `insert(...)`. Customer response follows `get(...)`, `respond_to_quote(...)`, then `save(...)`. Revision follows `get(...)`, `revise_quote(...)`, then `save(...)`. Keep the browser's expected revision so an already stale UI cannot inadvertently act on a newer quote. Workflow validation may reject stale input before the database write; either way show a reload message.

Use `list_quotes(actor_id=session_account_id, workspace="customer")` for My Quotes. The owner inbox uses `workspace="owner"`. Each list entry includes the current version at `record["versions"][-1]`; display its workflow status, not the inner pricing status. The list currently returns full records (including history), paginated to at most 100; a later API can return smaller summaries.

## Persistence and concurrency

The adapter uses one connection per operation and closes it afterwards. Writes lock before checking the stored revision and preserve participants and historical versions. Two writes from the same revision cannot both succeed. There is no booking/capacity reservation or atomic transaction with menu edits: the approval service checks the supplied current menu/calendar snapshot. If the team requires consistency across concurrent menu edits and approval, include menu versions in the final database transaction.

SQLite requires a durable local disk on the hosting service. An ephemeral/serverless filesystem (including typical Vercel function storage) is not sufficient. Do not deploy this adapter on a network-shared SQLite file or assume it supports multiple app instances. For hosted Postgres or another database, implement the same operations with ownership filters and atomic revision checks. This module does not create accounts, implement password handling, or provision hosting/storage.

## Verification and remaining work

61 tests pass: 50 calculation/readiness/workflow tests and 11 storage tests. Storage tests cover a saved approval/customer acceptance across fresh store instances, account isolation, competing writes, revisions/history, duplicate creation, immutable participants, and pagination. All tests use temporary databases; no customer data is committed.

D still needs to connect actual authentication, business membership, persistent deployment storage, endpoints, and screens. C assists with the quote action integration. A/B integrations still supply current data and validated AI requests. A browser-level test of logout/login and My Quotes remains required after those integrations exist.


Review update (October 19): three edge cases fixed; all 65 tests pass. See [review notes](review-notes.md) for findings, evidence, and remaining integration requirements. Unrecognized customer allergen names now block approval until clarified; unknown menu allergen information still requires owner review.
