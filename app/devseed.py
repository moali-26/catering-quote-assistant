"""Local preview data for AUTH_BACKEND=memory (never used in production).

Creates a demo owner and customer, plus one submitted quote, so the screens can be
tried before the chat is connected. Passwords here are throwaway local values.
"""
from datetime import timedelta

DEV_OWNER_ID = '00000000-0000-4000-8000-00000000000a'
DEV_CUSTOMER_ID = '00000000-0000-4000-8000-00000000000c'
DEV_OWNER_EMAIL = 'owner@example.com'
DEV_CUSTOMER_EMAIL = 'customer@example.com'
DEV_PASSWORD = 'catering-demo'


def seed(auth_backend, quote_app) -> None:
    for email, uid in ((DEV_OWNER_EMAIL, DEV_OWNER_ID), (DEV_CUSTOMER_EMAIL, DEV_CUSTOMER_ID)):
        try:
            auth_backend.sign_up(email, DEV_PASSWORD, user_id=uid)
        except Exception:
            pass  # already created
    service = quote_app.service
    if service.list_quotes(actor_id=DEV_CUSTOMER_ID, workspace='customer'):
        return
    now = quote_app.context.now()
    event = (now + timedelta(days=6)).replace(hour=12, minute=0, second=0, microsecond=0)
    request = {
        'headcount': 40,
        'event_at': event.isoformat(),
        'service_mode': 'delivery',
        'address': '9300 Culver Blvd, Culver City, CA',
        'allergens': ['peanut', 'tree_nuts'],
        'dietary_needs': ['vegetarian'],
        'selections': [
            {'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': 40},
            {'item_id': 'side-garlic-mashed', 'variant_id': 'side-garlic-mashed-full', 'quantity': 1},
        ],
    }
    service.submit(request, actor_id=DEV_CUSTOMER_ID, owner_id=DEV_OWNER_ID)
