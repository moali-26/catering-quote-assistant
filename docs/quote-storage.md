# Persistent Quotes — Integration Guide

**Deployment: Supabase PostgreSQL + Supabase Auth.** The deployed app uses `PostgresQuoteStore` (see [Supabase setup](supabase-setup.md)).

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

Creation follows `create_quote(...)`