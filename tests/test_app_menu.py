"""Owner menu page: access, saving, validation, conflicts, and what the change reaches
(new quotes, the home page, the assistant's menu search, and pending drafts via reprice)."""
import html as htmllib
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    TestClient = None

OWNER_ID = '00000000-0000-4000-8000-0000000000aa'
NOW = '2026-10-20T09:00:00-07:00'
PASSWORD = 'correct-horse-9'
REQUEST = {
    'headcount': 40, 'event_at': '2026-10-30T12:00:00-07:00', 'service_mode': 'delivery',
    'address': '9300 Culver Blvd, Culver City, CA', 'allergens': [],
    'selections': [{'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': 40}],
}
DUO_PRICE = 'm:pkg-pasta-duo:pkg-pasta-duo-pp:price'


def form_of(html):
    """Every field the menu page would post, as the browser would send it untouched."""
    fields = {'revision': re.search(r'name="revision" value="(\d+)"', html).group(1)}
    for name, value in re.findall(r'<input[^>]*name="(m:[^"]+)" value="([^"]*)"', html):
        fields[name] = htmllib.unescape(value)
    for name in re.findall(r'<input type="checkbox" name="(m:[^"]+)" value="1" checked', html):
        fields[name] = '1'
    for name, value in re.findall(r'<textarea[^>]*name="(m:[^"]+)"[^>]*>([^<]*)</textarea>', html, re.S):
        fields[name] = htmllib.unescape(value)
    return fields


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class MenuPageTest(unittest.TestCase):
    def setUp(self):
        from ai_service.data_loader import load_context
        from app.auth import MemoryAuth
        from app.config import load_settings
        from app.main import create_app
        from app.quotes import QuoteApp
        from menu_admin import MenuService, SQLiteMenuStore
        from quote_engine.storage import SQLiteQuoteStore

        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name)
        env = {'APP_ENV': 'development', 'APP_DATASET': 'demo', 'OWNER_USER_IDS': OWNER_ID,
               'AUTH_BACKEND': '', 'QUOTE_DATABASE_URL': '', 'LLM_PROVIDER': ''}
        with mock.patch.dict(os.environ, env):
            settings = load_settings()
            self.auth = MemoryAuth()
            self.auth.sign_up('owner@example.com', PASSWORD, user_id=OWNER_ID)
            context = load_context('demo', now=NOW)
            self.quotes = QuoteApp(settings, store=SQLiteQuoteStore(folder / 'q.sqlite3'), context=context)
            self.menus = MenuService(SQLiteMenuStore(folder / 'm.sqlite3'), clock=context.now)
            self.app = create_app(auth_backend=self.auth, quote_app=self.quotes, menu_service=self.menus)

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, email='owner@example.com', signup=False):
        client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        if email:
            response = client.post('/signup' if signup else '/login', data={'email': email, 'password': PASSWORD})
            self.assertEqual(response.status_code, 303, response.text[:200])
        return client

    def save(self, client, **changes):
        html = client.get('/owner/menu').text
        fields = form_of(html)
        for name, value in changes.items():
            if value is None:
                fields.pop(name, None)
            else:
                fields[name] = value
        return client.post('/owner/menu', data=fields)

    # ---- access
    def test_only_the_owner_can_open_the_menu(self):
        self.assertIn('/login', self.client(None).get('/owner/menu').headers['location'])
        customer = self.client('ana@example.com', signup=True)
        self.assertEqual(customer.get('/owner/menu').headers['location'], '/quotes')
        self.assertEqual(customer.post('/owner/menu', data={'revision': '1'}).headers['location'], '/quotes')
        page = self.client().get('/owner/menu')
        self.assertEqual(page.status_code, 200)
        self.assertIn('The Pasta Duo', page.text)
        self.assertIn('href="/owner/menu"', self.client().get('/owner').text)

    def test_first_visit_starts_from_the_standard_menu(self):
        self.assertEqual(self.quotes.menu_source, 'file')
        self.client().get('/owner/menu')
        self.quotes.forget_menu()
        self.quotes.current_menu()
        self.assertEqual(self.quotes.menu_source, 'saved')

    def test_two_first_visits_at_once_do_not_fail(self):
        from menu_admin import MenuNotFound
        real_view = self.menus.owner_view
        calls = {'n': 0}

        def first_missing(*args, **kwargs):  # tab 2 seeded between our read and our seed
            calls['n'] += 1
            if calls['n'] == 1:
                self.menus.seed(OWNER_ID, self.quotes.base_context.menu)
                raise MenuNotFound('menu not found')
            return real_view(*args, **kwargs)
        with mock.patch.object(self.menus, 'owner_view', side_effect=first_missing):
            self.assertEqual(self.client().get('/owner/menu').status_code, 200)

    # ---- saving and what it reaches
    def test_price_change_reaches_new_quotes_and_the_home_page(self):
        owner = self.client()
        response = self.save(owner, **{DUO_PRICE: '15.00'})
        self.assertEqual(response.status_code, 303)
        self.assertIn('Menu saved', owner.get('/owner/menu').text)
        context = self.quotes.current_context().quote_service_context(OWNER_ID, REQUEST)
        duo = next(i for i in context['menu']['items'] if i['id'] == 'pkg-pasta-duo')
        self.assertEqual(duo['variants'][0]['price'], 15.0)
        quote = self.quotes.service.submit(REQUEST, actor_id='cust-1', owner_id=OWNER_ID)
        self.assertEqual(quote['pricing']['lines'][0]['line_total_cents'], 60000)
        self.assertIn('$15.00', self.client(None).get('/').text)
        self.assertIn('price $13.49 → $15.00', owner.get('/owner/menu').text)

    def test_taking_a_dish_off_hides_it_everywhere(self):
        from ai_service.menu_tools import search_menu
        self.save(self.client(), **{'m:app-hummus:available': None})
        self.assertNotIn('Hummus', self.client(None).get('/').text)
        found = search_menu(self.quotes.current_context().menu, {'query': 'hummus'})
        self.assertNotIn('app-hummus', [r.get('item_id', r.get('id')) for r in found.get('items', [])])
        before = search_menu(self.quotes.base_context.menu, {'query': 'hummus'})
        self.assertIn('app-hummus', [r.get('item_id', r.get('id')) for r in before.get('items', [])])  # the check is real
        self.assertIn('taken off the menu', self.client().get('/owner/menu').text)

    def test_invalid_price_shows_next_to_the_field_and_saves_nothing(self):
        owner = self.client()
        response = self.save(owner, **{DUO_PRICE: '-3', 'm:app-hummus:name': 'Hummus Plate'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Price must be greater than 0', response.text)
        self.assertIn('value="-3"', response.text)          # what they typed is still there
        self.assertIn('value="Hummus Plate"', response.text)
        menu = self.menus.current_menu(OWNER_ID)
        self.assertEqual(next(i for i in menu['items'] if i['id'] == 'app-hummus')['name'], 'Hummus')

    def test_saving_without_changes_says_so(self):
        owner = self.client()
        response = self.save(owner)
        self.assertEqual(response.headers['location'], '/owner/menu')
        self.assertIn('Nothing changed', owner.get('/owner/menu').text)

    def test_stale_page_does_not_overwrite_newer_edits(self):
        owner = self.client()
        old_page = owner.get('/owner/menu').text
        self.save(owner, **{DUO_PRICE: '14.00'})
        stale = form_of(old_page)
        stale[DUO_PRICE] = '99.00'
        response = owner.post('/owner/menu', data=stale)
        self.assertEqual(response.status_code, 409)
        self.assertIn('changed in another tab', response.text)
        menu = self.menus.current_menu(OWNER_ID)
        self.assertEqual(next(i for i in menu['items'] if i['id'] == 'pkg-pasta-duo')['variants'][0]['price'], 14.0)

    def test_fixed_fields_cannot_be_sent(self):
        owner = self.client()
        html = owner.get('/owner/menu').text
        fields = form_of(html)
        fields['m:app-hummus:allergens'] = '[]'
        fields['m:app-hummus:app-hummus-small:pricing_unit'] = 'each'
        owner.post('/owner/menu', data=fields)
        item = next(i for i in self.menus.current_menu(OWNER_ID)['items'] if i['id'] == 'app-hummus')
        self.assertIn('sesame', item['allergens'])
        self.assertEqual(item['variants'][0]['pricing_unit'], 'per_tray')

    # ---- pending drafts after a price change
    def test_pending_draft_is_repriced_before_approval(self):
        owner = self.client()
        owner.get('/owner/menu')  # seed
        quote = self.quotes.service.submit(REQUEST, actor_id='cust-1', owner_id=OWNER_ID)
        quote_id = quote['quote_id']
        self.assertNotIn('Menu prices changed', owner.get(f'/quotes/{quote_id}').text)
        self.save(owner, **{DUO_PRICE: '15.00'})
        page = owner.get(f'/quotes/{quote_id}').text
        self.assertIn('Menu prices changed', page)
        self.assertNotIn('Approve quote', page)
        revision = int(re.search(r'name="revision" value="(\d+)"', page).group(1))
        response = owner.post(f'/quotes/{quote_id}/reprice', data={'revision': revision})
        self.assertEqual(response.headers['location'], f'/quotes/{quote_id}')
        page = owner.get(f'/quotes/{quote_id}').text
        self.assertIn('Repriced with today', page)
        self.assertIn('Approve quote', page)
        detail = self.quotes.service.detail(quote_id, actor_id=OWNER_ID)
        self.assertEqual(detail['version'], 2)
        self.assertEqual(detail['pricing']['lines'][0]['line_total_cents'], 60000)

    def test_approving_an_outdated_draft_explains_what_to_do(self):
        owner = self.client()
        owner.get('/owner/menu')
        quote = self.quotes.service.submit(REQUEST, actor_id='cust-1', owner_id=OWNER_ID)
        page = owner.get(f"/quotes/{quote['quote_id']}").text
        revision = int(re.search(r'name="revision" value="(\d+)"', page).group(1))
        acks = re.findall(r'name="ack" value="([^"]+)"', page)
        self.save(owner, **{DUO_PRICE: '15.00'})
        response = owner.post(f"/quotes/{quote['quote_id']}/approve", data={'revision': revision, 'ack': acks})
        self.assertIn('Reprice it with today', owner.get(response.headers['location']).text)

    def test_dish_taken_off_a_waiting_request_tells_the_owner_what_to_do(self):
        owner = self.client()
        owner.get('/owner/menu')
        quote = self.quotes.service.submit(REQUEST, actor_id='cust-1', owner_id=OWNER_ID)
        self.save(owner, **{'m:pkg-pasta-duo:available': None})
        page = owner.get(f"/quotes/{quote['quote_id']}").text
        self.assertIn('The Pasta Duo (Per person) is off the menu', page)
        self.assertIn('href="/owner/menu"', page)
        self.assertNotIn('Approve quote', page)
        self.assertNotIn('Reprice with today', page)
        self.assertIn('class="is-off"', page)  # the receipt line itself is marked
        self.assertIn('<span class="ticket-flag">Off menu</span>', page)
        # putting it back makes the request approvable again
        self.save(owner, **{'m:pkg-pasta-duo:available': '1'})
        back = owner.get(f"/quotes/{quote['quote_id']}").text
        self.assertIn('Approve quote', back)
        self.assertNotIn('ticket-flag', back)

    def test_price_with_thousands_comma_is_accepted(self):
        self.save(self.client(), **{DUO_PRICE: '1,013.49'})
        duo = next(i for i in self.menus.current_menu(OWNER_ID)['items'] if i['id'] == 'pkg-pasta-duo')
        self.assertEqual(duo['variants'][0]['price'], 1013.49)

    def test_dish_switch_names_the_dish_for_screen_readers(self):
        self.assertIn('aria-label="Offer The Pasta Duo"', self.client().get('/owner/menu').text)

    # ---- storage problems
    def test_menu_storage_down_keeps_quoting_from_the_file(self):
        from menu_admin.postgres_storage import MenuStorageUnavailable
        broken = mock.Mock()
        broken.current_menu.side_effect = MenuStorageUnavailable('down')
        broken.owner_view.side_effect = MenuStorageUnavailable('down')
        self.quotes.attach_menus(broken, OWNER_ID)
        self.assertEqual(self.client(None).get('/').status_code, 200)
        self.assertEqual(self.quotes.menu_source, 'unavailable')
        page = self.client().get('/owner/menu')
        self.assertEqual(page.status_code, 503)
        self.assertIn('can’t be loaded right now', page.text)


if __name__ == '__main__':
    unittest.main()
