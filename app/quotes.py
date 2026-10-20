"""Wires C's QuoteService to storage and trusted business context, plus display helpers.

Pages never compute money or workflow state: they show what quote_view/quote_card return.
"""
import dataclasses
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ai_service.data_loader import load_context
from quote_engine.checks import check_quote_readiness
from quote_engine.postgres_storage import QuoteStorageUnavailable
from quote_engine.pricing import QuoteError
from quote_engine.service import QuoteService

from .catalog import make_scrubber

ROOT = Path(__file__).resolve().parents[1]
MENU_CACHE_SECONDS = 5  # the owner's own saves clear it at once; other workers catch up within this
logger = logging.getLogger('app')

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
    """Owns the QuoteService and the business context for the single demo business.

    The menu is the owner's current menu (A's MenuService) when one is saved; until then,
    or if menu storage is down, it is the dataset's menu file. Chat pricing, submission,
    approval and the home page all read it through current_context().
    """

    def __init__(self, settings, *, store=None, context=None, menus=None, owner_id=None):
        self.settings = settings
        self.base_context = context or load_context(settings.dataset)
        self.scrub = make_scrubber(self.base_context.menu)  # keep the provenance name off every screen
        self.menus = menus          # menu_admin.MenuService or None
        self.owner_id = owner_id    # the business whose menu this is
        self.menu_source = 'file'   # 'saved' (owner's menu), 'file' (not saved yet) or 'unavailable'
        self._menu_lock = threading.Lock()
        self._menu_cache = None     # (fetched_at, menu, context, item_labels)
        self._store = store
        self._service: Optional[QuoteService] = None

    def attach_menus(self, menus, owner_id):
        self.menus, self.owner_id = menus, owner_id
        self.forget_menu()

    # ---- current menu ----------------------------------------------------
    def forget_menu(self):
        with self._menu_lock:
            self._menu_cache = None

    def _load_menu(self):
        if self.menus is None or not self.owner_id:
            return self.base_context.menu, 'file'
        from menu_admin import MenuNotFound
        try:
            return self.menus.current_menu(self.owner_id), 'saved'
        except MenuNotFound:
            return self.base_context.menu, 'file'
        except QuoteError:  # MenuStorageUnavailable (e.g. migration not applied): keep quoting from the file
            logger.warning('Menu storage unavailable; pricing from the menu file')
            return self.base_context.menu, 'unavailable'

    def _menu_state(self):
        with self._menu_lock:
            cached = self._menu_cache
            if cached and time.monotonic() - cached[0] < MENU_CACHE_SECONDS:
                return cached
        menu, source = self._load_menu()
        context = self.base_context if menu is self.base_context.menu else dataclasses.replace(self.base_context, menu=menu)
        labels = {}
        for item in menu.get('items', []):
            name = self.scrub(item['name'])
            labels[item['id']] = name
            for variant in item.get('variants', []):
                labels[variant['id']] = '{} ({})'.format(name, variant.get('label', ''))
        state = (time.monotonic(), menu, context, labels)
        with self._menu_lock:
            self._menu_cache = state
            self.menu_source = source
        return state

    def current_menu(self):
        return self._menu_state()[1]

    def current_context(self):
        return self._menu_state()[2]

    @property
    def context(self):
        return self.current_context()

    @property
    def items(self):
        return self._menu_state()[3]

    @property
    def service(self) -> QuoteService:
        if self._service is None:
            store = self._store or self._default_store()
            self._service = QuoteService(
                store, clock=self.base_context.now,
                context_for=lambda owner_id, request: self.current_context().quote_service_context(owner_id, request))
        return self._service

    def menu_check(self, quote_id, *, actor_id) -> dict:
        """How the latest draft compares with today's menu, for the owner's quote page.

        {'state': 'ok'}; {'state': 'prices'} when it would price differently (reprice it);
        or {'state': 'unavailable', 'items': [names], 'variants': [variant ids]} when a chosen dish or size is off the
        menu, which the engine cannot price at all (put it back, or change the order).
        """
        record = self.service.store.get(quote_id, actor_id=actor_id)
        version = record['versions'][-1]
        if version['status'] != 'draft' or not version['readiness'].get('pricing'):
            return {'state': 'ok'}
        request = version['request']
        context = self.service.context_for(record['owner_id'], dict(request))
        off = self._unavailable_choices(context['menu'], request)
        if off:
            return {'state': 'unavailable', 'items': list(dict.fromkeys(label for label, _ in off)),
                    'variants': [variant_id for _, variant_id in off]}
        ready = check_quote_readiness(context['menu'], context['rules'], request,
                                      now=self.service.clock(), capacity=context.get('capacity'))
        return {'state': 'prices' if ready.get('pricing') != version['readiness']['pricing'] else 'ok'}

    def _unavailable_choices(self, menu, request):
        items = {item['id']: item for item in menu.get('items', [])}
        found = []
        for choice in request.get('selections') or []:
            item = items.get(choice.get('item_id'))
            variant = next((v for v in (item or {}).get('variants', []) if v['id'] == choice.get('variant_id')), None)
            if item is None or variant is None or item.get('available', True) is not True or variant.get('available', True) is not True:
                label = self.items.get(choice.get('variant_id')) or self.items.get(choice.get('item_id')) or 'A dish'
                found.append((label, choice.get('variant_id')))
        return found

    def pricing_changed(self, quote_id, *, actor_id) -> bool:
        return self.menu_check(quote_id, actor_id=actor_id)['state'] != 'ok'

    def reprice(self, quote_id, *, actor_id, expected_revision):
        """Owner: make a new draft version of the same request with today's menu."""
        record = self.service.store.get(quote_id, actor_id=actor_id)
        if actor_id != record['owner_id']:
            raise QuoteError('only the owner can reprice')
        request = {k: v for k, v in record['versions'][-1]['request'].items() if k not in ('tax_location', 'delivery_miles')}
        return self.service.revise(quote_id, request, actor_id=actor_id, expected_revision=expected_revision)

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
        local = parsed.astimezone(self.base_context.now().tzinfo) if parsed.tzinfo else parsed
        hour = local.strftime('%I:%M %p').lstrip('0')
        return f'{local:%a}, {local:%b} {local.day}, {local.year} · {hour}'

    @staticmethod
    def tone(status: str) -> str:
        return STATUS_TONE.get(status, 'pending')
