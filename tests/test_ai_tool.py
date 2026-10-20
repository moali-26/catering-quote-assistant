import copy
import json
import unittest
import test_quote_checks as fixtures
from quote_engine.ai_tool import evaluate_catering_quote


class AIToolTests(unittest.TestCase):
    def setUp(self):
        fixtures.ReadinessTests.setUp(self)
        self.args = {k:v for k,v in self.request.items() if k in
                     ('headcount','event_at','service_mode','address','allergens','selections')}
        self.args['budget_usd'] = '800.00'
        self.context = dict(menu=self.menu,rules=self.rules,capacity=self.capacity,now=self.now,
                            tax_location='Culver City',delivery_miles=15)
    def call(self):
        return evaluate_catering_quote(self.args, **self.context)

    def test_ready_draft_with_budget(self):
        result = self.call()
        self.assertEqual(result['status'],'needs_owner_review')
        self.assertEqual(result['pricing']['total_cents'],74904)
        self.assertTrue(result['budget']['within_budget'])
        self.assertFalse(result['saved']); self.assertFalse(result['can_auto_approve'])
        json.dumps(result)

    def test_over_budget_is_not_approval(self):
        self.args['budget_usd']='700'
        result=self.call()
        self.assertEqual(result['budget']['over_budget_cents'],4904)
        self.assertFalse(result['budget']['within_budget'])
        self.assertEqual(result['status'],'needs_owner_review')

    def test_partial_input_returns_questions(self):
        self.args={'headcount':40}
        result=self.call()
        self.assertEqual(result['status'],'needs_clarification')
        self.assertIn('event_at',result['missing_fields'])
        self.assertIsNone(result['pricing'])

    def test_allergies_must_be_confirmed(self):
        self.args.pop('allergens')
        self.assertIn('allergens',self.call()['missing_fields'])
        self.args['allergens']=[]
        self.assertEqual(self.call()['status'],'needs_owner_review')

    def test_server_facts_not_guessed(self):
        self.context['delivery_miles']=None
        self.assertEqual(self.call()['status'],'needs_server_context')

    def test_reject_privileged_and_pricing_fields(self):
        for key in ('owner_id','customer_id','price','menu','tax_location','delivery_miles','status'):
            with self.subTest(key=key):
                args=dict(self.args); args[key]='forged'
                self.assertEqual(evaluate_catering_quote(args,**self.context)['status'],'invalid_input')
        self.args['selections'][0]['price']=0.01
        self.assertEqual(self.call()['status'],'invalid_input')

    def test_known_allergen_conflict(self):
        self.args['selections'].append({'item_id':'side-coleslaw','variant_id':'side-coleslaw-half','quantity':1})
        result=self.call()
        self.assertEqual(result['status'],'blocked')
        self.assertIn('allergen_conflict:side-coleslaw:peanut',result['blocking_reasons'])

    def test_unrecognized_allergen(self):
        self.args['allergens']=['nuts']
        self.assertEqual(self.call()['status'],'blocked')

    def test_invalid_values_controlled(self):
        for field,value in [('headcount',True),('event_at',42),('selections',None),('budget_usd','NaN')]:
            with self.subTest(field=field):
                args=dict(self.args);args[field]=value
                self.assertEqual(evaluate_catering_quote(args,**self.context)['status'],'invalid_input')

    def test_invalid_datetime_code(self):
        self.args['event_at']='Friday'
        self.assertEqual(self.call()['error_code'],'invalid_event_datetime')

    def test_minimum_failure_actionable(self):
        self.args['headcount']=1
        self.assertEqual(self.call()['error_code'],'headcount_below_minimum')

    def test_bad_config_does_not_leak_details(self):
        self.rules.pop('tax')
        result=self.call()
        self.assertEqual(result['status'],'cannot_evaluate')
        self.assertEqual(result['error_code'],'invalid_request_or_configuration')
        self.assertIsNone(result['pricing'])

    def test_no_mutation_or_raw_request_in_output(self):
        before=copy.deepcopy((self.args,self.context))
        result=self.call()
        self.assertEqual(before,(self.args,self.context))
        self.assertNotIn('rules_assumptions',result['pricing'])
        self.assertNotIn(self.args['address'],json.dumps(result))

    def test_budget_optional(self):
        self.args.pop('budget_usd')
        self.assertIsNone(self.call()['budget'])
