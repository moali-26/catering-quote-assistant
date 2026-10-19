import copy
import json
from pathlib import Path
from datetime import datetime
import unittest
from quote_engine import QuoteError, check_quote_readiness


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parents[1] / 'data/sample'
        self.menu=json.loads((folder/'menu.json').read_text())
        self.rules=json.loads((folder/'rules.json').read_text())
        self.capacity=json.loads((folder/'capacity.json').read_text())
        self.request=dict(json.loads((folder/'inquiries.json').read_text())['pricing_example'],
                          headcount=40,event_at='2026-10-23T12:00:00-07:00',address='Demo office',allergens=['peanut','tree_nuts'])
        self.now=datetime.fromisoformat('2026-10-18T12:00:00-07:00')
    def check(self):
        return check_quote_readiness(self.menu,self.rules,self.request,now=self.now,capacity=self.capacity)
    def test_normal_is_review_not_approval(self):
        result=self.check()
        self.assertEqual(result['status'],'needs_owner_review')
        self.assertEqual(result['pricing']['total_cents'],74904)
        self.assertFalse(result['can_auto_approve'])
        self.assertIn('synthetic_capacity_requires_owner_confirmation',result['review_reasons'])
    def test_missing(self):
        for key in ['event_at','headcount','address']:
            with self.subTest(key=key):
                req=dict(self.request);req.pop(key)
                r=check_quote_readiness(self.menu,self.rules,req,now=self.now)
                self.assertEqual(r['status'],'needs_clarification')
                self.assertIn(key,r['missing_fields']);self.assertIsNone(r['pricing'])
    def test_full_day(self):
        self.request['event_at']='2026-10-24T12:00:00-07:00'
        self.assertIn('capacity_conflict',self.check()['blocking_reasons'])
    def test_short_notice(self):
        self.request['event_at']='2026-10-19T12:00:00-07:00'
        self.assertIn('insufficient_lead_time',self.check()['blocking_reasons'])
    def test_notice_boundary(self):
        self.request['event_at']='2026-10-20T12:00:00-07:00'
        self.assertNotIn('insufficient_lead_time',self.check()['blocking_reasons'])
    def test_past(self):
        self.request['event_at']='2026-10-17T12:00:00-07:00'
        self.assertIn('event_in_past',self.check()['blocking_reasons'])
    def test_timezone_required(self):
        self.request['event_at']='2026-10-23T12:00:00'
        with self.assertRaises(QuoteError):self.check()
    def test_naive_clock(self):
        self.now=datetime(2026,10,18)
        with self.assertRaises(QuoteError):self.check()
    def test_pacific_calendar_date(self):
        self.request['event_at']='2026-10-25T01:00:00+00:00'
        self.assertIn('capacity_conflict',self.check()['blocking_reasons'])
    def test_capacity_remaining_guests(self):
        self.capacity['exceptions']['2026-10-23']['booked_guests']=70
        self.assertIn('capacity_conflict',self.check()['blocking_reasons'])
    def test_known_allergen_conflict(self):
        self.request['selections'].append({'item_id':'side-coleslaw','variant_id':'side-coleslaw-half','quantity':1})
        self.assertIn('allergen_conflict:side-coleslaw:peanut',self.check()['blocking_reasons'])
    def test_unknown_allergen_not_silently_cleared(self):
        self.request['allergens']=['nuts']
        self.assertIn('unrecognized_allergen_requires_clarification',self.check()['review_reasons'])
    def test_no_capacity_is_review(self):
        self.capacity=None
        self.assertIn('capacity_not_checked',self.check()['review_reasons'])
    def test_no_mutation(self):
        before=copy.deepcopy((self.request,self.capacity));self.check()
        self.assertEqual(before,(self.request,self.capacity))
    def test_closed_day(self):
        self.request['event_at']='2026-11-26T12:00:00-08:00'
        self.assertIn('capacity_conflict',self.check()['blocking_reasons'])
    def test_wrong_dataset(self):
        self.capacity['meta']['dataset_id']='other'
        with self.assertRaises(QuoteError):self.check()
