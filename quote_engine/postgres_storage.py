"""Server-only Supabase Postgres adapter. Supabase Auth verification belongs upstream.

No browser access to this private table. Supply actor IDs only from verified Auth
users, and pass records only from the workflow functions, never request JSON.
"""
import os
from contextlib import contextmanager
from uuid import UUID

from .pricing import QuoteError
from .storage import QuoteConflict, QuoteNotFound, _encode, _id


class QuoteStorageUnavailable(QuoteError):
    """Database unavailable; no connection details should reach clients."""


def _uuid(value):
    _id(value)
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise QuoteError('quote/account IDs must be UUIDs') from exc


def _payload(record):
    encoded = _encode(record)
    for field in ('quote_id', 'owner_id', 'customer_id'):
        if _uuid(record[field]) != record[field]:
            raise QuoteError('stored IDs must use canonical UUID format')
    return encoded


class PostgresQuoteStore:
    """Same operation contract as SQLiteQuoteStore; migrations run separately.

    Install requirements-postgres.txt. QUOTE_DATABASE_URL stays on the Python
    server. No connection or schema mutation happens during construction.
    """
    def __init__(self, dsn=None):
        self._dsn = dsn or os.environ.get('QUOTE_DATABASE_URL')
        if not self._dsn:
            raise QuoteError('QUOTE_DATABASE_URL is required')

    @contextmanager
    def _connect(self):
        try:
            import psycopg
        except ImportError:
            raise QuoteError('install requirements-postgres.txt for Postgres storage') from None
        try:
            # Transaction pooler compatible: disable automatic prepared statements.
            with psycopg.connect(self._dsn, sslmode='require', connect_timeout=10,
                                prepare_threshold=None) as db:
                yield db
        except psycopg.errors.UniqueViolation:
            raise QuoteConflict('quote already exists') from None
        except psycopg.Error:
            # Do not echo DSNs, database messages, or customer data to the UI.
            raise QuoteStorageUnavailable('quote storage unavailable; please retry') from None

    def insert(self, record, *, actor_id):
        actor_id = _uuid(actor_id)
        payload = _payload(record)
        if actor_id != record['customer_id']:
            raise QuoteNotFound('quote not found')
        if (record['revision'] != 1 or len(record['versions']) != 1
                or record['versions'][0]['status'] != 'draft'):
            raise QuoteError('only a newly created draft can be inserted')
        with self._connect() as db:
            db.execute('''INSERT INTO catering_private.quotes
                       (quote_id, owner_id, customer_id, revision, payload)
                       VALUES (%s, %s, %s, %s, %s::jsonb)''',
                       (record['quote_id'], record['owner_id'], record['customer_id'], 1, payload))

    def get(self, quote_id, *, actor_id):
        actor_id, quote_id = _uuid(actor_id), _uuid(quote_id)
        with self._connect() as db:
            row = db.execute('''SELECT payload FROM catering_private.quotes
                             WHERE quote_id = %s AND (customer_id = %s OR owner_id = %s)''',
                             (quote_id, actor_id, actor_id)).fetchone()
        if row is None:
            raise QuoteNotFound('quote not found')
        return row[0]

    def list_quotes(self, *, actor_id, workspace, limit=50, offset=0):
        actor_id = _uuid(actor_id)
        if workspace not in ('customer', 'owner'):
            raise QuoteError('workspace must be customer or owner')
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise QuoteError('invalid pagination')
        column = 'customer_id' if workspace == 'customer' else 'owner_id'
        with self._connect() as db:
            rows = db.execute(f'''SELECT payload FROM catering_private.quotes WHERE {column} = %s
                              ORDER BY created_at DESC, quote_id DESC LIMIT %s OFFSET %s''',
                              (actor_id, limit, offset)).fetchall()
        return [row[0] for row in rows]

    def save(self, record, *, actor_id, expected_revision):
        actor_id = _uuid(actor_id)
        payload = _payload(record)
        if (type(expected_revision) is not int or expected_revision < 1
                or record['revision'] != expected_revision + 1):
            raise QuoteError('save must advance revision by exactly one')
        with self._connect() as db:
            row = db.execute('''SELECT payload FROM catering_private.quotes
                             WHERE quote_id = %s AND (customer_id = %s OR owner_id = %s)
                             FOR UPDATE''', (record['quote_id'], actor_id, actor_id)).fetchone()
            if row is None:
                raise QuoteNotFound('quote not found')
            old = row[0]
            if old['revision'] != expected_revision:
                raise QuoteConflict('stale quote: reload before making changes')
            if any(old[key] != record[key] for key in ('owner_id', 'customer_id')):
                raise QuoteError('quote participants cannot change')
            previous, current = old['versions'], record['versions']
            if len(current) == len(previous):
                if current[:-1] != previous[:-1]:
                    raise QuoteError('historical versions cannot change')
            elif len(current) == len(previous) + 1:
                if current[:-1] != previous:
                    raise QuoteError('revision must preserve prior versions')
            else:
                raise QuoteError('invalid version history')
            result = db.execute('''UPDATE catering_private.quotes
                                SET revision = %s, payload = %s::jsonb, updated_at = now()
                                WHERE quote_id = %s AND revision = %s''',
                                (record['revision'], payload, record['quote_id'], expected_revision))
            if result.rowcount != 1:
                raise QuoteConflict('stale quote: reload before making changes')
