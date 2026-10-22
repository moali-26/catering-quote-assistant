"""Quote Kitchen Subscription Plan in the web app: Stripe test checkout, confirmation, webhook (no network).

A fake Stripe client stands in for checkout.Session create/retrieve; webhook tests use
Stripe's real signature verification with a locally signed payload.
"""
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import httpx  # noqa: F401
    import stripe
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    TestClient = None

OWNER_ID = '00000000-0000-4000-8000-0000000000aa'
NOW = '2026-10-19T12:00:00-07:00'
PASSWORD = 'correct-horse-9'
PRICE = 'price_test_plan'
WEBHOOK_SECRET = 'whsec_test_secret'
STRIPE_URL = 'https://checkout.stripe.com/c/pay/cs_test_new'


def notice_of(response):
    for header in response.headers.get_list('set-cookie'):
        if header.startswith('cqa_notice='):
            return header.split(';', 1)[0].split('=', 1)[1]
    return None


def paid_session(**overrides):
    from billing.stripe_billing import PURPOSE
    session = {'id': 'cs_test_1', 'url': STRIPE_URL, 'status': 'complete', 'payment_status': 'paid',
               'livemode': False, 'client_reference_id': OWNER_ID,
               'metadata': {'purpose': PURPOSE, 'owner_id': OWNER_ID},
               'amount_total': 2900, 'currency': 'usd', 'line_items': {'data': [{'price': {'id': PRICE}}]}}
    session.update(overrides)
    return session


class FakeSessions:
    def __init__(self, session):
        self.session, self.created = session, None

    def create(self, **params):
        self.created = params
        return {'id': 'cs_test_new', 'url': STRIPE_URL}

    def retrieve(self, session_id, **params):
        return self.session


def sign(payload, secret=WEBHOOK_SECRET):
    stamp = int(time.time())
    digest = hmac.new(secret.encode(), f'{stamp}.'.encode() + payload, hashlib.sha256).hexdigest()
    return f't={stamp},v1={digest}'


