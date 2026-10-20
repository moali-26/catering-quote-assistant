"""Opt-in: chat storage against a real Postgres with the migrations applied.

Set QUOTE_TEST_DATABASE_URL to a disposable development database (never production).
Writes synthetic rows under random UUIDs and deletes them afterwards.
"""
import os
import unittest
import uuid

DSN = os.environ.get('QUOTE_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'QUOTE_TEST_DATABASE_URL not set')
class LiveChatStoreTest(unittest.TestCase):
    def setUp(self):
        from app.chat import PostgresConversationStore
        self.store = PostgresConversationStore(DSN)
        self.customer, self.other, self.owner = (str(uuid.uuid4()) for _ in range(3))
        self.created = []

    def tearDown(self):
        import psycopg
        with psycopg.connect(DSN) as db:
            db.execute('DELETE FROM catering_private.conversations WHERE conversation_id = ANY(%s::uuid[])',
                       (self.created,))
            db.execute('DELETE FROM catering_private.quotes WHERE customer_id = %s', (self.customer,))

    def test_create_save_reload_isolation_and_conflict(self):
        from app.chat import ChatConflict, ChatNotFound
        record = self.store.create(customer_id=self.customer, owner_id=self.owner)
        self.created.append(record['conversation_id'])
        self.assertEqual(self.store.active(customer_id=self.customer)['conversation_id'], record['conversation_id'])
        messages = [{'role': 'user', 'content': 'Lunch for 40'},
                    {'role': 'assistant', 'content': 'Sure', 'tool_calls': []}]
        saved = self.store.save(dict(record, messages=messages), customer_id=self.customer, expected_revision=1)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(self.store.get(record['conversation_id'], customer_id=self.customer)['messages'], messages)
        with self.assertRaises(ChatConflict):
            self.store.save(dict(record, messages=[]), customer_id=self.customer, expected_revision=1)
        with self.assertRaises(ChatNotFound):
            self.store.get(record['conversation_id'], customer_id=self.other)
        with self.assertRaises(ChatConflict):  # another customer cannot overwrite it either
            self.store.save(dict(record, messages=[]), customer_id=self.other, expected_revision=2)
        self.assertIsNone(self.store.active(customer_id=self.other))


    def test_usage_counts_only_customer_messages(self):
        from datetime import datetime, timedelta, timezone
        record = self.store.create(customer_id=self.customer, owner_id=self.owner)
        self.created.append(record['conversation_id'])
        messages = [{'role': 'user', 'content': 'a'}, {'role': 'assistant', 'content': 'b'},
                    {'role': 'user', 'server_note': True, 'content': 'note'}, {'role': 'user', 'content': 'c'}]
        self.store.save(dict(record, messages=messages), customer_id=self.customer, expected_revision=1)
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        self.assertEqual(self.store.usage_since(customer_id=self.customer, since=since), (1, 2))
        self.assertEqual(self.store.usage_since(customer_id=self.other, since=since), (0, 0))

    def test_submit_through_chat_is_idempotent_in_postgres(self):
        """Quote id comes from the conversation id, so a retried submit can't make a second quote."""
        from ai_service import LLMResponse, ScriptedLLM, ToolCall
        from ai_service.data_loader import load_context
        from app.chat import ChatService
        from app.config import load_settings
        from app.quotes import QuoteApp
        from quote_engine.postgres_storage import PostgresQuoteStore
        from unittest import mock
        request = {'headcount': 40, 'event_at': '2026-10-30T12:00:00-07:00', 'service_mode': 'delivery',
                   'address': '9300 Culver Blvd, Culver City, CA', 'allergens': [],
                   'selections': [{'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': 40}]}
        with mock.patch.dict(os.environ, {'APP_DATASET': 'demo', 'OWNER_USER_IDS': self.owner}):
            quotes = QuoteApp(load_settings(), store=PostgresQuoteStore(DSN),
                              context=load_context('demo', now='2026-10-20T09:00:00-07:00'))
        steps = [LLMResponse(tool_calls=[ToolCall('c1', 'evaluate_catering_quote', request)]),
                 LLMResponse(content='Here is your draft.')]
        chat = ChatService(self.store, quotes=quotes, llm_factory=lambda: ScriptedLLM(list(steps)), owner_id=self.owner)
        record = chat.current(self.customer)
        self.created.append(record['conversation_id'])
        record, _turn = chat.send(self.customer, record['conversation_id'], 'Lunch for 40',
                                  expected_revision=record['revision'])
        _, first = chat.submit(self.customer, record['conversation_id'], expected_revision=record['revision'])
        linked = self.store.get(record['conversation_id'], customer_id=self.customer)
        unlinked = self.store.save(dict(linked, quote_id=None), customer_id=self.customer,
                                   expected_revision=linked['revision'])
        _, second = chat.submit(self.customer, record['conversation_id'], expected_revision=unlinked['revision'])
        self.assertEqual(first, second)
        self.assertEqual(len(quotes.service.list_quotes(actor_id=self.customer, workspace='customer')), 1)


if __name__ == '__main__':
    unittest.main()
