"""Server-only Supabase Postgres menu storage. Same contract as SQLiteMenuStore.

Apply supabase/migrations/202610190002_menu_storage.sql first. Uses the same
QUOTE_DATABASE_URL server connection as C's PostgresQuoteStore; never expose it.
Not yet tested against a live database (mocked contract tests only).
"""
import os
from contextlib import contextmanager
from uuid import UUID

from quote_engine.pricing import QuoteError

from .storage import MenuConflict, MenuNotFound, check_record


class MenuStorageUnavailable(QuoteError):
    """Database unavailable; no connection details should reach clients."""


def _uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise QuoteError('owner IDs must be UUIDs') from exc


class PostgresMenuStore:
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
            with psycopg.connect(self._dsn, sslmode='require', connect_timeout=10,
                                prepare_threshold=None) as db:
                yield db
        except psycopg.errors.UniqueViolation:
            raise MenuConflict('this business already has a menu') from None
        except psycopg.Error:
            raise MenuStorageUnavailable('menu storage unavailable; please retry') from None

    def create(self, record):
        owner_id = _uuid(record.get('owner_id'))
        if owner_id != record['owner_id']:
            raise QuoteError('owner_id must be a canonical UUID')
        payload = check_record(record)
        if record['revision'] != 1:
            raise QuoteError('a new menu starts at revision 1')
        with self._connect() as db:
            db.execute('''INSERT INTO catering_private.menus (owner_id, revision, payload)
                       VALUES (%s, 1, %s::jsonb)''', (owner_id, payload))

    def get(self, owner_id):
        owner_id = _uuid(owner_id)
        with self._connect() as db:
            row = db.execute('SELECT payload FROM catering_private.menus WHERE owner_id = %s',
                             (owner_id,)).fetchone()
        if row is None:
            raise MenuNotFound('menu not found')
        return row[0]

    def save(self, record, *, expected_revision):
        owner_id = _uuid(record.get('owner_id'))
        payload = check_record(record)
        if type(expected_revision) is not int or record['revision'] != expected_revision + 1:
            raise QuoteError('save must advance revision by exactly one')
        with self._connect() as db:
            result = db.execute('''UPDATE catering_private.menus
                                SET revision = %s, payload = %s::jsonb, updated_at = now()
                                WHERE owner_id = %s AND revision = %s''',
                                (record['revision'], payload, owner_id, expected_revision))
            if result.rowcount != 1:
                exists = db.execute('SELECT 1 FROM catering_private.menus WHERE owner_id = %s',
                                    (owner_id,)).fetchone()
                raise (MenuConflict('menu changed since you loaded it: reload and try again')
                       if exists else MenuNotFound('menu not found'))
