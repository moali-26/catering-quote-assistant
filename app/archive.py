"""Owner archive: hide finished or unwanted quotes from the owner's inbox, and restore them.

Archiving is an owner-side view setting, not a quote change: quote records, their history,
the workflow and the customer's My Quotes are untouched. The archive is a separate list of
(owner_id, quote_id) pairs; restoring a quote just removes its pair.

If the archive storage is missing (e.g. the migration hasn't been applied) every call raises
ArchiveUnavailable, and the app shows the inbox exactly as before, without archive buttons.
"""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger('app.archive')


class ArchiveUnavailable(Exception):
    """Archive storage can't be reached or doesn't exist yet."""


class SQLiteArchiveStore:
    """Local development storage; same contract as PostgresArchiveStore."""

    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS quote_archive (
                owner_id TEXT NOT NULL, quote_id TEXT NOT NULL, archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (owner_id, quote_id))''')

    @contextmanager
    def _db(self):
        try:
            db = sqlite3.connect(self.path, timeout=10)
        except sqlite3.Error as exc:
            raise ArchiveUnavailable(str(exc)) from None
        try:
            with db:
                yield db
        except sqlite3.Error as exc:
            raise ArchiveUnavailable(str(exc)) from None
        finally:
            db.close()

    def archived_ids(self, owner_id):
        with self._db() as db:
            return {row[0] for row in db.execute('SELECT quote_id FROM quote_archive WHERE owner_id = ?', (owner_id,))}

    def archive(self, owner_id, quote_ids):
        with self._db() as db:
            db.executemany('INSERT OR IGNORE INTO quote_archive (owner_id, quote_id) VALUES (?, ?)',
                           [(owner_id, q) for q in quote_ids])

    def restore(self, owner_id, quote_id):
        with self._db() as db:
            db.execute('DELETE FROM quote_archive WHERE owner_id = ? AND quote_id = ?', (owner_id, quote_id))


class PostgresArchiveStore:
    """catering_private.quote_archive through the server-only connection (never the browser)."""

    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def _db(self):
        import psycopg
        try:
            with psycopg.connect(self.dsn, sslmode='require', connect_timeout=10, prepare_threshold=None) as db:
                yield db
        except psycopg.Error as exc:
            raise ArchiveUnavailable(type(exc).__name__) from None

    def archived_ids(self, owner_id):
        with self._db() as db:
            rows = db.execute('SELECT quote_id FROM catering_private.quote_archive WHERE owner_id = %s',
                              (owner_id,)).fetchall()
        return {str(row[0]) for row in rows}

    def archive(self, owner_id, quote_ids):
        with self._db() as db:
            with db.cursor() as cur:
                cur.executemany('''INSERT INTO catering_private.quote_archive (owner_id, quote_id) VALUES (%s, %s)
                                   ON CONFLICT (owner_id, quote_id) DO NOTHING''',
                                [(owner_id, q) for q in quote_ids])

    def restore(self, owner_id, quote_id):
        with self._db() as db:
            db.execute('DELETE FROM catering_private.quote_archive WHERE owner_id = %s AND quote_id = %s',
                       (owner_id, quote_id))


class Archive:
    """What the routes call. store is None when there is nowhere to keep the archive."""

    def __init__(self, store):
        self.store = store

    def archived_ids(self, owner_id):
        """The owner's archived quote IDs, or None when the archive isn't available (show everything)."""
        if self.store is None:
            return None
        try:
            return self.store.archived_ids(owner_id)
        except ArchiveUnavailable as exc:
            logger.warning('Quote archive unavailable: %s', exc)
            return None

    def archive(self, owner_id, quote_ids):
        if self.store is None:
            raise ArchiveUnavailable('no archive storage')
        quote_ids = [q for q in dict.fromkeys(quote_ids) if q]
        if quote_ids:
            self.store.archive(owner_id, quote_ids)

    def restore(self, owner_id, quote_id):
        if self.store is None:
            raise ArchiveUnavailable('no archive storage')
        self.store.restore(owner_id, quote_id)


def build_archive(settings) -> Archive:
    if settings.database_url:
        return Archive(PostgresArchiveStore(settings.database_url))
    if settings.is_production:
        return Archive(None)
    folder = Path(__file__).resolve().parents[1] / 'var'
    folder.mkdir(exist_ok=True)
    return Archive(SQLiteArchiveStore(folder / 'archive.sqlite3'))