def webhook_payload(session_id='cs_test_1'):
    from billing.stripe_billing import PURPOSE
    return json.dumps({'id': 'evt_test_1', 'object': 'event', 'type': 'checkout.session.completed',
                       'data': {'object': {'id': session_id, 'object': 'checkout.session',
                                           'metadata': {'purpose': PURPOSE}}}}).encode()


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class OwnerBillingAppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sessions = FakeSessions(paid_session())
        self.app = self.make_app()

    def make_app(self, *, env='development', configured=True):
        from ai_service.data_loader import load_context
        from app.auth import MemoryAuth
        from app.billing_app import BillingApp, SQLiteBillingStore
        from app.config import load_settings
        from app.main import create_app
        from app.quotes import QuoteApp
        from billing import BillingConfig
        from quote_engine.storage import SQLiteQuoteStore

        folder = Path(self.tmp.name)
        environ = {'APP_ENV': env, 'APP_DATASET': 'sample', 'OWNER_USER_IDS': OWNER_ID,
                   'AUTH_BACKEND': '', 'QUOTE_DATABASE_URL': ''}
        with mock.patch.dict(os.environ, environ):
            settings = load_settings()
            self.auth = MemoryAuth()
            self.auth.sign_up('owner@example.com', PASSWORD, user_id=OWNER_ID)
            quotes = QuoteApp(settings, store=SQLiteQuoteStore(folder / f'quotes-{env}.sqlite3'),
                              context=load_context('sample', now=NOW))
            config = BillingConfig(secret_key='sk_test_fake', price_id=PRICE,
                                   webhook_secret=WEBHOOK_SECRET) if configured else None
            client = SimpleNamespace(checkout=SimpleNamespace(Session=self.sessions), Webhook=stripe.Webhook)
            self.store = SQLiteBillingStore(folder / 'billing.sqlite3')
            self.billing = BillingApp(config, self.store, owner_ids=(OWNER_ID,), client=client)
            return create_app(auth_backend=self.auth, quote_app=quotes, billing_app=self.billing)

    def client(self, app=None):
        return TestClient(app or self.app, raise_server_exceptions=False, follow_redirects=False)

    def signed_in(self, email, signup=False, app=None):
        client = self.client(app)
        response = client.post('/signup' if signup else '/login', data={'email': email, 'password': PASSWORD})
        self.assertEqual(response.status_code, 303, response.text[:300])
        return client

    def owner(self):
        return self.signed_in('owner@example.com')

    # ---- access ----
    def test_customers_cannot_open_or_start_billing(self):
        customer = self.signed_in('ana@example.com', signup=True)
        self.assertEqual(customer.get('/owner/billing').headers['location'], '/quotes')
        self.assertEqual(customer.post('/owner/billing/checkout').headers['location'], '/quotes')
        self.assertEqual(customer.get('/owner/billing/success?session_id=cs_test_1').headers['location'], '/quotes')
        self.assertIsNone(self.sessions.created)
        self.assertIsNone(self.store.get(OWNER_ID))

    def test_signed_out_is_sent_to_login(self):
        self.assertTrue(self.client().get('/owner/billing').headers['location'].startswith('/login'))

    # ---- checkout ----
    def test_owner_starts_test_mode_checkout(self):
        owner = self.owner()
        page = owner.get('/owner/billing')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Not subscribed yet', page.text)
        self.assertIn('4242 4242 4242 4242', page.text)
        response = owner.post('/owner/billing/checkout')
        self.assertEqual((response.status_code, response.headers['location']), (303, STRIPE_URL))
        created = self.sessions.created
        self.assertEqual(created['client_reference_id'], OWNER_ID)  # from the session, not a form field
        self.assertEqual(created['line_items'], [{'price': PRICE, 'quantity': 1}])
        self.assertTrue(created['success_url'].startswith('http://testserver/owner/billing/success'))
        self.assertIn('{CHECKOUT_SESSION_ID}', created['success_url'])
        self.assertTrue(created['cancel_url'].endswith('/owner/billing?canceled=1'))
        self.assertIsNone(self.store.get(OWNER_ID))  # starting checkout is not payment

    def test_success_page_asks_stripe_then_records_payment(self):
        owner = self.owner()
        response = owner.get('/owner/billing/success?session_id=cs_test_1')
        self.assertEqual((response.headers['location'], notice_of(response)), ('/owner/billing', 'billing-paid'))
        plan = self.store.get(OWNER_ID)
        self.assertTrue(plan['paid'])
        self.assertEqual(plan['amount_total_cents'], 2900)
        self.assertIn('Plan active', owner.get('/owner/billing').text)
        self.assertIn('Quote Kitchen Subscription Plan · Active', owner.get('/owner').text)

    def test_unpaid_session_is_pending_not_paid(self):
        self.sessions.session = paid_session(payment_status='unpaid', status='open')
        response = self.owner().get('/owner/billing/success?session_id=cs_test_1')
        self.assertEqual(notice_of(response), 'billing-pending')
        self.assertIsNone(self.store.get(OWNER_ID))

    def test_someone_elses_session_is_refused(self):
        self.sessions.session = paid_session(client_reference_id='11111111-1111-4111-8111-111111111111')
        response = self.owner().get('/owner/billing/success?session_id=cs_test_1')
        self.assertEqual(notice_of(response), 'billing-failed')
        self.assertIsNone(self.store.get(OWNER_ID))

    def test_visiting_success_url_without_a_real_session_proves_nothing(self):
        for session_id in ('', 'paid', 'cs_live_x"><script>'):
            response = self.owner().get('/owner/billing/success', params={'session_id': session_id})
            self.assertIn(notice_of(response), ('billing-failed', 'billing-pending'))
        self.sessions.session = paid_session(metadata={'purpose': 'something_else'})
        self.assertEqual(notice_of(self.owner().get('/owner/billing/success?session_id=cs_test_1')), 'billing-failed')
        self.assertIsNone(self.store.get(OWNER_ID))

    def test_no_second_checkout_once_paid(self):
        owner = self.owner()
        owner.get('/owner/billing/success?session_id=cs_test_1')
        response = owner.post('/owner/billing/checkout')
        self.assertEqual(response.headers['location'], '/owner/billing')
        self.assertIsNone(self.sessions.created)

    def test_cancel_shows_notice(self):
        self.assertIn('Checkout canceled', self.owner().get('/owner/billing?canceled=1').text)

    # ---- webhook ----
    def test_webhook_records_payment_and_works_without_origin_in_production(self):
        app = self.make_app(env='production')
        payload = webhook_payload()
        response = self.client(app).post('/stripe/webhook', content=payload,
                                         headers={'stripe-signature': sign(payload),
                                                  'content-type': 'application/json'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.store.get(OWNER_ID)['paid'])
        # The exemption is narrow: other posts without Origin/Referer are still refused in production.
        self.assertEqual(self.client(app).post('/owner/billing/checkout').status_code, 403)

    def test_webhook_rejects_bad_signature(self):
        payload = webhook_payload()
        response = self.client().post('/stripe/webhook', content=payload,
                                      headers={'stripe-signature': sign(payload, 'whsec_wrong')})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.store.get(OWNER_ID))

    def test_webhook_ignores_payment_for_unknown_account(self):
        self.sessions.session = paid_session(client_reference_id='22222222-2222-4222-8222-222222222222')
        payload = webhook_payload()
        response = self.client().post('/stripe/webhook', content=payload, headers={'stripe-signature': sign(payload)})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.store.get(OWNER_ID))

    def test_webhook_and_success_page_together_record_once(self):
        payload = webhook_payload()
        self.client().post('/stripe/webhook', content=payload, headers={'stripe-signature': sign(payload)})
        first = self.store.get(OWNER_ID)
        self.sessions.session = paid_session(id='cs_test_2')
        self.owner().get('/owner/billing/success?session_id=cs_test_2')
        self.assertEqual(self.store.get(OWNER_ID)['session_id'], first['session_id'])

    # ---- not configured ----
    def test_unconfigured_billing_says_so_and_never_calls_stripe(self):
        app = self.make_app(configured=False)
        owner = self.signed_in('owner@example.com', app=app)
        self.assertIn('isn’t set up yet', owner.get('/owner/billing').text)
        self.assertEqual(notice_of(owner.post('/owner/billing/checkout')), 'billing-off')
        payload = webhook_payload()
        self.assertEqual(self.client(app).post('/stripe/webhook', content=payload,
                                               headers={'stripe-signature': sign(payload)}).status_code, 503)
        self.assertIsNone(self.sessions.created)


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class BuildBillingTest(unittest.TestCase):
    def settings(self):
        from app.config import load_settings
        with mock.patch.dict(os.environ, {'APP_ENV': 'development', 'APP_DATASET': 'sample',
                                          'QUOTE_DATABASE_URL': '', 'AUTH_BACKEND': ''}):
            return load_settings()

    def test_live_keys_are_refused_without_crashing(self):
        from app.billing_app import build_billing
        with self.assertLogs('app.billing', level='WARNING'):
            billing = build_billing(self.settings(), (OWNER_ID,),
                                    env={'STRIPE_SECRET_KEY': 'sk_live_real', 'STRIPE_PRICE_ID': 'price_x'})
        self.assertFalse(billing.configured)

    def test_test_keys_enable_checkout(self):
        from app.billing_app import build_billing
        billing = build_billing(self.settings(), (OWNER_ID,),
                                env={'STRIPE_SECRET_KEY': 'sk_test_x', 'STRIPE_PRICE_ID': 'price_x'})
        self.assertTrue(billing.configured)
        self.assertFalse(billing.webhook_ready)  # no STRIPE_WEBHOOK_SECRET yet
        self.assertNotIn('sk_test_x', repr(billing.config))


if __name__ == '__main__':
    unittest.main()
