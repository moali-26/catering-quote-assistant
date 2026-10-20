"""Wires C's QuoteService to storage and trusted business context, plus display helpers.

Pages never compute money or workflow state: they show what quote_view/quote_card return.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from ai_service.data_loader import load_context
from quote_engine.postgres_storage import QuoteStorageUnavailable
from quote_engine.service import QuoteService
from quote_engine.storage import QuoteNotFound

from .catalog import make_scrubber

ROOT = Path(__file__).resolve().parents[1]

REVIEW_LABELS = {
    'owner_confirmation_required': 'Confirm availability and the final details with the customer',
    'portion_and_dietary_review_required': 'Check that portions and dietary needs are covered',
    'synthetic_capacity_requires_owner_confirmation': 'The calendar is sample data: confirm the date is free',
    'capacity_not_checked': 'Capacity was not checked: confirm the date is free',
    'allergen_depends_on_selection': 'Allergens depend on the choices for {item}',
    'allergen_unknown': 'Allergen information is unknown for {item}',
    'assumed_servings': 'Servings for {item} are an estimate: check the portion size',
    'unrecognized_allergen_requires_clarification': 'An allergy the customer named isn’t recognized: clarify it',
    'event_in_past': 'The event date has passed',
    'insufficient_lead_time': 'Not enough notice before the event',
    'capacity_conflict': 'The kitchen is fully booked that day',
    'allergen_conflict': '{item} contains {detail}, which the customer is allergic to',
}
FIELD_LABELS = {
    'headcount': 'Guest count', 'event_at': 'Event date and time', 'service_mode': 'Pickup or delivery',
    'address': 'Delivery address', 'allergens': 'Allergies', 'selections': 'Menu items',
    'tax_location': 'Delivery city', 'delivery_miles': 'Delivery distance',
}
# Blockers shown to the customer in the chat draft (second person; owner wording stays above).
CUSTOMER_BLOCK_LABELS = {
    'event_in_past': 'The event date has already passed. Pick a future date',
    'insufficient_lead_time': 'That’s too soon for us to prepare. Choose a later date',
    'capacity_conflict': 'The kitchen is fully booked that day. Try another date',
    'allergen_conflict': '{item} contains {detail}, which you said to avoid. Swap it for something else',
}
STATUS_TONE = {'draft': 'pending', 'owner_approved': 'ready', 'customer_accepted': 'done', 'customer_declined': 'closed'}


class StorageNotConfigured(QuoteStorageUnavailable):
    """Production without QUOTE_DATABASE_URL: quote pages show a 503, the rest of the site works."""


def humanize(code: str) -> str:
    return code.replace('_', ' ').replace(':', ': ').strip().capitalize()


class QuoteApp:
    """Owns the QuoteService and the business context for the single demo business."""

    def __init__(self, settings, *, store=None, context=None):
        self.settings = settings
        self._context = context or load_context(settings.dataset)
        self.menu_service = None
        self.menu_owner_id = None
        self.scrub = make_scrubber(self.context.menu)  # keep the provenance name off every screen
        self.items = {}
        for item in self.context.menu.get('items', []):
            name = self.scrub(item['name'])
            self.items[item['id']] = name
            for variant in item.get('variants', []):
                self.items[variant['id']] = '{} ({})'.format(name, variant.get('label', ''))
        self._store = store
        self._service: Optional[QuoteService] = None

    @property
    def context(self):
        if self.menu_service is None:
            return self._context
        from dataclasses import replace
        from menu_admin import MenuNotFound
        from menu_admin.postgres_storage import MenuStorageUnavailable
        try:
            menu = self.menu_service.current_menu(self.menu_owner_id)
        except MenuNotFound:
            # Before the owner's one-time initialization, use the frozen seed.
            return self._context
        except MenuStorageUnavailable as exc:
            raise QuoteStorageUnavailable('menu storage unavailable') from exc
        if menu['meta']['dataset_id'] != self._context.menu['meta']['dataset_id']:
            raise QuoteStorageUnavailable('menu dataset does not match business rules')
        return replace(self._context, menu=menu)

    def current_quote_context(self, owner_id, request):
        if self.menu_owner_id is not None and owner_id != self.menu_owner_id:
            raise QuoteNotFound('quote not found')
        return self.context.quote_service_context(owner_id, request)

    @property
    def service(self) -> QuoteService:
        if self._service is None:
            store = self._store or self._default_store()
            self._service = QuoteService(store, context_for=self.current_quote_context,
                                         clock=self._context.now)
        return self._service

    def _default_store(self):
        if self.settings.database_url:
            from quote_engine.postgres_storage import PostgresQuoteStore
            return PostgresQuoteStore(self.settings.database_url)
        if self.settings.is_production:
            raise StorageNotConfigured('QUOTE_DATABASE_URL is not set')
        from quote_engine.storage import SQLiteQuoteStore
        folder = ROOT / 'var'
        folder.mkdir(exist_ok=True)
        return SQLiteQuoteStore(folder / 'quotes.sqlite3')

    # ---- display helpers -------------------------------------------------
    def customer_block_label(self, code: str) -> str:
        base, _, rest = code.partition(':')
        item_id, _, detail = rest.partition(':')
        template = CUSTOMER_BLOCK_LABELS.get(base)
        if not template:
            return self.review_label(code)
        return self.scrub(template.format(item=self.items.get(item_id, item_id or 'An item'),
                                          detail=detail.replace('_', ' ') or 'an allergen'))

    def review_label(self, code: str) -> str:
        base, _, rest = code.partition(':')
        item_id, _, detail = rest.partition(':')
        template = REVIEW_LABELS.get(base)
        if template:
            text = template.format(item=self.items.get(item_id, item_id or 'an item'),
                                   detail=detail.replace('_', ' ') or 'an allergen')
            return text[0].upper() + text[1:]
        return humanize(code)

    @staticmethod
    def field_label(code: str) -> str:
        return FIELD_LABELS.get(code, humanize(code))

    def event_time(self, value) -> str:
        if not value:
            return 'Date to be confirmed'
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return str(value)
        local = parsed.astimezone(self.context.now().tzinfo) if parsed.tzinfo else parsed
        hour = local.strftime('%I:%M %p').lstrip('0')
        return f'{local:%a}, {local:%b} {local.day}, {local.year} · {hour}'

    @staticmethod
    def tone(status: str) -> str:
        return STATUS_TONE.get(status, 'pending')
