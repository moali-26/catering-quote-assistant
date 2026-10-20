"""Owner menu editing and the existing chat/quote flow (from PR #17, merged with PR #18).

PR #17 tested these scenarios through /owner/menu/initialize and /owner/menu/update. After
the merge there is one editor, the /owner/menu form, so the same scenarios go through it:
the first visit seeds the menu (once, never overwriting), and a save posts the whole form.
"""
import os
import unittest
from pathlib import Path
from unittest import mock

import test_app_accounts as accounts
from test_app_accounts import OWNER_ID, sample_request
from test_app_menu import form_of
from app.main import create_app
from ai_service import Conversation, LLMResponse, ScriptedLLM, ToolCall
from menu_admin import MenuConflict, MenuNotFound, MenuService, SQLiteMenuStore
from menu_admin.postgres_storage import MenuStorageUnavailable
from quote_engine.postgres_storage import QuoteStorageUnavailable
from quote_engine.pricing import QuoteError

DUO = 'm:pkg-pasta-duo:pkg-pasta-duo-pp:'


@unittest.skipIf(accounts.TestClient is None, 'web dependencies not installed')
class OwnerMenuAppTests(unittest.TestCase):
    client = accounts.AccountsAndQuotesTest.client
    signed_in = accounts.AccountsAndQuotesTest.signed_in
    customer = accounts.AccountsAndQuotesTest.customer

    def setUp(self):
        accounts.AccountsAndQuotesTest.setUp(self)
        self.addCleanup(self.tmp.cleanup)
        self.menus = MenuService(SQLiteMenuStore(Path(self.tmp.name) / 'menus.db'), clock=self.quotes.base_context.now)
        with mock.patch.dict(os.environ, {'APP_ENV': 'development', 'APP_DATASET': 'sample',
                                          'OWNER_USER_IDS': OWNER_ID, 'AUTH_BACKEND': '', 'QUOTE_DATABASE_URL': ''}):
            self.app = create_app(auth_backend=self.auth, quote_app=self.quotes, menu_service=self.menus)
        self.owner = self.signed_in('owner@example.com')

    def form(self):
        page = self.owner.get('/owner/menu')
        self.assertEqual(page.status_code, 200)
        return form_of(page.text)

    def edit(self, data=None, **fields):
        """Post the editor form with some fields changed; None unticks a checkbox."""
        data = dict(data if data is not None else self.form())
        for key, value in fields.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        return self.owner.post('/owner/menu', data=data)

    def revision(self):
        return self.menus.owner_view(OWNER_ID, actor_id=OWNER_ID)['revision']

    def test_first_visit_seeds_once_and_never_overwrites(self):
        with self.assertRaises(MenuNotFound):
            self.menus.current_menu(OWNER_ID)
        self.assertIn('Save changes', self.owner.get('/owner/menu').text)
        self.assertEqual(self.edit(**{DUO + 'price': '14.49'}).status_code, 303)
        self.owner.get('/owner/menu')  # visiting again must not reseed
        with self.assertRaises(MenuConflict):
            self.menus.seed(OWNER_ID, self.quotes.base_context.menu)
        self.assertEqual(self.revision(), 2)

    def test_customer_and_cross_site_cannot_edit(self):
        customer, _ = self.customer()
        self.assertEqual(customer.get('/owner/menu').status_code, 303)
        self.assertEqual(customer.post('/owner/menu', data={'revision': '1'}).status_code, 303)
        with self.assertRaises(MenuNotFound):  # a customer's visit seeds nothing
            self.menus.current_menu(OWNER_ID)
        data = self.form()
        data[DUO + 'price'] = '1.00'
        response = self.owner.post('/owner/menu', data=data, headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.revision(), 1)

    def test_invalid_and_stale_edits(self):
        stale = self.form()
        self.assertEqual(self.edit(**{DUO + 'price': '-1'}).status_code, 400)
        self.assertEqual(self.edit(**{DUO + 'price': '14.49'}).status_code, 303)
        self.assertEqual(self.edit(stale, **{DUO + 'price': '15.49'}).status_code, 409)
        self.assertEqual(self.revision(), 2)

    def test_new_price_existing_chat_new_quote_saved_snapshot(self):
        self.form()
        request = sample_request()
        request.pop('dietary_needs', None)
        saved = self.quotes.service.submit(request, actor_id='customer', owner_id=OWNER_ID)

        def evaluate():
            return LLMResponse(tool_calls=[ToolCall('q', 'evaluate_catering_quote', request)])
        chat = Conversation(ScriptedLLM([evaluate(), LLMResponse(content='Draft.'), evaluate(), LLMResponse(content='Draft.')]),
                            self.quotes.context, context_loader=lambda: self.quotes.context)
        old = chat.send('Price please').quote['result']['pricing']['total_cents']
        self.edit(**{DUO + 'price': '14.49'})
        new = chat.send('Current price please').quote['result']['pricing']['total_cents']
        self.assertEqual(new - old, 4450)
        again = self.quotes.service.submit(request, actor_id='customer', owner_id=OWNER_ID)
        self.assertEqual(again['pricing']['amounts']['total_cents']['cents'], new)
        self.assertEqual(self.quotes.service.detail(saved['quote_id'], actor_id='customer')['pricing'], saved['pricing'])
        with self.assertRaises(QuoteError):
            self.quotes.service.approve(saved['quote_id'], actor_id=OWNER_ID, expected_revision=1,
                                        acknowledged_reviews=saved['readiness']['review_reasons'])
        self.assertIn('$14.49', self.client().get('/').text)

    def test_unavailable_hides_public_menu_and_blocks_quote(self):
        self.assertEqual(self.edit(**{DUO + 'available': None}).status_code, 303)
        self.assertNotIn('The Pasta Duo', self.client().get('/').text)
        with self.assertRaises(QuoteError):
            self.quotes.service.submit(sample_request(), actor_id='customer', owner_id=OWNER_ID)

    def test_storage_failure_does_not_return_frozen_prices(self):
        self.form()
        self.quotes.forget_menu()
        with mock.patch.object(self.menus, 'current_menu', side_effect=MenuStorageUnavailable('offline')):
            self.assertEqual(self.client().get('/').status_code, 503)
            with self.assertRaises(QuoteStorageUnavailable):
                self.quotes.service.submit(sample_request(), actor_id='customer', owner_id=OWNER_ID)

    def test_item_edit_escaped_and_unknown_item_ignored(self):
        self.assertEqual(self.edit(**{'m:pkg-pasta-duo:name': '<script>bad</script>'}).status_code, 303)
        text = self.owner.get('/owner/menu').text
        self.assertIn('&lt;script&gt;', text)
        self.assertNotIn('<script>bad</script>', text)
        # fields for a dish that isn't on the menu change nothing
        self.edit(**{'m:missing:name': 'Ghost dish', 'm:missing:x:price': '1.00'})
        self.assertEqual(self.revision(), 2)
        self.assertNotIn('Ghost dish', self.owner.get('/owner/menu').text)

    def test_owner_can_explicitly_reprice_pending_quote(self):
        self.form()
        saved = self.quotes.service.submit(sample_request(), actor_id='customer', owner_id=OWNER_ID)
        self.edit(**{DUO + 'price': '14.49'})
        response = self.owner.post('/quotes/' + saved['quote_id'] + '/reprice', data={'revision': 1})
        self.assertEqual(response.status_code, 303)
        new = self.quotes.service.detail(saved['quote_id'], actor_id=OWNER_ID)
        self.assertEqual(len(new['history']), 2)
        self.assertEqual(new['status'], 'draft')
        self.assertGreater(new['pricing']['amounts']['total_cents']['cents'],
                           saved['pricing']['amounts']['total_cents']['cents'])
        customer, _ = self.customer()
        self.assertEqual(customer.post('/quotes/' + saved['quote_id'] + '/reprice', data={'revision': 2}).status_code, 303)
        self.assertEqual(self.quotes.service.detail(saved['quote_id'], actor_id=OWNER_ID)['revision'], 2)


if __name__ == '__main__':
    unittest.main()
