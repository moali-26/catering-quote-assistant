"""Quote Kitchen Subscription Plan for the owner (Stripe test mode) wired into the web app.

E's billing package talks to Stripe; this module decides what the app trusts and stores.
This is the owner subscribing to Quote Kitchen, never a customer paying for food.

Paid state is recorded only after Stripe confirms it: the success page asks Stripe
(verify_checkout) and the signed webhook re-fetches the session (handle_webhook).
Arriving at the success URL proves nothing on its own.
"""
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from billing import BillingConfig, BillingError, create_checkout, handle_webhook, verify_checkout
from quote_engine.postgres_storage import QuoteStorageUnavailable

logger = logging.getLogger('app.billing')


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- storage

class SQLiteBillingStore:
    """Local development storage; same contract as PostgresBillingStore."""

    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS owner_billing (
                owner_id TEXT PRIMARY KEY, paid INTEGER NOT NULL, session_id TEXT,
                amount_total_cents INTEGER, currency TEXT, paid_at TEXT, updated_at TEXT NOT NULL)''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, owner_id) -> Optional[Dict[str, Any]]:
        with self._db() as db:
            row = db.execute('''SELECT owner_id, paid, session_id, amount_total_cents, currency, paid_at
                                FROM owner_billing WHERE owner_id = ?''', (owner_id,)).fetchone()
        if not row:
            return None
        return {'owner_id': row[0], 'paid': bool(row[1]), 'session_id': row[2],
                'amount_total_cents': row[3], 'currency': row[4], 'paid_at': row[5]}

    def record_paid(self, result) -> None:
        """Idempotent: the first confirmed payment is kept; a repeat (webhook + success page) is a no-op."""
        now = _now()
        with self._db() as db:
            db.execute('''INSERT INTO owner_billing VALUES (?, 1, ?, ?, ?, ?, ?)
                          ON CONFLICT(owner_id) DO UPDATE SET paid = 1, session_id = excluded.session_id,
                              amount_total_cents = excluded.amount_total_cents, currency = excluded.currency,
                              paid_at = excluded.paid_at, updated_at = excluded.updated_at
                          WHERE owner_billing.paid = 0''',
                       (result['owner_id'], result['session_id'], result.get('amount_total_cents'),
                        result.get('currency'), now, now))


class PostgresBillingStore:
    """catering_private.owner_billing through the server-only connection (never the browser)."""

    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def _db(self):
        import psycopg
        try:
            with psycopg.connect(self.dsn, sslmode='require', connect_timeout=10, prepare_threshold=None) as db:
                yield db
        except psycopg.Error:
            raise QuoteStorageUnavailable('billing storage unavailable; please retry') from None

    def get(self, owner_id) -> Optional[Dict[str, Any]]:
        with self._db() as db:
            row = db.execute('''SELECT owner_id, paid, session_id, amount_total_cents, currency, paid_at
                                FROM catering_private.owner_billing WHERE owner_id = %s''', (owner_id,)).fetchone()
        if not row:
            return None
        return {'owner_id': str(row[0]), 'paid': bool(row[1]), 'session_id': row[2],
                'amount_total_cents': row[3], 'currency': row[4],
                'paid_at': row[5].isoformat() if row[5] else None}

    def record_paid(self, result) -> None:
        with self._db() as db:
            db.execute('''INSERT INTO catering_private.owner_billing
                              (owner_id, paid, session_id, amount_total_cents, currency, paid_at)
                          VALUES (%s, true, %s, %s, %s, now())
                          ON CONFLICT (owner_id) DO UPDATE SET paid = true, session_id = EXCLUDED.session_id,
                              amount_total_cents = EXCLUDED.amount_total_cents, currency = EXCLUDED.currency,
                              paid_at = EXCLUDED.paid_at, updated_at = now()
                          WHERE catering_private.owner_billing.paid = false''',
                       (result['owner_id'], result['session_id'], result.get('amount_total_cents'),
                        result.get('currency')))


# ---------------------------------------------------------------- service

class BillingApp:
    """What the routes call. config is None when Stripe isn't set up (page says so)."""

    def __init__(self, config: Optional[BillingConfig], store, *, owner_ids, client=None):
        self.config = config
        self.store = store
        self.owner_ids = tuple(owner_ids)
        self.client = client  # None = the real stripe module (tests pass a fake)

    @property
    def configured(self) -> bool:
        return self.config is not None and self.store is not None

    @property
    def webhook_ready(self) -> bool:
        return self.configured and bool(self.config.webhook_secret)

    def _stripe(self):
        return {} if self.client is None else {'client': self.client}

    def status(self, owner_id) -> Optional[Dict[str, Any]]:
        return self.store.get(owner_id) if self.store is not None else None

    def start(self, owner_id, base_url) -> str:
        """Create a Checkout Session; returns the Stripe URL to redirect the owner to."""
        session = create_checkout(self.config, owner_id,
                                  success_url=f'{base_url}/owner/billing/success',
                                  cancel_url=f'{base_url}/owner/billing?canceled=1', **self._stripe())
        return session['url']

    def confirm(self, owner_id, session_id) -> str:
        """Success page: ask Stripe. Returns 'paid' or 'pending'. Raises BillingError if it isn't theirs."""
        result = verify_checkout(self.config, session_id, owner_id=owner_id, **self._stripe())
        if result['session_id'] != session_id:  # defense in depth: must be exactly the session asked about
            raise BillingError('checkout session mismatch')
        if result['paid']:
            self.store.record_paid(result)
            return 'paid'
        return 'pending'

    def webhook(self, payload: bytes, signature: str) -> bool:
        """Signed webhook. Returns True when a payment was recorded. Raises BillingError on a bad signature."""
        result = handle_webhook(self.config, payload, signature, **self._stripe())
        if not result or not result['paid']:
            return False
        if result.get('owner_id') not in self.owner_ids:
            # Checkout is only started from the owner page, so this means a stale or foreign session.
            logger.warning('Ignoring paid checkout for an account that is not a configured owner')
            return False
        self.store.record_paid(result)
        return True


def build_billing(settings, owner_ids, *, env=None) -> BillingApp:
    """Billing from STRIPE_* env vars. Missing or invalid config turns billing off without crashing the site."""
    env = os.environ if env is None else env
    config = None
    if env.get('STRIPE_SECRET_KEY') or env.get('STRIPE_PRICE_ID'):
        try:
            config = BillingConfig.from_env(env)
        except BillingError as exc:  # e.g. a live key: refuse, but keep the rest of the site up
            logger.warning('Stripe billing disabled: %s', exc)
    if settings.database_url:
        store = PostgresBillingStore(settings.database_url)
    elif settings.is_production:
        store = None
    else:
        folder = Path(__file__).resolve().parents[1] / 'var'
        folder.mkdir(exist_ok=True)
        store = SQLiteBillingStore(folder / 'billing.sqlite3')
    if config is None:
        logger.warning('Quote Kitchen subscription checkout is off (needs STRIPE_SECRET_KEY and STRIPE_PRICE_ID)')
    return BillingApp(config, store, owner_ids=owner_ids)
