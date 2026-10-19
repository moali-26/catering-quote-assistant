"""SQLite adapter for trusted server code; never expose save/insert directly to HTTP clients.

Authentication and business membership are supplied by the application. Workflow
functions must authorize transitions before their returned records are saved.
"""
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path

from .pricing import QuoteError


class QuoteNotFound(QuoteError):
    """Missing and unauthorized records deliberately share one error."""


class QuoteConflict(QuoteError):
    """Duplicate creation or stale write; reload before retrying."""


def _id(value):
    if not isinstance(value, str) or not value.strip():
        raise QuoteError('a nonempty authenticated account ID is required')
    return value


def _encode(record):
    try:
        for field in ('quote_id', 'owner_id', 'customer_id'):
            _id(record[field])
        if type(record['revision']) is not int or record['revision'] < 1:
            raise QuoteError('invalid revision')
        if not isinstance(record['versions'], list) or not record['versions']:
            raise QuoteError('quote must contain a version')
        return json.dumps(record, allow_nan=False)
    except (KeyError, TypeError, ValueError) as exc:
        raise QuoteError('invalid stored quote record') from exc


class SQLiteQuoteStore:
    """File-backed development storage, with a fresh connection per operation.

    Use a persistent disk on a compatible host. This is not suitable for ephemeral
    serverless filesystems or multiple app instances sharing a network filesystem.
    """
    def __init__(self, path):
        if str(path) == ':memory:':
            raise QuoteError('use a file path so quotes survive new connections')
        self.path = str(Path(path))
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS quotes (
                quote_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                payload TEXT NOT NULL
            )''')
            db.execute('CREATE INDEX IF NOT EXISTS quotes_customer ON quotes(customer_id)')
            db.execute('CREATE INDEX IF NOT EXISTS quotes_owner ON quotes(owner_id)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def insert(self, record, *, actor_id):
        """Save a new server-created draft for its authenticated customer.

        Application must resolve owner_id from the selected business server-side.
        """
        _id(actor_id)
        payload = _encode(record)
        if actor_id != record['customer_id']:
            raise QuoteNotFound('quote not found')
        if record['revision'] != 1 or len(record['versions']) != 1 or record['versions'][0]['status'] != 'draft':
            raise QuoteError('only a newly created draft can be inserted')
        try:
            with self._connect() as db:
                db.execute('INSERT INTO quotes VALUES (?, ?, ?, ?, ?)',
                           (record['quote_id'], record['owner_id'], record['customer_id'], 1, payload))
        except sqlite3.IntegrityError as exc:
            raise QuoteConflict('quote already exists') from exc

    def get(self, quote_id, *, actor_id):
        _id(actor_id)
        with self._connect() as db:
            row = db.execute('''SELECT payload FROM quotes WHERE quote_id = ?
                             AND (customer_id = ? OR owner_id = ?)''',
                             (quote_id, actor_id, actor_id)).fetchone()
        if row is None:
            raise QuoteNotFound('quote not found')
        return json.loads(row[0])

    def list_quotes(self, *, actor_id, workspace, limit=50, offset=0):
        """Account-filtered My Quotes or owner inbox; explicit role-specific filters."""
        _id(actor_id)
        if workspace not in ('customer', 'owner'):
            raise QuoteError('workspace must be customer or owner')
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise QuoteError('invalid pagination')
        column = 'customer_id' if workspace == 'customer' else 'owner_id'
        with self._connect() as db:
            rows = db.execute(f'''SELECT payload FROM quotes WHERE {column} = ?
                                ORDER BY rowid DESC LIMIT ? OFFSET ?''',
                              (actor_id, limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save(self, record, *, actor_id, expected_revision):
        """Atomically persist a trusted workflow result, never a client-supplied record.

        Participant access is checked here. Action-specific authorization (for
        example, only an owner approving) belongs to the workflow function.
        """
        _id(actor_id)
        payload = _encode(record)
        if type(expected_revision) is not int or expected_revision < 1 or record['revision'] != expected_revision + 1:
            raise QuoteError('save must advance revision by exactly one')
        with self._connect() as db:
            # Lock before read so ownership/history validation and write are atomic.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT payload FROM quotes WHERE quote_id = ?
                             AND (customer_id = ? OR owner_id = ?)''',
                             (record['quote_id'], actor_id, actor_id)).fetchone()
            if row is None:
                raise QuoteNotFound('quote not found')
            old = json.loads(row[0])
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
            result = db.execute('''UPDATE quotes SET revision = ?, payload = ?
                                WHERE quote_id = ? AND revision = ?''',
                                (record['revision'], payload, record['quote_id'], expected_revision))
            if result.rowcount != 1:
                raise QuoteConflict('stale quote: reload before making changes')
