"""Sign-in, roles and quote screens through the web app (MemoryAuth + SQLite, no network)."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import httpx
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    TestClient = None

OWNER_ID = '00000000-0000-4000-8000-0000000000aa'
NOW = '2026-10-19T12:00:00-07:00'
EVENT = '2026-10-27T12:00:00-07:00'
PASSWORD = 'correct-horse-9'


def notice_of(response):
    for header in response.headers.get_list('set-cookie'):
        if header.startswith('cqa_notice='):
            return header.split(';', 1)[0].split('=', 1)[1]
    return None


def sample_request(**changes):
    request = {
        'headcount': 40, 'event_at': EVENT, 'service_mode': 'delivery',
        'address': '9300 Culver Blvd, Culver City, CA', 'allergens': [], 'dietary_needs': ['vegetarian'],
        'selections': [{'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': 40},
                       {'item_id': 'side-garlic-mashed', 'variant_id': 'side-garlic-mashed-full', 'quantity': 1}],
    }
    request.update(changes)
    return request


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class AccountsAndQuotesTest(unittest.TestCase):
    def setUp(self):
        from ai_service.data_loader import load_context
        from app.auth import MemoryAuth
        from app.config import load_settings
        from app.main import create_app
        from app.quotes import QuoteApp
        from quote_engine.storage import SQLiteQuoteStore

        self.tmp = tempfile.TemporaryDirectory()
        env = {'APP_ENV': 'development', 'APP_DATASET': 'sample', 'OWNER_USER_IDS': OWNER_ID,
               'AUTH_BACKEND': '', 'QUOTE_DATABASE_URL': ''}
        with mock.patch.dict(os.environ, env):
            settings = load_settings()
            self.auth = MemoryAuth()
            self.auth.sign_up('owner@example.com', PASSWORD, user_id=OWNER_ID)
            store = SQLiteQuoteStore(Path(self.tmp.name) / 'quotes.sqlite3')
            self.quotes = QuoteApp(settings, store=store, context=load_context('sample', now=NOW))
            self.app = create_app(auth_backend=self.auth, quote_app=self.quotes)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- helpers ----
    def client(self):
        return TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)

    def signed_in(self, email, password=PASSWORD, signup=False):
        client = self.client()
        response = client.post('/signup' if signup else '/login', data={'email': email, 'password': password})
        self.assertEqual(response.status_code, 303, response.text[:300])
        return client

    def customer(self, email='ana@example.com'):
        client = self.signed_in(email, signup=True)
        user_id = self.auth.sign_in(email, PASSWORD).user_id
        return client, user_id

    def submit_for(self, customer_id, **changes):
        view = self.quotes.service.submit(sample_request(**changes), actor_id=customer_id, owner_id=OWNER_ID)
        return view['quote_id']

    # ---- accounts ----
    def test_signup_sets_http_only_session_and_lands_on_my_quotes(self):
        client = self.client()
        response = client.post('/signup', data={'email': 'Ana@Example.com ', 'password': PASSWORD})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/quotes')
        cookies = response.headers.get_list('set-cookie')
        self.assertTrue(any('cqa_access=' in c and 'HttpOnly' in c and 'SameSite=lax' in c for c in cookies))
        page = client.get('/quotes')
        self.assertEqual(page.status_code, 200)
        self.assertIn('No quote requests yet', page.text)
        self.assertIn('ana@example.com', page.text)

    def test_wrong_password_shows_error_without_signing_in(self):
        self.auth.sign_up('ana@example.com', PASSWORD)
        response = self.client().post('/login', data={'email': 'ana@example.com', 'password': 'nope-nope'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Email or password is incorrect', response.text)
        self.assertNotIn('cqa_access=', response.headers.get('set-cookie', ''))

    def test_duplicate_signup_and_short_password_are_explained(self):
        self.auth.sign_up('ana@example.com', PASSWORD)
        dup = self.client().post('/signup', data={'email': 'ana@example.com', 'password': PASSWORD})
        self.assertIn('already exists', dup.text)
        short = self.client().post('/signup', data={'email': 'new@example.com', 'password': 'short'})
        self.assertIn('at least 8 characters', short.text)

    def test_signup_cannot_claim_owner_role(self):
        client = self.client()
        response = client.post('/signup', data={'email': 'eve@example.com', 'password': PASSWORD,
                                                'role': 'owner', 'user_id': OWNER_ID})
        self.assertEqual(response.headers['location'], '/quotes')
        self.assertEqual(client.get('/owner').headers['location'], '/quotes')

    def test_owner_is_decided_by_server_config(self):
        client = self.signed_in('owner@example.com')
        self.assertEqual(client.get('/quotes').headers['location'], '/owner')
        self.assertIn('Quote inbox', client.get('/owner').text)

    def test_signed_out_visitors_are_sent_to_login_with_return_path(self):
        response = self.client().get('/quotes')
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/login?next=/quotes')

    def test_next_parameter_cannot_redirect_off_site(self):
        self.auth.sign_up('ana@example.com', PASSWORD)
        for evil in ('//evil.example', 'https://evil.example', '/\\evil.example'):
            response = self.client().post('/login', data={'email': 'ana@example.com', 'password': PASSWORD,
                                                          'next': evil})
            self.assertEqual(response.headers['location'], '/quotes', evil)

    def test_expired_access_token_is_refreshed_from_refresh_cookie(self):
        client, _ = self.customer()
        self.auth.expire(client.cookies.get('cqa_access'))
        response = client.get('/quotes')
        self.assertEqual(response.status_code, 200)
        self.assertIn('cqa_access=', response.headers.get('set-cookie', ''))

    def test_static_and_health_requests_keep_the_session(self):
        client, _ = self.customer()
        for path in ('/static/css/app.css', '/static/img/favicon.svg', '/healthz'):
            response = client.get(path)
            self.assertNotIn('cqa_access', response.headers.get('set-cookie', ''), path)
        self.assertEqual(client.get('/quotes').status_code, 200)

    def test_stale_cookies_are_cleared_on_pages(self):
        client = self.client()
        client.cookies.set('cqa_access', 'forged')
        response = client.get('/')
        self.assertIn('cqa_access=""', response.headers.get('set-cookie', ''))

    def test_logout_clears_session(self):
        client, _ = self.customer()
        response = client.post('/logout')
        self.assertEqual(response.headers['location'], '/')
        self.assertEqual(notice_of(response), 'signed-out')
        self.assertIn('cqa_access=""', response.headers.get('set-cookie', ''))
        self.assertEqual(client.get('/quotes').status_code, 303)

    def test_cross_site_form_posts_are_rejected(self):
        client, _ = self.customer()
        response = client.post('/logout', headers={'origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)

    def test_auth_outage_shows_retry_page_not_a_crash(self):
        from app.auth import AuthUnavailable
        client, _ = self.customer()
        with mock.patch.object(self.auth, 'verify', side_effect=AuthUnavailable('down')):
            from app.main import create_app
            fresh = TestClient(create_app(auth_backend=self.auth, quote_app=self.quotes),
                               raise_server_exceptions=False, follow_redirects=False)
            fresh.cookies.update(client.cookies)
            response = fresh.get('/quotes')
        self.assertEqual(response.status_code, 503)

    # ---- quotes ----
    def test_full_journey_submit_review_approve_accept(self):
        ana, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        owner = self.signed_in('owner@example.com')

        inbox = owner.get('/owner').text
        self.assertIn('$749.04', inbox)
        self.assertIn('Needs your review', inbox)

        detail = owner.get(f'/quotes/{quote_id}').text
        self.assertIn('Review and approve', detail)
        self.assertIn('Allergens depend on the choices for The Pasta Duo', detail)
        acks = re.findall(r'name="ack" value="([^"]+)"', detail)
        self.assertTrue(acks)

        # Approving without ticking every review item is refused.
        partial = owner.post(f'/quotes/{quote_id}/approve', data={'revision': 1, 'ack': acks[:1]})
        self.assertEqual(notice_of(partial), 'acknowledge')

        approved = owner.post(f'/quotes/{quote_id}/approve', data={'revision': 1, 'ack': acks})
        self.assertEqual(approved.headers['location'], f'/quotes/{quote_id}')
        self.assertEqual(notice_of(approved), 'approved')

        customer_view = ana.get(f'/quotes/{quote_id}').text
        self.assertIn('Accept quote', customer_view)
        accepted = ana.post(f'/quotes/{quote_id}/respond', data={'revision': 2, 'decision': 'accept'})
        self.assertEqual(notice_of(accepted), 'accepted')
        self.assertIn('You accepted this quote', ana.get(accepted.headers['location']).text)

        after = owner.get('/owner').text
        self.assertIn('Approved and answered', after)
        self.assertIn('Accepted', after)
        # Persisted across a brand-new app instance (restart) and a fresh sign-in.
        from app.main import create_app
        restarted = TestClient(create_app(auth_backend=self.auth, quote_app=self.quotes), follow_redirects=False)
        restarted.post('/login', data={'email': 'ana@example.com', 'password': PASSWORD})
        self.assertIn('Accepted', restarted.get('/quotes').text)

    def test_other_customers_cannot_see_or_answer_a_quote(self):
        _, ana_id = self.customer('ana@example.com')
        quote_id = self.submit_for(ana_id)
        bob, _ = self.customer('bob@example.com')
        self.assertEqual(bob.get(f'/quotes/{quote_id}').status_code, 404)
        self.assertEqual(bob.post(f'/quotes/{quote_id}/respond', data={'revision': 1, 'decision': 'accept'}).status_code, 404)
        self.assertNotIn(quote_id, bob.get('/quotes').text)

    def test_customer_cannot_approve_own_quote(self):
        ana, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        response = ana.post(f'/quotes/{quote_id}/approve', data={'revision': 1, 'ack': ['owner_confirmation_required']})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/quotes')
        self.assertEqual(self.quotes.service.detail(quote_id, actor_id=ana_id)['status'], 'draft')

    def test_customer_cannot_accept_before_owner_approval(self):
        ana, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        self.assertNotIn('Accept quote', ana.get(f'/quotes/{quote_id}').text)
        response = ana.post(f'/quotes/{quote_id}/respond', data={'revision': 1, 'decision': 'accept'})
        self.assertEqual(notice_of(response), 'failed')
        self.assertEqual(self.quotes.service.detail(quote_id, actor_id=ana_id)['status'], 'draft')

    def test_stale_revision_asks_to_review_latest(self):
        _, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        owner = self.signed_in('owner@example.com')
        acks = re.findall(r'name="ack" value="([^"]+)"', owner.get(f'/quotes/{quote_id}').text)
        owner.post(f'/quotes/{quote_id}/approve', data={'revision': 1, 'ack': acks})
        again = owner.post(f'/quotes/{quote_id}/approve', data={'revision': 1, 'ack': acks})
        self.assertEqual(notice_of(again), 'conflict')
        self.assertIn('changed while you were viewing', owner.get(again.headers['location']).text)
        # One-shot: the message does not reappear on the next load.
        self.assertNotIn('changed while you were viewing', owner.get(again.headers['location']).text)

    def test_invalid_decision_and_bad_ids_are_rejected_cleanly(self):
        ana, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        self.assertEqual(ana.post(f'/quotes/{quote_id}/respond', data={'revision': 1, 'decision': 'approve'}).status_code, 400)
        self.assertEqual(ana.post(f'/quotes/{quote_id}/respond', data={'decision': 'accept'}).status_code, 400)
        self.assertEqual(ana.get('/quotes/not-a-real-id').status_code, 404)
        self.assertEqual(ana.get("/quotes/' OR 1=1 --").status_code, 404)

    def test_logout_with_only_refresh_cookie_really_signs_out(self):
        client, _ = self.customer()
        old_refresh = client.cookies.get('cqa_refresh')
        client.cookies.delete('cqa_access')
        response = client.post('/logout')
        cookies = response.headers.get_list('set-cookie')
        self.assertFalse(any(c.startswith('cqa_access=') and 'Max-Age=0' not in c for c in cookies), cookies)
        self.assertEqual(client.get('/quotes').status_code, 303)
        # The old refresh token was revoked server-side too.
        replay = self.client()
        replay.cookies.set('cqa_refresh', old_refresh)
        self.assertEqual(replay.get('/quotes').status_code, 303)

    def test_refresh_token_is_revoked_after_normal_logout(self):
        client, _ = self.customer()
        old_refresh = client.cookies.get('cqa_refresh')
        client.post('/logout')
        replay = self.client()
        replay.cookies.set('cqa_refresh', old_refresh)
        self.assertEqual(replay.get('/quotes').status_code, 303)

    def test_rate_limited_refresh_keeps_the_session_and_shows_retry(self):
        from app.auth import AuthUnavailable
        client, _ = self.customer()
        self.auth.expire(client.cookies.get('cqa_access'))
        with mock.patch.object(self.auth, 'refresh', side_effect=AuthUnavailable('429')):
            response = client.get('/quotes')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('cqa_refresh=""', response.headers.get('set-cookie', ''))

    def test_post_after_session_expiry_returns_to_the_quote_page(self):
        _, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        response = self.client().post(f'/quotes/{quote_id}/respond', data={'revision': 1, 'decision': 'accept'})
        self.assertEqual(response.headers['location'], f'/login?next=/quotes/{quote_id}')

    def test_notice_cannot_be_spoofed_through_the_url(self):
        ana, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        self.assertNotIn('You accepted this quote', ana.get(f'/quotes/{quote_id}?notice=accepted').text)

    def test_quote_ids_are_case_insensitive(self):
        ana, ana_id = self.customer()
        quote_id = self.submit_for(ana_id)
        self.assertEqual(ana.get(f'/quotes/{quote_id.upper()}').status_code, 200)

    def test_cross_scheme_origin_is_rejected(self):
        client, _ = self.customer()
        self.assertEqual(client.post('/logout', headers={'origin': 'https://testserver'}).status_code, 403)

    def test_pages_are_not_cached_when_signed_in(self):
        ana, _ = self.customer()
        self.assertEqual(ana.get('/quotes').headers.get('cache-control'), 'no-store')


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class FullDatasetAndProductionTest(unittest.TestCase):
    def test_quote_screens_never_show_provenance_names_on_full_dataset(self):
        from ai_service.data_loader import load_context
        from app.auth import MemoryAuth
        from app.config import Settings
        from app.main import create_app
        from app.quotes import QuoteApp
        from quote_engine.storage import SQLiteQuoteStore
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {
                'APP_ENV': 'development', 'APP_DATASET': 'full', 'OWNER_USER_IDS': OWNER_ID, 'AUTH_BACKEND': ''}):
            auth = MemoryAuth()
            auth.sign_up('owner@example.com', PASSWORD, user_id=OWNER_ID)
            quotes = QuoteApp(Settings(env='development', dataset='full'),
                              store=SQLiteQuoteStore(Path(folder) / 'q.sqlite3'),
                              context=load_context('full', now=NOW))
            app = create_app(auth_backend=auth, quote_app=quotes)
            customer = auth.sign_up('ana@example.com', PASSWORD).user_id
            menu = {i['id']: i for i in quotes.context.menu['items']}
            picks = [i for i in menu.values() if re.search('SFG|Stonefire', i['name'])][:2]
            selections = [{'item_id': i['id'], 'variant_id': i['variants'][0]['id'],
                           'quantity': 40 if i['variants'][0]['pricing_unit'] == 'per_person' else 1} for i in picks]
            view = quotes.service.submit(sample_request(selections=selections), actor_id=customer, owner_id=OWNER_ID)
            client = TestClient(app, follow_redirects=False)
            client.post('/login', data={'email': 'owner@example.com', 'password': PASSWORD})
            html = client.get(f"/quotes/{view['quote_id']}").text
        self.assertTrue(picks)
        self.assertNotRegex(html, r'Stonefire|\bSFG\b')

    def test_production_without_database_shows_unavailable_not_crash(self):
        from app.auth import MemoryAuth
        from app.config import load_settings
        from app.main import create_app
        from app.quotes import QuoteApp
        env = {'APP_ENV': 'production', 'APP_DATASET': 'sample', 'QUOTE_DATABASE_URL': '', 'AUTH_BACKEND': '',
               'OWNER_USER_IDS': OWNER_ID}
        with mock.patch.dict(os.environ, env):
            auth = MemoryAuth()
            auth.sign_up('ana@example.com', PASSWORD)
            app = create_app(auth_backend=auth, quote_app=QuoteApp(load_settings()))
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False, base_url='https://testserver')
        client.post('/login', data={'email': 'ana@example.com', 'password': PASSWORD},
                    headers={'origin': 'https://testserver'})
        self.assertEqual(client.get('/quotes').status_code, 503)
        self.assertEqual(client.get('/quotes/00000000-0000-4000-8000-000000000001').status_code, 503)
        self.assertEqual(client.get('/').status_code, 200)
        # In production a form post must carry Origin or Referer.
        self.assertEqual(client.post('/logout').status_code, 403)


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class SupabaseAuthClientTest(unittest.TestCase):
    """The Supabase client against a fake HTTP server (no network)."""

    def make(self, handler):
        from app.auth import SupabaseAuth
        transport = httpx.MockTransport(handler)
        return SupabaseAuth('https://demo.supabase.co', 'sb_publishable_test', client=httpx.Client(transport=transport))

    @staticmethod
    def session_body(user_id='u-1'):
        return {'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600,
                'user': {'id': user_id, 'email': 'ana@example.com'}}

    def test_sign_in_sends_publishable_key_and_parses_session(self):
        seen = {}

        def handler(request):
            seen['url'], seen['apikey'] = str(request.url), request.headers.get('apikey')
            seen['body'] = json.loads(request.content)
            return httpx.Response(200, json=self.session_body())
        session = self.make(handler).sign_in('Ana@Example.com', PASSWORD)
        self.assertEqual(seen['url'], 'https://demo.supabase.co/auth/v1/token?grant_type=password')
        self.assertEqual(seen['apikey'], 'sb_publishable_test')
        self.assertEqual(seen['body']['email'], 'ana@example.com')
        self.assertEqual((session.user_id, session.access_token), ('u-1', 'at'))

    def test_wrong_credentials_and_existing_account_messages(self):
        from app.auth import AuthError
        bad = self.make(lambda r: httpx.Response(400, json={'error_code': 'invalid_credentials'}))
        with self.assertRaisesRegex(AuthError, 'incorrect'):
            bad.sign_in('ana@example.com', 'x')
        taken = self.make(lambda r: httpx.Response(422, json={'error_code': 'user_already_exists'}))
        with self.assertRaisesRegex(AuthError, 'already exists'):
            taken.sign_up('ana@example.com', PASSWORD)

    def test_signup_with_email_confirmation_on_explains_next_step(self):
        from app.auth import AuthError
        auth = self.make(lambda r: httpx.Response(200, json={'id': 'u-1', 'email': 'ana@example.com'}))
        with self.assertRaisesRegex(AuthError, 'confirm your email'):
            auth.sign_up('ana@example.com', PASSWORD)

    def test_verify_uses_bearer_token_and_rejects_invalid(self):
        def handler(request):
            if request.headers.get('authorization') == 'Bearer good':
                return httpx.Response(200, json={'id': 'u-1', 'email': 'ana@example.com'})
            return httpx.Response(401, json={'msg': 'invalid JWT'})
        auth = self.make(handler)
        self.assertEqual(auth.verify('good'), ('u-1', 'ana@example.com'))
        self.assertIsNone(auth.verify('forged'))

    def test_rate_limit_on_refresh_is_unavailable_not_signed_out(self):
        from app.auth import AuthUnavailable
        limited = self.make(lambda r: httpx.Response(429, json={'error_code': 'over_request_rate_limit'}))
        with self.assertRaises(AuthUnavailable):
            limited.refresh('rt')
        rejected = self.make(lambda r: httpx.Response(400, json={'error_code': 'refresh_token_not_found'}))
        self.assertIsNone(rejected.refresh('rt'))

    def test_outages_raise_unavailable(self):
        from app.auth import AuthUnavailable
        down = self.make(lambda r: httpx.Response(503))
        with self.assertRaises(AuthUnavailable):
            down.verify('t')

        def boom(request):
            raise httpx.ConnectError('no route')
        with self.assertRaises(AuthUnavailable):
            self.make(boom).sign_in('ana@example.com', PASSWORD)


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class ConfigTest(unittest.TestCase):
    def test_memory_auth_is_refused_in_production(self):
        from app.config import load_settings
        with mock.patch.dict(os.environ, {'APP_ENV': 'production', 'AUTH_BACKEND': 'memory'}):
            with self.assertRaises(ValueError):
                load_settings()

    def test_supabase_backend_selected_when_configured(self):
        from app.config import load_settings
        env = {'SUPABASE_URL': 'https://x.supabase.co/', 'SUPABASE_PUBLISHABLE_KEY': 'k',
               'OWNER_USER_IDS': ' A-1 , b-2 ', 'AUTH_BACKEND': ''}
        with mock.patch.dict(os.environ, env):
            settings = load_settings()
        self.assertEqual(settings.auth_backend, 'supabase')
        self.assertEqual(settings.supabase_url, 'https://x.supabase.co')
        self.assertEqual(settings.owner_ids, ('a-1', 'b-2'))
        self.assertEqual(settings.business_owner_id, 'a-1')

    def test_postgres_store_used_when_database_url_set(self):
        from app.config import Settings
        from app.quotes import QuoteApp
        from quote_engine.postgres_storage import PostgresQuoteStore
        app = QuoteApp(Settings(env='production', dataset='sample', database_url='postgresql://u@h/db'))
        self.assertIsInstance(app.service.store, PostgresQuoteStore)


if __name__ == '__main__':
    unittest.main()
