import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from quote_engine import create_quote, approve_quote, respond_to_quote, revise_quote, QuoteError
from quote_engine.storage import SQLiteQuoteStore, QuoteNotFound, QuoteConflict


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'quotes.sqlite3'
        self.store = SQLiteQuoteStore(self.path)
        folder = Path(__file__).resolve().parents[1] / 'data/sample'
        self.menu = json.loads((folder/'menu.json').read_text())
        self.rules = json.loads((folder/'rules.json').read_text())
        self.capacity = json.loads((folder/'capacity.json').read_text())
        self.now = datetime.fromisoformat('2026-10-18T12:00:00-07:00')
        self.request = dict(json.loads((folder/'inquiries.json').read_text())['pricing_example'],
                            headcount=40, event_at='2026-10-23T12:00:00-07:00', address='Demo office')
        self.quote = self.create('customer1')
        self.store.insert(self.quote, actor_id='customer1')

    def create(self, customer):
        return create_quote(self.menu, self.rules, self.request, owner_id='owner1',
                            customer_id=customer, now=self.now, capacity=self.capacity)

    def approved(self):
        loaded = self.store.get(self.quote['quote_id'], actor_id='owner1')
        return approve_quote(loaded, self.menu, self.rules, actor_id='owner1',
                             expected_revision=loaded['revision'], now=self.now, capacity=self.capacity,
                             acknowledged_reviews=loaded['versions'][-1]['readiness']['review_reasons'])

    def test_reopen_full_journey(self):
        approved = self.approved()
        self.store.save(approved, actor_id='owner1', expected_revision=1)
        reopened = SQLiteQuoteStore(self.path)
        customer_quote = reopened.list_quotes(actor_id='customer1', workspace='customer')[0]
        self.assertEqual(customer_quote['versions'][-1]['status'], 'owner_approved')
        accepted = respond_to_quote(customer_quote, actor_id='customer1', expected_revision=2,
                                    now=self.now, decision='accept')
        reopened.save(accepted, actor_id='customer1', expected_revision=2)
        self.assertEqual(SQLiteQuoteStore(self.path).get(accepted['quote_id'], actor_id='owner1'), accepted)

    def test_customer_isolation_and_owner_inbox(self):
        second = self.create('customer2')
        self.store.insert(second, actor_id='customer2')
        self.assertEqual(len(self.store.list_quotes(actor_id='owner1', workspace='owner')), 2)
        self.assertEqual(self.store.list_quotes(actor_id='customer2', workspace='customer'), [second])
        self.assertEqual(self.store.list_quotes(actor_id='customer2', workspace='owner'), [])
        self.assertEqual(self.store.list_quotes(actor_id='other-owner', workspace='owner'), [])
        for actor in ('customer2', 'other-owner', "' OR 1=1 --"):
            with self.assertRaises(QuoteNotFound): self.store.get(self.quote['quote_id'], actor_id=actor)

    def test_missing_and_forbidden_same_error(self):
        for quote_id in ('missing', self.quote['quote_id']):
            with self.assertRaisesRegex(QuoteNotFound, '^quote not found$'):
                self.store.get(quote_id, actor_id='outsider')

    def test_unauthorized_write(self):
        with self.assertRaises(QuoteNotFound):
            self.store.save(self.approved(), actor_id='outsider', expected_revision=1)
        self.assertEqual(self.store.get(self.quote['quote_id'], actor_id='customer1'), self.quote)

    def test_duplicate_does_not_overwrite(self):
        with self.assertRaises(QuoteConflict): self.store.insert(self.quote, actor_id='customer1')
        self.assertEqual(self.store.get(self.quote['quote_id'], actor_id='customer1'), self.quote)

    def test_insert_requires_bound_customer(self):
        with self.assertRaises(QuoteNotFound): self.store.insert(self.create('customer2'), actor_id='customer1')

    def test_atomic_competing_writes(self):
        approved = self.approved()
        def write():
            try:
                SQLiteQuoteStore(self.path).save(approved, actor_id='owner1', expected_revision=1)
                return 'saved'
            except QuoteConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: write(), range(2)))
        self.assertCountEqual(results, ['saved', 'conflict'])

    def test_revisions_preserve_history(self):
        approved = self.approved()
        self.store.save(approved, actor_id='owner1', expected_revision=1)
        revised = revise_quote(approved, self.menu, self.rules, self.request, actor_id='customer1',
                               expected_revision=2, now=self.now, capacity=self.capacity)
        self.store.save(revised, actor_id='customer1', expected_revision=2)
        loaded = SQLiteQuoteStore(self.path).get(self.quote['quote_id'], actor_id='customer1')
        self.assertEqual(loaded['versions'][0], approved['versions'][0])
        self.assertEqual(loaded['versions'][1]['status'], 'draft')
        corrupted = copy.deepcopy(loaded)
        corrupted['revision'] += 1
        corrupted['versions'][0]['status'] = 'draft'
        with self.assertRaises(QuoteError): self.store.save(corrupted, actor_id='owner1', expected_revision=3)
        self.assertEqual(self.store.get(loaded['quote_id'], actor_id='customer1'), loaded)

    def test_participants_cannot_change(self):
        approved = self.approved()
        approved['customer_id'] = 'someone-else'
        with self.assertRaises(QuoteError): self.store.save(approved, actor_id='owner1', expected_revision=1)

    def test_independent_return_values(self):
        loaded = self.store.get(self.quote['quote_id'], actor_id='customer1')
        loaded['versions'].clear()
        self.assertEqual(self.store.get(self.quote['quote_id'], actor_id='customer1'), self.quote)

    def test_pagination_and_invalid_arguments(self):
        self.assertEqual(self.store.list_quotes(actor_id='customer1', workspace='customer', offset=1), [])
        for options in ({'workspace':'bad'}, {'workspace':'customer','limit':True},
                        {'workspace':'customer','offset':-1}):
            with self.assertRaises(QuoteError): self.store.list_quotes(actor_id='customer1', **options)
        with self.assertRaises(QuoteError): self.store.get(self.quote['quote_id'], actor_id='')
        with self.assertRaises(QuoteError): SQLiteQuoteStore(':memory:')
