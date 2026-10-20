import copy
import json
from datetime import datetime
from pathlib import Path
import unittest
from quote_engine import (QuoteError, create_quote, revise_quote, approve_quote, respond_to_quote)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parents[1] / 'data/sample'
        self.menu = json.loads((folder/'menu.json').read_text())
        self.rules = json.loads((folder/'rules.json').read_text())
        self.capacity = json.loads((folder/'capacity.json').read_text())
        self.request = dict(json.loads((folder/'inquiries.json').read_text())['pricing_example'],
                            headcount=40, event_at='2026-10-23T12:00:00-07:00', address='Demo office', allergens=[])
        self.now = datetime.fromisoformat('2026-10-18T12:00:00-07:00')
        self.quote = create_quote(self.menu, self.rules, self.request, owner_id='owner1',
                                  customer_id='customer1', now=self.now, capacity=self.capacity)

    def approve(self, record=None, **overrides):
        record = record or self.quote
        args = dict(actor_id='owner1', expected_revision=record['revision'], now=self.now,
                    capacity=self.capacity,
                    acknowledged_reviews=record['versions'][-1]['readiness']['review_reasons'])
        args.update(overrides)
        return approve_quote(record, self.menu, self.rules, **args)

    def respond(self, record, **overrides):
        args = dict(actor_id='customer1', expected_revision=record['revision'], now=self.now, decision='accept')
        args.update(overrides)
        return respond_to_quote(record, **args)

    def revise(self, record, **overrides):
        args = dict(actor_id='customer1', expected_revision=record['revision'], now=self.now, capacity=self.capacity)
        args.update(overrides)
        return revise_quote(record, self.menu, self.rules, self.request, **args)

    def test_happy_path_and_json(self):
        approved = self.approve()
        accepted = self.respond(approved)
        self.assertEqual(accepted['versions'][-1]['status'], 'customer_accepted')
        self.assertEqual(accepted['revision'], 3)
        self.assertEqual(json.loads(json.dumps(accepted)), accepted)
        self.assertEqual(self.quote['versions'][0]['status'], 'draft')

    def test_decline(self):
        self.assertEqual(self.respond(self.approve(), decision='decline')['versions'][-1]['status'], 'customer_declined')

    def test_wrong_actors(self):
        approved = self.approve()
        with self.assertRaises(QuoteError): self.approve(actor_id='customer1')
        with self.assertRaises(QuoteError): self.respond(approved, actor_id='owner1')
        with self.assertRaises(QuoteError): self.revise(self.quote, actor_id='stranger')

    def test_stale_updates(self):
        with self.assertRaises(QuoteError): self.approve(expected_revision=0)
        with self.assertRaises(QuoteError): self.respond(self.approve(), expected_revision=1)
        with self.assertRaises(QuoteError): self.revise(self.quote, expected_revision=True)

    def test_transition_guards(self):
        approved = self.approve()
        accepted = self.respond(approved)
        with self.assertRaises(QuoteError): self.respond(self.quote)
        with self.assertRaises(QuoteError): self.approve(approved)
        with self.assertRaises(QuoteError): self.respond(accepted)
        with self.assertRaises(QuoteError): self.respond(approved, decision='pay')

    def test_acknowledgment_required(self):
        with self.assertRaises(QuoteError): self.approve(acknowledged_reviews=[])

    def test_recheck_capacity_before_approval(self):
        self.capacity['exceptions']['2026-10-23']['status'] = 'full'
        with self.assertRaises(QuoteError): self.approve()

    def test_recheck_notice_before_approval(self):
        with self.assertRaises(QuoteError):
            self.approve(now=datetime.fromisoformat('2026-10-23T11:00:00-07:00'))

    def test_changed_price_needs_revision(self):
        self.rules['tax']['rates']['Culver City'] = 0.12
        with self.assertRaises(QuoteError): self.approve()
        revised = self.revise(self.quote)
        self.assertNotEqual(revised['versions'][0]['readiness']['pricing']['total_cents'],
                            revised['versions'][1]['readiness']['pricing']['total_cents'])
        self.assertEqual(self.approve(revised)['versions'][-1]['status'], 'owner_approved')

    def test_revision_preserves_accepted_history(self):
        accepted = self.respond(self.approve())
        old = copy.deepcopy(accepted)
        revised = self.revise(accepted)
        self.assertEqual(revised['versions'][0], accepted['versions'][0])
        self.assertEqual(revised['versions'][1]['status'], 'draft')
        self.assertIsNone(revised['versions'][1]['approval'])
        self.assertIsNone(revised['versions'][1]['response'])
        revised['versions'][0]['request']['address'] = 'changed'
        self.assertEqual(accepted, old)

    def test_missing_request_cannot_approve(self):
        self.request.pop('event_at')
        with self.assertRaises(QuoteError): self.approve(self.revise(self.quote))

    def test_past_event_cannot_accept(self):
        with self.assertRaises(QuoteError):
            self.respond(self.approve(), now=datetime.fromisoformat('2026-10-24T12:00:00-07:00'))

    def test_clock_and_identity_validation(self):
        with self.assertRaises(QuoteError): self.approve(now=datetime(2026,10,18))
        with self.assertRaises(QuoteError): self.approve(now=datetime.fromisoformat('2026-10-17T12:00:00-07:00'))
        with self.assertRaises(QuoteError):
            create_quote(self.menu,self.rules,self.request,owner_id='',customer_id='c',now=self.now)

    def test_acknowledgment_cannot_bypass_unrecognized_allergen(self):
        self.request['allergens'] = ['nuts']
        revised = self.revise(self.quote)
        with self.assertRaises(QuoteError):
            self.approve(revised)
