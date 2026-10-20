"""Offline billing tests with a fake Stripe client; not live Stripe evidence.

Webhook tests use Stripe's real signature check with a locally signed payload.
"""
import hashlib
import hmac
import json
import time
import unittest
from types import SimpleNamespace

import stripe

from billing import BillingConfig, BillingError, create_checkout, handle_webhook, verify_checkout
from billing.stripe_billing import PURPOSE

PRICE = 'price_test_plan'
WEBHOOK_SECRET = 'whsec_test_secret'


def paid_session(**overrides):
    session = {'id': 'cs_test_1', 'url': 'https://checkout.stripe.com/c/pay/cs_test_1',
               'status': 'complete', 'payment_status': 'paid', 'livemode': False,
               'client_reference_id': 'owner-a', 'metadata': {'purpose': PURPOSE},
               'amount_total': 2900, 'currency': 'usd',
               'line_items': {'data': [{'price': {'id': PRICE}}]}}
    session.update(overrides)
    return session


class FakeSession:
    def __init__(self, session):
        self.session = session
        self.created = None
        self.retrieved = None

    def create(self, **params):
        self.created = params
        return {'id': 'cs_test_new', 'url': 'https://checkout.stripe.com/c/pay/cs_test_new'}

    def retrieve(self, session_id, **params):
        self.retrieved = (session_id, params)
        return self.session


def fake_client(session=None):
    sessions = FakeSession(session or paid_session())
    return SimpleNamespace(checkout=SimpleNamespace(Session=sessions), Webhook=stripe.Webhook)


def sign(payload, secret=WEBHOOK_SECRET):
    timestamp = int(time.time())
    digest = hmac.new(secret.encode(), f'{timestamp}.'.encode() + payload,
                      hashlib.sha256).hexdigest()
    return f't={timestamp},v1={digest}'


class ConfigTests(unittest.TestCase):
    def test_rejects_live_or_missing_keys(self):
        for key in ('sk_live_abc', '', 'pk_test_abc'):
            with self.subTest(key=key), self.assertRaises(BillingError):
                BillingConfig(key, PRICE)

    def test_rejects_bad_price(self):
        with self.assertRaises(BillingError):
            BillingConfig('sk_test_abc', 'prod_abc')

    def test_from_env_and_repr_hides_key(self):
        config = BillingConfig.from_env({'STRIPE_SECRET_KEY': 'sk_test_secret123',
                                         'STRIPE_PRICE_ID': PRICE})
        self.assertIsNone(config.webhook_secret)
        self.assertNotIn('secret123', repr(config))


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.config = BillingConfig('sk_test_abc', PRICE, WEBHOOK_SECRET)

    def test_create_uses_server_price_and_owner(self):
        client = fake_client()
        result = create_checkout(self.config, 'owner-a', success_url='https://app/billing/done',
                                 cancel_url='https://app/billing', client=client)
        params = client.checkout.Session.created
        self.assertEqual(result['session_id'], 'cs_test_new')
        self.assertEqual(params['mode'], 'subscription')
        self.assertEqual(params['line_items'], [{'price': PRICE, 'quantity': 1}])
        self.assertEqual(params['client_reference_id'], 'owner-a')
        self.assertEqual(params['metadata']['purpose'], PURPOSE)
        self.assertEqual(params['success_url'],
                         'https://app/billing/done?session_id={CHECKOUT_SESSION_ID}')

    def test_create_requires_owner(self):
        with self.assertRaises(BillingError):
            create_checkout(self.config, ' ', success_url='https://a', cancel_url='https://b',
                            client=fake_client())

    def test_verify_paid(self):
        result = verify_checkout(self.config, 'cs_test_1', owner_id='owner-a',
                                 client=fake_client())
        self.assertTrue(result['paid'])
        self.assertEqual((result['owner_id'], result['amount_total_cents']), ('owner-a', 2900))

    def test_verify_unpaid(self):
        client = fake_client(paid_session(status='open', payment_status='unpaid'))
        self.assertFalse(verify_checkout(self.config, 'cs_test_1', client=client)['paid'])

    def test_verify_rejects_bad_sessions(self):
        cases = {
            'other owner': (paid_session(client_reference_id='owner-b'), 'owner-a'),
            'not our purchase': (paid_session(metadata={}), None),
            'live mode': (paid_session(livemode=True), None),
            'wrong price': (paid_session(line_items={'data': [{'price': {'id': 'price_x'}}]}), None),
            'extra items': (paid_session(line_items={'data': [{'price': {'id': PRICE}}] * 2}), None),
        }
        for name, (session, owner) in cases.items():
            with self.subTest(name), self.assertRaises(BillingError):
                verify_checkout(self.config, 'cs_test_1', owner_id=owner,
                                client=fake_client(session))

    def test_verify_rejects_non_session_id(self):
        with self.assertRaises(BillingError):
            verify_checkout(self.config, 'pi_123', client=fake_client())

    def test_stripe_errors_become_billing_errors(self):
        class Failing:
            def retrieve(self, *args, **kwargs):
                raise stripe.APIConnectionError('network down')
        client = SimpleNamespace(checkout=SimpleNamespace(Session=Failing()))
        with self.assertRaises(BillingError):
            verify_checkout(self.config, 'cs_test_1', client=client)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.config = BillingConfig('sk_test_abc', PRICE, WEBHOOK_SECRET)

    def event(self, kind='checkout.session.completed', session=None):
        return json.dumps({'id': 'evt_1', 'object': 'event', 'type': kind,
                           'data': {'object': session or paid_session()}}).encode()

    def test_signed_completed_event_reverifies_with_stripe(self):
        client = fake_client()
        payload = self.event()
        result = handle_webhook(self.config, payload, sign(payload), client=client)
        self.assertTrue(result['paid'])
        self.assertEqual(client.checkout.Session.retrieved[0], 'cs_test_1')

    def test_bad_signature_rejected(self):
        payload = self.event()
        with self.assertRaises(BillingError):
            handle_webhook(self.config, payload, sign(payload, 'whsec_wrong'),
                           client=fake_client())

    def test_tampered_payload_rejected(self):
        payload = self.event()
        signature = sign(payload)
        with self.assertRaises(BillingError):
            handle_webhook(self.config, payload.replace(b'owner-a', b'owner-b'), signature,
                           client=fake_client())

    def test_ignored_events(self):
        for payload in (self.event('payment_intent.created'),
                        self.event(session=paid_session(metadata={'purpose': 'other'}))):
            with self.subTest(payload=payload[:60]):
                self.assertIsNone(handle_webhook(self.config, payload, sign(payload),
                                                 client=fake_client()))

    def test_requires_webhook_secret(self):
        config = BillingConfig('sk_test_abc', PRICE)
        with self.assertRaises(BillingError):
            handle_webhook(config, b'{}', 't=1,v1=x', client=fake_client())


if __name__ == '__main__':
    unittest.main()
