"""Part A owner menu editing: validation, permissions, revisions, and effect on quotes/AI."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from ai_service import ServerContext
from ai_service.data_loader import load_context
from ai_service.menu_tools import search_menu
from menu_admin import (MenuConflict, MenuEditError, MenuNotFound, MenuService, SQLiteMenuStore,
                        apply_menu_changes)
from menu_admin.postgres_storage import PostgresMenuStore
from quote_engine import QuoteError
from quote_engine.ai_tool import evaluate_catering_quote
from quote_engine.service import QuoteService
from quote_engine.storage import SQLiteQuoteStore

NOW = '2026-10-18T12:00:00-07:00'
OWNER, CUSTOMER = 'owner-1', 'customer-1'
REQUEST = {
    'headcount': 40, 'event_at': '2026-10-30T12:00:00-07:00', 'service_mode': 'delivery',
    'address': '123 Main St, Culver City', 'allergens': [],
    'selections': [
        {'item_id': 'pan-tri-tip', 'variant_id': 'pan-tri-tip-full', 'quantity': 2},
        {'item_id': 'salad-garden', 'variant_id': 'salad-garden-full', 'quantity': 1},
        {'item_id': 'dessert-brownie', 'variant_id': 'dessert-brownie-pp', 'quantity': 40},
    ],
}
BROWNIE_PRICE = {'item_id': 'dessert-brownie', 'variant_id': 'dessert-brownie-pp', 'set': {'price': '4.29'}}


class EditRulesTests(unittest.TestCase):
    def setUp(self):
        self.menu = load_context('demo', NOW).menu

    def item(self, menu, item_id):
        return next(i for i in menu['items'] if i['id'] == item_id)

    def test_price_name_description_availability(self):
        new, applied = apply_menu_changes(self.menu, [
            BROWNIE_PRICE,
            {'item_id': 'pan-tri-tip', 'set': {'name': '  Smoked   Tri Tip ', 'available': False}},
            {'item_id': 'salad-garden', 'set': {'description': 'Seasonal greens.'}},
        ])
        self.assertEqual(self.item(new, 'dessert-brownie')['variants'][0]['price'], 4.29)
        self.assertEqual(self.item(new, 'pan-tri-tip')['name'], 'Smoked Tri Tip')
        self.assertFalse(self.item(new, 'pan-tri-tip')['available'])
        self.assertEqual({a['field'] for a in applied}, {'price', 'name', 'available', 'description'})
        self.assertEqual(self.item(self.menu, 'dessert-brownie')['variants'][0]['price'], 3.29)  # input untouched

    def test_fixed_fields_rejected(self):
        for change in [{'item_id': 'salad-garden', 'set': {'allergens': []}},
                       {'item_id': 'salad-garden', 'set': {'dietary_tags': ['vegan']}},
                       {'item_id': 'salad-garden', 'set': {'id': 'x'}},
                       {'item_id': 'salad-garden', 'set': {'price': 1}},  # price is per variant
                       {'item_id': 'salad-garden', 'variant_id': 'salad-garden-full',
                        'set': {'pricing_unit': 'each'}}]:
            with self.subTest(change=change), self.assertRaises(MenuEditError):
                apply_menu_changes(self.menu, [change])

    def test_bad_values_rejected(self):
        for price in [0, -5, 'abc', '1.234', True, 99999, float('nan'), None]:
            with self.subTest(price=price), self.assertRaises(MenuEditError):
                apply_menu_changes(self.menu, [dict(BROWNIE_PRICE, set={'price': price})])
        for name in ['', '   ', 'x' * 121, 'bad\x00name', 123]:
            with self.subTest(name=name), self.assertRaises(MenuEditError):
                apply_menu_changes(self.menu, [{'item_id': 'salad-garden', 'set': {'name': name}}])
        with self.assertRaises(MenuEditError):
            apply_menu_changes(self.menu, [{'item_id': 'salad-garden', 'set': {'available': 'no'}}])

    def test_unknown_ids_and_all_or_nothing(self):
        with self.assertRaises(MenuEditError):
            apply_menu_changes(self.menu, [{'item_id': 'nope', 'set': {'available': False}}])
        with self.assertRaises(MenuEditError):
            apply_menu_changes(self.menu, [{'item_id': 'salad-garden', 'variant_id': 'pan-tri-tip-full',
                                            'set': {'price': 10}}])
        before = json.dumps(self.menu)
        with self.assertRaises(MenuEditError):
            apply_menu_changes(self.menu, [BROWNIE_PRICE, {'item_id': 'nope', 'set': {'name': 'x'}}])
        self.assertEqual(json.dumps(self.menu), before)

    def test_no_op_rejected(self):
        with self.assertRaises(MenuEditError):
            apply_menu_changes(self.menu, [dict(BROWNIE_PRICE, set={'price': '3.29'})])
        with self.assertRaises(MenuEditError):
            apply_menu_changes(self.menu, [])


class MenuServiceTests(unittest.TestCase):
    def setUp(self):
        self.ctx = load_context('demo', NOW)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.menus = MenuService(SQLiteMenuStore(self.path / 'menus.sqlite3'), clock=self.ctx.now)
        self.menus.seed(OWNER, self.ctx.menu)

    def context_for(self, owner_id, request):
        """What D's load_current_business_context should do: current menu from storage."""
        ctx = ServerContext(menu=self.menus.current_menu(owner_id), rules=self.ctx.rules,
                            capacity=self.ctx.capacity, clock=self.ctx.clock)
        return ctx.quote_service_context(owner_id, request)

    def test_owner_edits_and_change_log(self):
        view = self.menus.update(OWNER, [BROWNIE_PRICE], actor_id=OWNER, expected_revision=1)
        self.assertEqual(view['revision'], 2)
        self.assertEqual(view['applied'][0]['new'], 4.29)
        log = self.menus.change_log(OWNER, actor_id=OWNER)
        self.assertEqual((log[0]['field'], log[0]['old'], log[0]['by']), ('price', 3.29, OWNER))

    def test_only_owner_can_view_or_edit(self):
        for actor in (CUSTOMER, 'owner-2', '', None):
            with self.subTest(actor=actor):
                with self.assertRaises(MenuNotFound):
                    self.menus.update(OWNER, [BROWNIE_PRICE], actor_id=actor, expected_revision=1)
                with self.assertRaises(MenuNotFound):
                    self.menus.owner_view(OWNER, actor_id=actor)
        self.assertEqual(self.menus.owner_view(OWNER, actor_id=OWNER)['revision'], 1)

    def test_stale_tab_cannot_overwrite(self):
        self.menus.update(OWNER, [BROWNIE_PRICE], actor_id=OWNER, expected_revision=1)
        with self.assertRaises(MenuConflict):
            self.menus.update(OWNER, [{'item_id': 'pan-tri-tip', 'set': {'available': False}}],
                              actor_id=OWNER, expected_revision=1)

    def test_seed_twice_conflicts_and_edits_persist(self):
        with self.assertRaises(MenuConflict):
            self.menus.seed(OWNER, self.ctx.menu)
        self.menus.update(OWNER, [BROWNIE_PRICE], actor_id=OWNER, expected_revision=1)
        reopened = MenuService(SQLiteMenuStore(self.path / 'menus.sqlite3'), clock=self.ctx.now)
        brownie = next(i for i in reopened.current_menu(OWNER)['items'] if i['id'] == 'dessert-brownie')
        self.assertEqual(brownie['variants'][0]['price'], 4.29)

    def test_price_edit_new_quotes_change_saved_quotes_do_not(self):
        quotes = QuoteService(SQLiteQuoteStore(self.path / 'quotes.sqlite3'),
                              context_for=self.context_for, clock=self.ctx.now)
        saved = quotes.submit(REQUEST, actor_id=CUSTOMER, owner_id=OWNER)
        old_total = saved['pricing']['amounts']['total_cents']['cents']

        self.menus.update(OWNER, [BROWNIE_PRICE], actor_id=OWNER, expected_revision=1)

        reopened = quotes.detail(saved['quote_id'], actor_id=CUSTOMER)
        self.assertEqual(reopened['pricing']['amounts']['total_cents']['cents'], old_total)
        new = quotes.submit(REQUEST, actor_id=CUSTOMER, owner_id=OWNER)
        self.assertGreater(new['pricing']['amounts']['total_cents']['cents'], old_total)
        # Approving the old draft at the old price is refused: owner must revise explicitly.
        owner_view = quotes.detail(saved['quote_id'], actor_id=OWNER)
        with self.assertRaises(QuoteError):
            quotes.approve(saved['quote_id'], actor_id=OWNER, expected_revision=1,
                           acknowledged_reviews=owner_view['approval_requires_acknowledgment'])

    def test_unavailable_item_hidden_from_ai_and_rejected(self):
        self.menus.update(OWNER, [{'item_id': 'pan-tri-tip', 'set': {'available': False}}],
                          actor_id=OWNER, expected_revision=1)
        menu = self.menus.current_menu(OWNER)
        self.assertNotIn('pan-tri-tip', {i['item_id'] for i in search_menu(menu, {})['items']})
        result = evaluate_catering_quote(REQUEST, menu=menu, rules=self.ctx.rules,
                                         capacity=self.ctx.capacity, now=self.ctx.now(),
                                         tax_location='Culver City', delivery_miles=15)
        self.assertEqual(result['error_code'], 'menu_item_unavailable')


