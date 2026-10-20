"""Owner software purchase through Stripe Checkout, test mode only.

This is the owner buying the app, not a customer paying for food. Quote
acceptance never charges money.

Trust rules:
- owner_id must come from the verified Supabase Auth user on the server,
  never from a browser field.
- "Paid" is trusted only after asking Stripe (verify_checkout) or receiving a
  signed webhook (handle_webhook). A redirect to the success URL proves nothing.
- Only sandbox keys (sk_test_/rk_test_) are accepted.
"""
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import stripe

PURPOSE = 'owner_software_plan'
PAID_EVENTS = ('checkout.session.completed', 'checkout.session.async_payment_succeeded')


class BillingError(Exception):
    """Billing request rejected or Stripe unavailable; safe to show a generic message."""


@dataclass(frozen=True)
class BillingConfig:
    secret_key: str
    price_id: str
    webhook_secret: Optional[str] = None

    def __post_init__(self):
        if not str(self.secret_key).startswith(('sk_test_', 'rk_test_')):
            raise BillingError('STRIPE_SECRET_KEY must be a sandbox/test key (sk_test_...)')
        if not str(self.price_id).startswith('price_'):
            raise BillingError('STRIPE_PRICE_ID must be a Stripe price ID (price_...)')

    def __repr__(self):  # keep keys out of logs and tracebacks
        return f'BillingConfig(price_id={self.price_id!r})'

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(secret_key=env.get('STRIPE_SECRET_KEY', ''),
                   price_id=env.get('STRIPE_PRICE_ID', ''),
                   webhook_secret=env.get('STRIPE_WEBHOOK_SECRET') or None)


def _owner(owner_id):
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise BillingError('owner_id is required')
    return owner_id


def create_checkout(config: BillingConfig, owner_id: str, *, success_url: str,
                    cancel_url: str, client=stripe) -> Dict[str, str]:
    """Start a Stripe Checkout for the owner's software plan.

    Returns {'session_id', 'url'}; send the owner's browser to url. Stripe fills
    {CHECKOUT_SESSION_ID} in success_url so the success page can call verify_checkout.
    """
    owner_id = _owner(owner_id)
    if '{CHECKOUT_SESSION_ID}' not in success_url:
        joiner = '&' if '?' in success_url else '?'
        success_url = f'{success_url}{joiner}session_id={{CHECKOUT_SESSION_ID}}'
    try:
        session = client.checkout.Session.create(
            api_key=config.secret_key,
            mode='subscription',
            line_items=[{'price': config.price_id, 'quantity': 1}],
            client_reference_id=owner_id,
            metadata={'purpose': PURPOSE, 'owner_id': owner_id},
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except stripe.StripeError as exc:
        raise BillingError('could not start checkout') from exc
    return {'session_id': session['id'], 'url': session['url']}


def verify_checkout(config: BillingConfig, session_id: str, *, owner_id: Optional[str] = None,
                    client=stripe) -> Dict[str, Any]:
    """Ask Stripe whether this checkout was paid. The only source of truth for paid state.

    Pass owner_id from the logged-in user so one owner cannot claim another's session.
    """
    if not isinstance(session_id, str) or not session_id.startswith('cs_'):
        raise BillingError('invalid checkout session ID')
    try:
        session = client.checkout.Session.retrieve(
            session_id, api_key=config.secret_key, expand=['line_items'])
    except stripe.StripeError as exc:
        raise BillingError('could not verify checkout') from exc

    metadata = session.get('metadata') or {}
    if metadata.get('purpose') != PURPOSE:
        raise BillingError('checkout is not a software plan purchase')
    if session.get('livemode'):
        raise BillingError('live-mode payments are not accepted in this project')
    session_owner = session.get('client_reference_id')
    if owner_id is not None and session_owner != _owner(owner_id):
        raise BillingError('checkout belongs to a different account')
    items = (session.get('line_items') or {}).get('data') or []
    if [item['price']['id'] for item in items] != [config.price_id]:
        raise BillingError('checkout does not match the configured plan price')

    return {
        'owner_id': session_owner,
        'session_id': session['id'],
        'paid': session.get('status') == 'complete' and session.get('payment_status') == 'paid',
        'amount_total_cents': session.get('amount_total'),
        'currency': session.get('currency'),
    }


def handle_webhook(config: BillingConfig, payload: bytes, signature: str,
                   *, client=stripe) -> Optional[Dict[str, Any]]:
    """Verify a Stripe webhook. Returns verify_checkout's result for a completed
    software-plan checkout, or None for events we ignore.

    payload must be the raw request body bytes (not re-serialized JSON) and
    signature the Stripe-Signature header.
    """
    if not config.webhook_secret:
        raise BillingError('STRIPE_WEBHOOK_SECRET is not configured')
    try:
        event = client.Webhook.construct_event(payload, signature, config.webhook_secret)
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise BillingError('invalid webhook signature') from exc
    if event['type'] not in PAID_EVENTS:
        return None
    session = event['data']['object']
    if (session.get('metadata') or {}).get('purpose') != PURPOSE:
        return None
    # Re-fetch rather than trusting the event body for price/line-item checks.
    return verify_checkout(config, session['id'], client=client)
