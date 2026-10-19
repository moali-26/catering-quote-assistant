"""Adapter contract tests with a mocked database; not live Postgres evidence."""
import copy
import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from quote_engine import QuoteError
from quote_engine.storage import QuoteConflict, QuoteNotFound
from quote_engine.postgres_storage import PostgresQuoteStore


class PostgresAdapterTests(unittest.TestCase):
    def setUp(self):
        self.customer, self.owner, self.qid = [str(uuid4()) for _ in range(3)]
        self.old = dict(quote_id=self.qid, customer_id=self.customer, owner_id=self.owner,
                        revision=1, versions=[{'status':'draft','version':1}])
        self.new = copy.deepcopy(self.old)
        self.new['revision'] = 2
        self.new['versions'][0]['status'] = 'owner_approved'
        self.store = PostgresQuoteStore('test-only-dsn')
        self.db = MagicMock()
        context = patch.object(self.store, '_connect')
        self.mock_connect = context.start()
        self.addCleanup(context.stop)
        self.mock_connect.return_value.__enter__.return_value = self.db

    def test_insert_uses_bound_parameters(self):
        self.store.insert(self.old, actor_id=self.customer)
        sql, params = self.db.execute.call_args.args
        self.assertNotIn(self.customer, sql)
        self.assertEqual(params[:4], (self.qid,self.owner,self.customer,1))
        self.assertEqual(json.loads(params[4]), self.old)

    def test_insert_wrong_actor_never_connects(self):
        with self.assertRaises(QuoteNotFound): self.store.insert(self.old, actor_id=self.owner)
        self.mock_connect.assert_not_called()

    def test_reads_filter_by_actor(self):
        self.db.execute.return_value.fetchone.return_value = (self.old,)
        self.assertEqual(self.store.get(self.qid, actor_id=self.customer), self.old)
        sql, params = self.db.execute.call_args.args
        self.assertIn('customer_id = %s OR owner_id = %s', sql)
        self.assertEqual(params, (self.qid,self.customer,self.customer))

    def test_missing_is_controlled(self):
        self.db.execute.return_value.fetchone.return_value = None
        with self.assertRaises(QuoteNotFound): self.store.get(self.qid, actor_id=self.customer)

    def test_list_uses_role_specific_filter(self):
        self.db.execute.return_value.fetchall.return_value = [(self.old,)]
        self.assertEqual(self.store.list_quotes(actor_id=self.owner, workspace='owner'), [self.old])
        sql, params = self.db.execute.call_args.args
        self.assertIn('WHERE owner_id = %s', sql)
        self.assertEqual(params, (self.owner,50,0))

    def test_save_locks_then_updates_expected_revision(self):
        self.db.execute.return_value.fetchone.return_value = (self.old,)
        self.db.execute.return_value.rowcount = 1
        self.store.save(self.new, actor_id=self.owner, expected_revision=1)
        calls = self.db.execute.call_args_list
        self.assertIn('FOR UPDATE', calls[0].args[0])
        self.assertIn('AND revision = %s', calls[1].args[0])
        self.assertEqual(calls[1].args[1][-2:], (self.qid,1))

    def test_stale_write_does_not_update(self):
        stored = dict(self.old, revision=2)
        self.db.execute.return_value.fetchone.return_value = (stored,)
        with self.assertRaises(QuoteConflict): self.store.save(self.new, actor_id=self.owner, expected_revision=1)
        self.assertEqual(self.db.execute.call_count, 1)

    def test_changed_participants_rejected(self):
        self.db.execute.return_value.fetchone.return_value = (self.old,)
        self.new['customer_id'] = str(uuid4())
        with self.assertRaises(QuoteError): self.store.save(self.new, actor_id=self.owner, expected_revision=1)
        self.assertEqual(self.db.execute.call_count, 1)

    def test_history_cannot_be_replaced(self):
        self.db.execute.return_value.fetchone.return_value = (self.old,)
        self.new['versions'].append({'version':2,'status':'draft'})
        with self.assertRaises(QuoteError): self.store.save(self.new, actor_id=self.owner, expected_revision=1)

    def test_invalid_arguments_never_connect(self):
        with self.assertRaises(QuoteError): self.store.get(self.qid, actor_id='forged-name')
        with self.assertRaises(QuoteError): self.store.list_quotes(actor_id=self.customer, workspace='admin')
        with self.assertRaises(QuoteError): self.store.list_quotes(actor_id=self.customer, workspace='customer', limit=True)
        self.mock_connect.assert_not_called()