class PostgresMenuStoreTests(unittest.TestCase):
    """Mocked contract tests (no live database), like C's test_postgres_storage."""

    def setUp(self):
        self.owner = str(uuid4())
        self.store = PostgresMenuStore('test-only-dsn')
        self.db = MagicMock()
        patcher = patch.object(self.store, '_connect')
        self.connect = patcher.start()
        self.addCleanup(patcher.stop)
        self.connect.return_value.__enter__.return_value = self.db
        self.record = {'owner_id': self.owner, 'revision': 1, 'menu': {'items': []}, 'change_log': []}

    def test_create_uses_bound_parameters(self):
        self.store.create(self.record)
        sql, params = self.db.execute.call_args.args
        self.assertNotIn(self.owner, sql)
        self.assertEqual(params[0], self.owner)

    def test_non_uuid_owner_rejected_before_connecting(self):
        with self.assertRaises(QuoteError):
            self.store.get('owner-1')
        self.connect.assert_not_called()

    def test_stale_save_is_conflict(self):
        self.db.execute.return_value.rowcount = 0
        self.db.execute.return_value.fetchone.return_value = (1,)
        with self.assertRaises(MenuConflict):
            self.store.save(dict(self.record, revision=2), expected_revision=1)

    def test_missing_menu(self):
        self.db.execute.return_value.fetchone.return_value = None
        with self.assertRaises(MenuNotFound):
            self.store.get(self.owner)


if __name__ == '__main__':
    unittest.main()
