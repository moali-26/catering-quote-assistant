"""Opt-in: A's PostgresMenuStore and the app's live-menu wiring against a real Postgres.

Set QUOTE_TEST_DATABASE_URL to a disposable development database with the migrations
applied (never production). Uses a random owner UUID and deletes its rows afterwards.
"""
import os
import unittest
import uuid
from datetime import datetime, timezone

DSN = os.environ.get('QUOTE_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'QUOTE_TEST_DATABASE_URL not set')
class LiveMenuStoreTest(unittest.TestCase):
    def setUp(self):
        from ai_service.data_loader import load_context
        from menu_admin import MenuService
        from menu_admin.postgres_storage import PostgresMenuStore
        self.owner = str(uuid.uuid4())
        self.context = load_context('demo', now='2026-10-20T09:00:00-07:00')
        self.menus = MenuService(PostgresMenuStore(DSN), clock=lambda: datetime.now(timezone.utc))

    def tearDown(self):
        import psycopg
        with psycopg.connect(DSN) as db:
            db.execute('DELETE FROM catering_private.menus WHERE owner_id = %s', (self.owner,))

    def test_seed_edit_conflict_and_isolation(self):
        from menu_admin import MenuConflict, MenuNotFound
        view = self.menus.seed(self.owner, self.context.menu)
        self.assertEqual(view['revision'], 1)
        with self.assertRaises(MenuConflict):
            self.menus.seed(self.owner, self.context.menu)
        updated = self.menus.update(self.owner, [
            {'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'set': {'price': '15.00'}},
            {'item_id': 'app-hummus', 'set': {'available': False}}], actor_id=self.owner, expected_revision=1)
        self.assertEqual(updated['revision'], 2)
        menu = self.menus.current_menu(self.owner)
        self.assertEqual(next(i for i in menu['items'] if i['id'] == 'pkg-pasta-duo')['variants'][0]['price'], 15.0)
        self.assertFalse(next(i for i in menu['items'] if i['id'] == 'app-hummus')['available'])
        self.assertEqual(len(self.menus.change_log(self.owner, actor_id=self.owner)), 2)
        with self.assertRaises(MenuConflict):  # a second tab still on revision 1
            self.menus.update(self.owner, [{'item_id': 'app-hummus', 'set': {'available': True}}],
                              actor_id=self.owner, expected_revision=1)
        with self.assertRaises(MenuNotFound):  # someone else cannot read or edit it
            self.menus.owner_view(self.owner, actor_id=str(uuid.uuid4()))

    def test_app_prices_from_the_saved_menu(self):
        from app.config import load_settings
        from app.quotes import QuoteApp
        self.menus.seed(self.owner, self.context.menu)
        self.menus.update(self.owner, [{'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'set': {'price': '15.00'}}],
                          actor_id=self.owner, expected_revision=1)
        quotes = QuoteApp(load_settings(), store=object(), context=self.context, menus=self.menus, owner_id=self.owner)
        duo = next(i for i in quotes.current_menu()['items'] if i['id'] == 'pkg-pasta-duo')
        self.assertEqual(duo['variants'][0]['price'], 15.0)
        self.assertEqual(quotes.menu_source, 'saved')


if __name__ == '__main__':
    unittest.main()
