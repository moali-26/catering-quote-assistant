import copy
import json
from pathlib import Path
import unittest
from quote_engine import QuoteError, calculate_quote

ROOT = Path(__file__).resolve().parents[1]


class PricingTests(unittest.TestCase):
    def setUp(self):
        data = ROOT / 'data' / 'sample'
        self.menu = json.loads((data / 'menu.json').read_text())
        self.rules = json.loads((data / 'rules.json').read_text())
        examples = json.loads((data / 'inquiries.json').read_text())
        self.request = dict(examples['pricing_example'], headcount=40)
        self.expected = examples['pricing_example']['expected']

    def quote(self):
        return calculate_quote(self.menu, self.rules, self.request)

    def test_hand_checked_example(self):
        result = self.quote()
        for key in ['food_subtotal', 'delivery_fee', 'service_charge', 'staffing_fee', 'taxable_subtotal', 'tax', 'total']:
            self.assertEqual(result[key + '_cents'], round(self.expected[key] * 100))
        self.assertEqual(result['total_cents'], 74904)
        self.assertIn('allergen_depends_on_selection:pkg-pasta-duo', result['flags'])
        self.assertTrue(result['requires_owner_review'])

    def test_inputs_unchanged_and_result_is_json(self):
        before = copy.deepcopy((self.menu, self.rules, self.request))
        json.dumps(self.quote())
        self.assertEqual(before, (self.menu, self.rules, self.request))

    def test_bad_quantity(self):
        for value in [0, -1, 1.5, True, '40']:
            with self.subTest(value=value):
                self.request['selections'][0]['quantity'] = value
                with self.assertRaises(QuoteError): self.quote()

    def test_unknown_or_mismatched_variant(self):
        self.request['selections'][0]['item_id'] = 'wrong'
        with self.assertRaises(QuoteError): self.quote()
        self.request['selections'][0]['variant_id'] = 'missing'
        with self.assertRaises(QuoteError): self.quote()

    def test_duplicate_selection(self):
        self.request['selections'].append(dict(self.request['selections'][0]))
        with self.assertRaises(QuoteError): self.quote()

    def test_unavailable(self):
        next(i for i in self.menu['items'] if i['id'] == 'pkg-pasta-duo')['available'] = False
        with self.assertRaises(QuoteError): self.quote()

    def test_minimums(self):
        self.request['headcount'] = 19
        with self.assertRaises(QuoteError): self.quote()
        self.request['headcount'] = 40
        self.request['selections'] = [dict(self.request['selections'][0], quantity=1)]
        with self.assertRaises(QuoteError): self.quote()

    def test_delivery_distance(self):
        self.request['delivery_miles'] = 20
        self.assertEqual(self.quote()['delivery_fee_cents'], 6250)
        self.request['delivery_miles'] = 26
        with self.assertRaises(QuoteError): self.quote()

    def test_invalid_distance(self):
        for value in [None, -1, True, 'NaN', 'Infinity']:
            with self.subTest(value=value):
                self.request['delivery_miles'] = value
                with self.assertRaises(QuoteError): self.quote()

    def test_no_default_tax_guess(self):
        self.request['tax_location'] = 'Unknown'
        with self.assertRaises(QuoteError): self.quote()

    def test_pickup_and_unsupported_full_service(self):
        self.request['service_mode'] = 'pickup'
        self.assertEqual(self.quote()['delivery_fee_cents'], 0)
        self.request['service_mode'] = 'full_service'
        with self.assertRaises(QuoteError): self.quote()

    def test_tray_is_one_tray_not_headcount_multiplier(self):
        self.assertEqual(self.quote()['lines'][1]['line_total_cents'], 8369)

    def test_price_snapshot_and_untrusted_price(self):
        old = self.quote()
        self.request['selections'][0]['price'] = .01
        self.assertEqual(self.quote()['total_cents'], 74904)
        next(i for i in self.menu['items'] if i['id'] == 'pkg-pasta-duo')['variants'][0]['price'] = 14
        self.assertEqual(self.quote()['food_subtotal_cents'], 64369)
        self.assertEqual(old['food_subtotal_cents'], 62329)

    def test_sample_full_mix_rejected(self):
        self.rules['meta'].pop('sample')
        with self.assertRaises(QuoteError): self.quote()

    def test_unknown_allergens_and_assumed_servings(self):
        self.request['selections'].append({'item_id':'app-chicken-tenders', 'variant_id':'app-chicken-tenders-half', 'quantity':1})
        result = self.quote()
        self.assertIn('allergen_unknown:app-chicken-tenders', result['flags'])
        self.assertIn('assumed_servings:app-chicken-tenders-half', result['flags'])

    def test_half_up_tax(self):
        self.request['service_mode'] = 'pickup'
        self.request['selections'] = [{'item_id':'pkg-pasta-duo','variant_id':'pkg-pasta-duo-pp','quantity':10}]
        next(i for i in self.menu['items'] if i['id'] == 'pkg-pasta-duo')['variants'][0]['price'] = .01
        self.rules['tax']['rates']['Culver City'] = .05
        self.assertEqual(self.quote()['tax_cents'], 1)

    def test_different_configuration_changes_output(self):
        self.rules['delivery']['fee']['flat_fee'] = 65
        self.assertEqual(self.quote()['total_cents'], 76572)

    def test_invalid_prices(self):
        variant = next(i for i in self.menu['items'] if i['id']=='pkg-pasta-duo')['variants'][0]
        for value in [-1, 'NaN', True, '13.499']:
            with self.subTest(value=value):
                variant['price'] = value
                with self.assertRaises(QuoteError): self.quote()

    def test_malformed_configuration_is_controlled_error(self):
        del self.rules['tax']
        with self.assertRaises(QuoteError): self.quote()

    def test_currency_is_not_silently_relabelled(self):
        self.menu['meta']['currency'] = 'EUR'
        with self.assertRaises(QuoteError): self.quote()

    def test_nonobject_request(self):
        with self.assertRaises(QuoteError):
            calculate_quote(self.menu, self.rules, None)


if __name__ == '__main__':
    unittest.main()
