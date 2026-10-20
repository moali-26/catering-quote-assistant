"""Frozen demo dataset (data/demo): provenance, engine compatibility, availability, AI use."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data' / 'demo'))

from validate_demo import validate  # noqa: E402

from ai_service import Conversation, LLMResponse, ScriptedLLM, ToolCall  # noqa: E402
from ai_service.data_loader import load_context  # noqa: E402
from ai_service.menu_tools import search_menu  # noqa: E402
from ai_service.prompts import build_system_prompt  # noqa: E402
from quote_engine import QuoteError, calculate_quote, create_quote  # noqa: E402
from quote_engine.ai_tool import evaluate_catering_quote  # noqa: E402

NOW = '2026-10-18T12:00:00-07:00'
REQUEST = {
    'headcount': 40, 'event_at': '2026-10-30T12:00:00-07:00', 'service_mode': 'delivery',
    'address': '123 Main St, Culver City', 'allergens': ['peanut', 'tree_nuts'],
    'selections': [
        {'item_id': 'pan-tri-tip', 'variant_id': 'pan-tri-tip-full', 'quantity': 2},
        {'item_id': 'pasta-marinara', 'variant_id': 'pasta-marinara-full', 'quantity': 1},
        {'item_id': 'salad-garden', 'variant_id': 'salad-garden-full', 'quantity': 1},
        {'item_id': 'dessert-brownie', 'variant_id': 'dessert-brownie-pp', 'quantity': 40},
    ],
}


def load(*parts):
    return json.loads(ROOT.joinpath(*parts).read_text())


class DemoDatasetTests(unittest.TestCase):
    def setUp(self):
        self.ctx = load_context('demo', NOW)
        self.full = load('data', 'menu.json')
        self.inquiries = load('data', 'sample', 'inquiries.json')

    def evaluate(self, menu, args):
        return evaluate_catering_quote(args, menu=menu, rules=self.ctx.rules,
                                       capacity=self.ctx.capacity, now=self.ctx.now(),
                                       tax_location='Culver City', delivery_miles=15)

    def test_validator_passes(self):
        self.assertEqual(validate(self.ctx.menu, self.ctx.rules, self.ctx.capacity,
                                  self.full, self.inquiries), [])

    def test_validator_catches_changed_price_and_brand_name(self):
        menu = copy.deepcopy(self.ctx.menu)
        menu['items'][0]['variants'][0]['price'] = 1.0
        menu['items'][1]['name'] = 'Stonefire Tenders'
        errors = validate(menu, self.ctx.rules, self.ctx.capacity, self.full, self.inquiries)
        self.assertTrue(any('price differs' in e for e in errors))
        self.assertTrue(any('real brand' in e for e in errors))

    def test_realistic_demo_quote(self):
        result = self.evaluate(self.ctx.menu, REQUEST)
        self.assertEqual(result['status'], 'needs_owner_review')
        self.assertEqual(result['blocking_reasons'], [])  # brownie has no listed nuts

    def test_nut_allergy_conflict_is_blocked(self):
        args = copy.deepcopy(REQUEST)
        args['selections'][3] = {'item_id': 'dessert-cookie-platter',
                                 'variant_id': 'dessert-cookie-platter-48', 'quantity': 1}
        result = self.evaluate(self.ctx.menu, args)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('allergen_conflict:dessert-cookie-platter:peanut', result['blocking_reasons'])

    def test_full_date_is_blocked(self):
        result = self.evaluate(self.ctx.menu, dict(REQUEST, event_at='2026-10-31T12:00:00-07:00'))
        self.assertIn('capacity_conflict', result['blocking_reasons'])

    def test_unavailable_item_hidden_and_rejected(self):
        menu = copy.deepcopy(self.ctx.menu)
        tri_tip = next(i for i in menu['items'] if i['id'] == 'pan-tri-tip')
        tri_tip['available'] = False
        self.assertNotIn('pan-tri-tip', {i['item_id'] for i in search_menu(menu, {})['items']})
        result = self.evaluate(menu, REQUEST)
        self.assertEqual(result['error_code'], 'menu_item_unavailable')

    def test_price_edit_changes_new_quotes_not_saved_ones(self):
        rules = self.ctx.rules
        saved = create_quote(self.ctx.menu, rules, dict(REQUEST, tax_location='Culver City', delivery_miles=15),
                             owner_id='owner', customer_id='cust', now=self.ctx.now(),
                             capacity=self.ctx.capacity)
        before = saved['versions'][-1]['readiness']['pricing']['total_cents']
        snapshot = json.dumps(saved)

        edited = copy.deepcopy(self.ctx.menu)
        brownie = next(i for i in edited['items'] if i['id'] == 'dessert-brownie')
        brownie['variants'][0]['price'] = 4.29
        new = calculate_quote(edited, rules, dict(REQUEST, tax_location='Culver City', delivery_miles=15))
        self.assertGreater(new['total_cents'], before)
        self.assertEqual(json.dumps(saved), snapshot)  # stored quote untouched

    def test_ai_sees_display_names_not_brand(self):
        prompt = build_system_prompt(self.ctx)
        names = json.dumps(search_menu(self.ctx.menu, {})['items'])
        self.assertNotIn('Stonefire', prompt + names)
        self.assertIn('Classic Package', names)

    def test_conversation_runs_on_demo_menu(self):
        llm = ScriptedLLM([
            LLMResponse(tool_calls=[ToolCall('c1', 'search_menu', {'dietary': ['vegetarian']})]),
            LLMResponse(tool_calls=[ToolCall('c2', 'evaluate_catering_quote', REQUEST)]),
            LLMResponse(content='Here is your draft; the owner will review it.'),
        ])
        turn = Conversation(llm, self.ctx).send('Lunch for 40 on Oct 30 in Culver City, nut allergy.')
        self.assertTrue(turn.ready_to_submit)
        self.assertEqual(turn.quote['tax_location'], 'Culver City')

    def test_engine_rejects_mixing_with_sample_rules(self):
        with self.assertRaises(QuoteError):
            calculate_quote(self.ctx.menu, load('data', 'sample', 'rules.json'),
                            dict(REQUEST, tax_location='Culver City', delivery_miles=15))


if __name__ == '__main__':
    unittest.main()
