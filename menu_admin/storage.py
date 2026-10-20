"""SQLite menu storage for local development and tests (same contract as the Postgres adapter).

One row per business, keyed by the owner's account ID (same owner_id that quotes use).
The full menu JSON is stored with a revision number for atomic compare-and-swap saves.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from quote_engine.pricing import QuoteError


class MenuNotFound(QuoteError):
    """No menu for this business, or the actor may not edit it (same message on purpose)."""


class MenuConflict(QuoteError):
    """Stale revision or duplicate creation: reload the menu and re-apply the edit."""


def check_record(record):
    try:
        if not isinstance(record['owner_id'], str) or not record['owner_id'].strip():
            raise QuoteError('owner_id required')
        if type(record['revision']) is not int or record['revision'] < 1:
            raise QuoteError('invalid revision')
        if not isinstance(record['menu'], dict) or not isinstance(record.get('change_log', []), list):
            raise QuoteError('invalid menu record')
        return json.dumps(record, allow_nan=False)
    except (KeyError, TypeError, ValueError) as exc:
        raise QuoteError('invalid menu record') from exc


class SQLiteMenuStore:
    def __init__(self, path):
        if str(path) == ':memory:':
            raise QuoteError('use a file path so menus survive new connections')
        self.path = str(Path(path))
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS menus (
                owner_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                payload TEXT NOT NULL
            )''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, record):
        payload = check_record(record)
        if record['revision'] != 1:
            raise QuoteError('a new menu starts at revision 1')
        try:
            with self._connect() as db:
                db.execute('INSERT INTO menus VALUES (?, ?, ?)', (record['owner_id'], 1, payload))
        except sqlite3.IntegrityError as exc:
            raise MenuConflict('this business already has a menu') from exc

    def get(self, owner_id):
        with self._connect() as db:
            row = db.execute('SELECT payload FROM menus WHERE owner_id = ?', (owner_id,)).fetchone()
        if row is None:
            raise MenuNotFound('menu not found')
        return json.loads(row[0])

    def save(self, record, *, expected_revision):
        payload = check_record(record)
        if type(expected_revision) is not int or record['revision'] != expected_revision + 1:
            raise QuoteError('save must advance revision by exactly one')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            result = db.execute('UPDATE menus SET revision = ?, payload = ? WHERE owner_id = ? AND revision = ?',
                                (record['revision'], payload, record['owner_id'], expected_revision))
            if result.rowcount != 1:
                exists = db.execute('SELECT 1 FROM menus WHERE owner_id = ?', (record['owner_id'],)).fetchone()
                raise (MenuConflict('menu changed since you loaded it: reload and try again')
                       if exists else MenuNotFound('menu not found'))
