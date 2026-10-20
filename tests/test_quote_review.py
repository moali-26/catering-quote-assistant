import unittest
import test_quote_pricing as fixtures
from quote_engine import QuoteError

class PricingReviewTests(unittest.TestCase):
    setUp = fixtures.PricingTests.setUp
    quote = fixtures.PricingTests.quote

    def test_nested_assumptions_are_independent_snapshot(self):
        self.rules['assumptions'] = [{'note': 'Original policy'}]
        result = self.quote()
        self.rules['assumptions'][0]['note'] = 'Changed policy'
        self.assertEqual(result['rules_assumptions'][0]['note'], 'Original policy')

    def test_invalid_guest_minimum_configuration_rejected(self):
        for value in (-1, True, 1.5):
            self.rules['service_modes']['delivery']['order_minimum']['guest_count'] = value
            with self.subTest(value=value), self.assertRaises(QuoteError): self.quote()
