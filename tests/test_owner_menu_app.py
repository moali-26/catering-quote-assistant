"""Owner editor routes and DB menu -> existing chat/quote integration."""
import os
from pathlib import Path
from unittest import mock
import unittest
import test_app_accounts as accounts
from test_app_accounts import OWNER_ID, PASSWORD, sample_request
from menu_admin import MenuService, SQLiteMenuStore
from menu_admin.postgres_storage import MenuStorageUnavailable
from app.main import create_app
from ai_service import Conversation, ScriptedLLM, LLMResponse, ToolCall
from quote_engine.pricing import QuoteError


class OwnerMenuAppTests(unittest.TestCase):
    client = accounts.AccountsAndQuotesTest.client
    signed_in = accounts.AccountsAndQuotesTest.signed_in
    customer = accounts.AccountsAndQuotesTest.customer
    def setUp(self):
        accounts.AccountsAndQuotesTest.setUp(self)
        self.addCleanup(self.tmp.cleanup)
        self.menus = MenuService(SQLiteMenuStore(Path(self.tmp.name)/'menus.db'), clock=self.quotes._context.now)
        with mock.patch.dict(os.environ, {'APP_ENV':'development','APP_DATASET':'sample',
                  'OWNER_USER_IDS':OWNER_ID,'AUTH_BACKEND':'','QUOTE_DATABASE_URL':''}):
            self.app=create_app(auth_backend=self.auth,quote_app=self.quotes,menu_service=self.menus)
        self.owner=self.signed_in('owner@example.com')
    def initialize(self):
        self.assertEqual(self.owner.post('/owner/menu/initialize').status_code,303)
    def edit(self, revision=1, **overrides):
        data=dict(revision=revision,item_id='pkg-pasta-duo',variant_id='pkg-pasta-duo-pp',price='14.49',available='true')
        data.update(overrides)
        return self.owner.post('/owner/menu/update',data=data)
    def test_initialize_and_render_and_no_overwrite(self):
        self.assertIn('Initialize menu',self.owner.get('/owner/menu').text)
        self.initialize()
        self.assertIn('Save price',self.owner.get('/owner/menu').text)
        self.assertEqual(self.edit().status_code,303)
        self.initialize()
        self.assertEqual(self.menus.owner_view(OWNER_ID,actor_id=OWNER_ID)['revision'],2)
    def test_customer_and_cross_site_cannot_edit(self):
        customer,_=self.customer()
        self.assertEqual(customer.get('/owner/menu').status_code,303)
        self.assertEqual(customer.post('/owner/menu/initialize').status_code,303)
        from menu_admin import MenuNotFound
        with self.assertRaises(MenuNotFound):self.menus.current_menu(OWNER_ID)
        self.initialize()
        self.assertEqual(self.owner.post('/owner/menu/update',data={'revision':1,'item_id':'pkg-pasta-duo'},headers={'Origin':'https://evil.example'}).status_code,403)
    def test_invalid_and_stale_edits(self):
        self.initialize()
        self.assertEqual(self.edit(price='-1').status_code,400)
        self.assertEqual(self.edit().status_code,303)
        self.assertEqual(self.edit().status_code,409)
    def test_new_price_existing_chat_new_quote_saved_snapshot(self):
        self.initialize()
        request=sample_request()
        request.pop("dietary_needs", None)
        saved=self.quotes.service.submit(request,actor_id='customer',owner_id=OWNER_ID)
        def evaluate():return LLMResponse(tool_calls=[ToolCall('q','evaluate_catering_quote',request)])
        chat=Conversation(ScriptedLLM([evaluate(),LLMResponse(content='Draft.'),evaluate(),LLMResponse(content='Draft.')]),self.quotes.context,context_loader=lambda:self.quotes.context)
        old=chat.send('Price please').quote['result']['pricing']['total_cents']
        self.edit()
        new=chat.send('Current price please').quote['result']['pricing']['total_cents']
        self.assertEqual(new-old,4450)
        again=self.quotes.service.submit(request,actor_id='customer',owner_id=OWNER_ID)
        self.assertEqual(again['pricing']['amounts']['total_cents']['cents'],new)
        self.assertEqual(self.quotes.service.detail(saved['quote_id'],actor_id='customer')['pricing'],saved['pricing'])
        with self.assertRaises(QuoteError):
            self.quotes.service.approve(saved['quote_id'],actor_id=OWNER_ID,expected_revision=1,acknowledged_reviews=saved['readiness']['review_reasons'])
        self.assertIn('$14.49',self.client().get('/').text)
    def test_unavailable_hides_public_menu_and_blocks_quote(self):
        self.initialize()
        self.assertEqual(self.edit(available='false').status_code,303)
        self.assertNotIn('The Pasta Duo',self.client().get('/').text)
        with self.assertRaises(QuoteError):self.quotes.service.submit(sample_request(),actor_id='customer',owner_id=OWNER_ID)
    def test_storage_failure_does_not_return_frozen_prices(self):
        self.initialize()
        with mock.patch.object(self.menus,'current_menu',side_effect=MenuStorageUnavailable('offline')):
            self.assertEqual(self.client().get('/').status_code,503)
    def test_item_edit_escaped_and_unknown_item_rejected(self):
        self.initialize()
        data=dict(revision=1,item_id='pkg-pasta-duo',name='<script>bad</script>',description='New description',available='true')
        self.assertEqual(self.owner.post('/owner/menu/update',data=data).status_code,303)
        text=self.owner.get('/owner/menu').text
        self.assertIn('&lt;script&gt;',text)
        self.assertNotIn('<script>bad</script>',text)
        self.assertEqual(self.edit(revision=2,item_id='missing').status_code,400)

    def test_owner_can_explicitly_reprice_pending_quote(self):
        self.initialize()
        saved=self.quotes.service.submit(sample_request(),actor_id='customer',owner_id=OWNER_ID)
        self.edit()
        response=self.owner.post('/quotes/'+saved['quote_id']+'/reprice',data={'revision':1})
        self.assertEqual(response.status_code,303)
        new=self.quotes.service.detail(saved['quote_id'],actor_id=OWNER_ID)
        self.assertEqual(len(new['history']),2)
        self.assertEqual(new['status'],'draft')
        self.assertGreater(new['pricing']['amounts']['total_cents']['cents'],saved['pricing']['amounts']['total_cents']['cents'])
        customer,_=self.customer()
        self.assertEqual(customer.post('/quotes/'+saved['quote_id']+'/reprice',data={'revision':2}).status_code,303)
        self.assertEqual(self.quotes.service.detail(saved['quote_id'],actor_id=OWNER_ID)['revision'],2)
