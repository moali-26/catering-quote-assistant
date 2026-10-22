"""Opt-in: the owner archive table against a real Postgres (QUOTE_TEST_DATABASE_URL, migrations applied)."""
import os
import unittest
import uuid

DSN = os.environ.get('QUOTE_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'QUOTE_TEST_DATABASE_URL not set')
class LiveArchiveStoreTest(unittest.TestCase):
    def setUp(self):
        import psycopg
        from app.archive import PostgresArchiveStore
        self.owner, self.customer = str(uuid.uuid4()), str(uuid.uuid4())
        self.quotes = [str(uuid.uuid4()) for _ in range(2)]
        with psycopg.connect(DSN) as db:
            for q in self.quotes:
                payload = {'quote_id': q, 'owner_id': self.owner, 'customer_id': self.customer, 'revision': 1,
                           'versions': [{'version': 1}]}
                db.execute('INSERT INTO catering_private.quotes (quote_id, owner_id, customer_id, revision, payload) '
                           'VALUES (%s, %s, %s, 1, %s::jsonb)', (q, self.owner, self.customer, psycopg.types.json.Json(payload)))
        self.store = PostgresArchiveStore(DSN)

    def tearDown(self):
        import psycopg
        with psycopg.connect(DSN) as db:
            db.execute('DELETE FROM catering_private.quotes WHERE owner_id = %s', (self.owner,))

    def test_archive_restore_and_cascade(self):
        import psycopg
        self.store.archive(self.owner, self.quotes)
        self.store.archive(self.owner, self.quotes[:1])  # repeat is a no-op
        self.assertEqual(self.store.archived_ids(self.owner), set(self.quotes))
        self.assertEqual(self.store.archived_ids(str(uuid.uuid4())), set())  # another owner sees nothing
        self.store.restore(self.owner, self.quotes[0])
        self.assertEqual(self.store.archived_ids(self.owner), {self.quotes[1]})
        with psycopg.connect(DSN) as db:  # deleting a quote removes its archive row
            db.execute('DELETE FROM catering_private.quotes WHERE quote_id = %s', (self.quotes[1],))
        self.assertEqual(self.store.archived_ids(self.owner), set())


if __name__ == '__main__':
    unittest.main()
