"""Web app tests. Skipped when the web dependencies are missing (pip install -r requirements-dev.txt)."""
import os
import re
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # RuntimeError: Starlette's TestClient without httpx
    TestClient = None

PROVENANCE = re.compile(r'Stonefire|\bSFG\b')


def make_client(**env):
    from app import catalog
    from app.main import create_app
    with mock.patch.dict(os.environ, env):
        app = create_app()
    catalog.business.cache_clear()
    return TestClient(app, raise_server_exceptions=False)


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class AppPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = make_client(APP_DATASET='sample', APP_ENV='development')

    def test_health_check(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_head_requests_succeed_for_uptime_checks(self):
        for path in ('/', '/healthz', '/login'):
            self.assertEqual(self.client.head(path).status_code, 200, path)

    def test_home_shows_business_and_engine_priced_example(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('Sample Catering Co.', html)
        # Total comes from quote_engine.calculate_quote on the fixture's pricing example.
        self.assertIn('$749.04', html)
        self.assertIn('The Pasta Duo', html)
        self.assertIn('Awaiting', html)
        self.assertIn('Torrance, CA', html)
        self.assertNotRegex(html, PROVENANCE)

    def test_home_lists_menu_with_prices(self):
        html = self.client.get('/').text
        self.assertIn('Hummus', html)
        self.assertIn('from $25.00', html)
        self.assertIn('Gluten-sensitive', html)

    def test_home_lists_every_dish_the_assistant_can_quote(self):
        import html as html_lib
        from app import catalog
        client = make_client(APP_DATASET='demo', APP_ENV='development')
        page = html_lib.unescape(client.get('/').text)
        items = [i for i in catalog.business('demo')['menu']['items'] if i.get('available', True) is True]
        self.assertGreater(len(items), 8)
        for item in items:
            self.assertIn(item['name'], page)
        # The first eight are featured; the rest sit behind the show-more button.
        self.assertEqual(page.count('class="menu-item menu-extra"'), len(items) - 8)
        self.assertIn(f'Show the full menu ({len(items) - 8} more dishes)', page)

    def test_home_does_not_link_to_inactive_sign_in_as_a_quote_action(self):
        html = self.client.get('/').text
        self.assertNotIn('Start a quote request</a>', html)
        self.assertIn('Online quote requests are coming soon', html)

    def test_login_page_renders_inactive_form(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Sign in', response.text)
        self.assertIn('disabled', response.text)

    def test_unknown_page_uses_branded_404(self):
        response = self.client.get('/no-such-page')
        self.assertEqual(response.status_code, 404)
        self.assertIn('isn’t on the menu', response.text)
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')

    def test_wrong_method_keeps_allow_header(self):
        response = self.client.post('/')
        self.assertEqual(response.status_code, 405)
        self.assertIn('GET', response.headers.get('allow', ''))

    def test_security_headers_present(self):
        response = self.client.get('/')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(response.headers['x-frame-options'], 'DENY')

    def test_static_assets_served(self):
        self.assertEqual(self.client.get('/static/css/app.css').status_code, 200)
        self.assertEqual(self.client.get('/static/img/favicon.svg').status_code, 200)


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class AppErrorAndConfigTest(unittest.TestCase):
    def test_unhandled_error_is_branded_with_headers_and_no_details(self):
        from app import catalog
        client = make_client(APP_DATASET='sample')
        with mock.patch.object(catalog, 'menu_highlights', side_effect=RuntimeError('secret detail')):
            response = client.get('/')
        self.assertEqual(response.status_code, 500)
        self.assertIn('Something went wrong', response.text)
        self.assertNotIn('secret detail', response.text)
        self.assertEqual(response.headers.get('x-frame-options'), 'DENY')

    def test_error_page_renders_when_business_data_is_unavailable(self):
        from app import catalog
        client = make_client(APP_DATASET='sample')
        with mock.patch.object(catalog, 'business', side_effect=FileNotFoundError('menu.json')):
            response = client.get('/no-such-page')
        self.assertEqual(response.status_code, 404)
        self.assertIn('isn’t on the menu', response.text)

    def test_production_hides_api_docs(self):
        client = make_client(APP_ENV='production')
        self.assertEqual(client.get('/docs').status_code, 404)
        self.assertEqual(client.get('/openapi.json').status_code, 404)

    def test_full_dataset_never_shows_provenance_names(self):
        from app import catalog
        client = make_client(APP_DATASET='full')
        self.assertNotRegex(client.get('/').text, PROVENANCE)
        for item in catalog.menu_highlights('full', limit=1000):
            self.assertNotRegex(item['name'] + ' ' + item['description'], PROVENANCE)


if __name__ == '__main__':
    unittest.main()
