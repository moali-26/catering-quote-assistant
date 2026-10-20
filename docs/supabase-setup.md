# Supabase Quote Storage — Connection Draft

Status: Python adapter and SQL migration prepared; **not applied to a Supabase project or tested against a live Postgres database yet**. The team has not created a shared schema. This draft preserves the existing quote record format and keeps pricing/workflow in Python.

## Design and ownership

- Supabase Auth handles accounts; D builds signup/login and verifies users on the server.
- Supabase PostgreSQL stores quote snapshots in `catering_private.quotes`.
- Python `PostgresQuoteStore` offers the same insert/get/list/save operations as the local SQLite adapter.
- D owns Supabase setup and the app/server connection. C owns quote persistence integration. A's menu tables and E's payment tables are outside this migration.
- This draft maps `owner_id` to one owner's Auth UUID and `customer_id` to the customer's Auth UUID. It does not support multiple employees per business yet. If D adopts business membership tables, align that mapping before applying the migration.

## Why server-only storage

The browser must not directly write a price, approval, or quote record. It calls authenticated Python actions, which load trusted data, run the existing workflow, and save the result. The SQL creates a private schema, enables RLS, and grants no access to `anon` or `authenticated`; there are deliberately no browser policies.

The adapter uses a privileged server-only Postgres connection (initially the migration-owning `postgres` connection from Supabase). Such a connection bypasses RLS. Therefore **the Python actor filters and workflow checks are essential**, not optional. This draft is not a per-user JWT/RLS data-access implementation. Never expose the connection string to the frontend, AI prompts, logs, or repository. A dedicated least-privilege server DB role can be configured with D before deployment; it needs a deliberate policy/grant plan, not public client access.

## Setup order for D + C

1. Create/select the team's development Supabase project. Set up Auth separately; this migration creates no accounts.
2. Review the owner/customer UUID mapping and the table name with C. Do not apply this migration over a different existing quote schema.
3. Run `supabase/migrations/202610190001_quote_storage.sql` once in the Supabase SQL editor as the migration role. It is transactional and intentionally fails if the schema already exists instead of overwriting data.
4. In the Python server environment, install `requirements-postgres.txt` and set `QUOTE_DATABASE_URL` from Supabase **Connect**. Do not paste it into chat. Use the session pooler on IPv4-only hosts, or the connection method appropriate to the final hosting setup.
5. D verifies the customer's Supabase access token server-side (for example, Supabase Auth `get_user(token)`) and extracts the returned account UUID. Never derive identity from browser-submitted IDs or unverified token contents. Resolve the owning business/account from trusted server configuration, not public role signup.
6. Instantiate `PostgresQuoteStore()` after setting the environment. Use existing workflow functions before saving. Do not create a generic endpoint accepting a complete quote object.
7. Run the live test below against a disposable development project, then test the actual signup/login/My Quotes journey after the UI exists.

The adapter requires TLS, times out connections after 10 seconds, and disables prepared statements for transaction-pooler compatibility. It opens/closes one connection per operation. It does not automatically load `.env` files or run migrations.

## Python integration example

```python
from quote_engine import respond_to_quote
from quote_engine.postgres_storage import PostgresQuoteStore

store = PostgresQuoteStore()  # QUOTE_DATABASE_URL from the server environment

# actor_id comes from server-verified Supabase Auth; now is a server clock.
# The browser sends quote_id, decision, and expected_revision only.
record = store.get(quote_id, actor_id=actor_id)
updated = respond_to_quote(
    record, actor_id=actor_id, expected_revision=expected_revision,
    now=now, decision=decision,
)
store.save(updated, actor_id=actor_id, expected_revision=expected_revision)
```

Use `list_quotes(actor_id=actor_id, workspace="customer")` for My Quotes and `workspace="owner"` for the owner inbox. New quotes use canonical UUIDs from Supabase Auth, not the human-readable IDs in local unit-test fixtures.

`save` takes a row lock, checks the old revision, preserves participants/history, and updates within one transaction. It does not authenticate the supplied actor or independently certify a workflow result. A concurrent change requires reload/review. Menu edits and capacity booking remain separate from the quote transaction.

The JSON payload preserves the existing quote record; separate indexed columns support participant queries. Database constraints keep those IDs and revision consistent with the payload. UUID foreign keys to Auth/business tables are deferred until D's account model is confirmed; server-side binding is mandatory meanwhile.

## Validation and limits

```sh
# Local tests (no secrets/network needed):
python3 -m unittest discover -s tests -v

# After applying migration to a disposable development Supabase project:
# Configure QUOTE_TEST_DATABASE_URL securely in your environment first.
python3 -m unittest discover -s tests/integration -v
```

Current result: **75 local tests pass** (65 existing + 10 mocked Postgres adapter contract tests). **The one live Postgres test is skipped** because no test connection is configured. Mock tests validate query arguments and error/guard behavior, not SQL execution, RLS, deployed Auth, or real database concurrency.

The opt-in live test writes synthetic quotes under random UUIDs, checks persistence/account filtering/concurrent updates, and removes only its own test record. It assumes the migration is already applied. It does not prove frontend permissions or actual Supabase Auth behavior; those require the full app integration test. SQL execution remains unverified until the migration is run on development Supabase.

## Official references

- [Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres): connection/pooler choice and prepared-statement restrictions.
- [Supabase row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security): client access policies and privileged-server behavior.
- [Supabase Python get_user](https://supabase.com/docs/reference/python/auth-getuser): server-verified identity.
- [Psycopg transaction/context-manager usage](https://www.psycopg.org/psycopg3/docs/basic/usage.html): commit/rollback and connection cleanup.
