"""Opt-in test against an already migrated disposable Supabase development DB.

Creates records under random synthetic account UUIDs; cleans up those records only.
Does not create a project, migrate schemas, or authenticate actual users.
"""
import os
import json
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import unittest
from quote_engine import create_quote, approve_quote, respond_to_quote
from quote_engine.postgres_storage import PostgresQuoteStore
from quote_engine.storage import QuoteNotFound, QuoteConflict


@unittest.skipUnless(os.environ.get('QUOTE_TEST_DATABASE_URL'), 'no disposable Postgres test DB configured')
class LivePostgresTests(unittest.TestCase):
    def test_saved_journey_and_concurrent_updates(self):
        dsn = os.environ['QUOTE_TEST_DATABASE_URL']
        store = PostgresQuoteStore(dsn)
        owner, customer, outsider = [str(uuid4()) for _ in range(3)]
        folder = Path(__file__).resolve().parents[2] / 'data/sample'
        menu, rules, capacity, inquiries = [json.loads((folder/name).read_text()) for name in
                                           ('menu.json','rules.json','capacity.json','inquiries.json')]
        now = datetime.fromisoformat('2026-10-18T12:00:00-07:00')
        request = dict(inquiries['pricing_example'], headcount=40,
                       event_at='2026-10-23T12:00:00-07:00',address='Test office')
        quote = create_quote(menu,rules,request,owner_id=owner,customer_id=customer,now=now,capacity=capacity)
        store.insert(quote,actor_id=customer)
        try:
            with self.assertRaises(QuoteNotFound): store.get(quote['quote_id'],actor_id=outsider)
            self.assertEqual(store.list_quotes(actor_id=outsider,workspace='customer'), [])
            self.assertEqual(store.list_quotes(actor_id=customer,workspace='customer'), [quote])
            approved = approve_quote(quote,menu,rules,actor_id=owner,expected_revision=1,now=now,
                                     capacity=capacity,acknowledged_reviews=quote['versions'][0]['readiness']['review_reasons'])
            def write(_):
                try:
                    PostgresQuoteStore(dsn).save(approved,actor_id=owner,expected_revision=1)
                    return 'saved'
                except QuoteConflict:
                    return 'conflict'
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertCountEqual(list(pool.map(write, range(2))), ['saved','conflict'])
            reopened = PostgresQuoteStore(dsn).get(quote['quote_id'],actor_id=customer)
            accepted = respond_to_quote(reopened,actor_id=customer,expected_revision=2,now=now,decision='accept')
            store.save(accepted,actor_id=customer,expected_revision=2)
            self.assertEqual(PostgresQuoteStore(dsn).get(quote['quote_id'],actor_id=owner), accepted)
        finally:
            with store._connect() as db:
                db.execute('DELETE FROM catering_private.quotes WHERE quote_id = %s AND customer_id = %s',
                           (quote['quote_id'], customer))
