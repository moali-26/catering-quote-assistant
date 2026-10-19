import copy
import tempfile
from pathlib import Path
from datetime import datetime
import unittest
import test_quote_checks as fixtures
from quote_engine import QuoteError
from quote_engine.storage import SQLiteQuoteStore, QuoteNotFound
from quote_engine.service import QuoteService
from quote_engine.presentation import quote_view


class ServiceTests(unittest.TestCase):
    def setUp(self):
        fixtures.ReadinessTests.setUp(self)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'quotes.sqlite3'
        self.store=SQLiteQuoteStore(self.path)
        self.context_calls=[]
        def context(owner,request):
            self.context_calls.append((owner,request))
            return dict(menu=self.menu,rules=self.rules,capacity=self.capacity,tax_location='Culver City',delivery_miles=15)
        self.context=context
        self.service=QuoteService(self.store,context_for=context,clock=lambda:self.now)

    def submit(self):
        return self.service.submit(self.request,actor_id='customer',owner_id='owner')

    def approve(self,view):
        return self.service.approve(view['quote_id'],actor_id='owner',expected_revision=view['revision'],
                                    acknowledged_reviews=view['readiness']['review_reasons'])

    def test_full_journey_with_reopen(self):
        draft=self.submit()
        self.assertFalse(draft['actions']['approve']);self.assertFalse(draft['actions']['accept'])
        self.assertEqual(draft['pricing']['amounts']['total_cents']['display'],'$749.04')
        owner=self.service.detail(draft['quote_id'],actor_id='owner')
        self.assertTrue(owner['actions']['approve'])
        self.approve(owner)
        reopened=QuoteService(SQLiteQuoteStore(self.path),context_for=self.context,clock=lambda:self.now)
        customer=reopened.detail(draft['quote_id'],actor_id='customer')
        self.assertTrue(customer['actions']['accept'])
        accepted=reopened.respond(draft['quote_id'],actor_id='customer',expected_revision=2,decision='accept')
        self.assertEqual(accepted['status'],'customer_accepted')
        self.assertFalse(accepted['actions']['accept'])
        self.assertEqual(self.service.list_quotes(actor_id='owner',workspace='owner')[0]['status'],'customer_accepted')

    def test_failed_submission_not_saved(self):
        self.request.pop('address')
        with self.assertRaises(QuoteError):self.submit()
        self.assertEqual(self.service.list_quotes(actor_id='owner',workspace='owner'),[])

    def test_unconfirmed_allergies_not_submitted(self):
        self.request.pop('allergens')
        with self.assertRaises(QuoteError):self.submit()

    def test_server_overrides_client_tax_distance(self):
        self.request['delivery_miles']=0;self.request['tax_location']='forged'
        self.assertEqual(self.submit()['pricing']['amounts']['total_cents']['cents'],74904)
        self.assertEqual(self.request['tax_location'],'forged')

    def test_wrong_actor_cannot_read_or_approve(self):
        draft=self.submit()
        with self.assertRaises(QuoteNotFound):self.service.detail(draft['quote_id'],actor_id='outsider')
        with self.assertRaises(QuoteError):self.service.approve(draft['quote_id'],actor_id='customer',expected_revision=1,acknowledged_reviews=[])
        self.assertEqual(self.service.list_quotes(actor_id='outsider',workspace='customer'),[])

    def test_stale_response_does_not_save(self):
        draft=self.submit();self.approve(draft)
        with self.assertRaises(QuoteError):self.service.respond(draft['quote_id'],actor_id='customer',expected_revision=1,decision='accept')
        self.assertEqual(self.service.detail(draft['quote_id'],actor_id='customer')['status'],'owner_approved')

    def test_revise_retains_old_total_and_resets_actions(self):
        draft=self.submit();self.approve(draft)
        request=copy.deepcopy(self.request);request['selections'][0]['quantity']=45
        revised=self.service.revise(draft['quote_id'],request,actor_id='customer',expected_revision=2)
        self.assertEqual(len(revised['history']),2)
        self.assertEqual(revised['history'][0]['total_cents'],74904)
        self.assertFalse(revised['actions']['accept'])
        self.assertNotEqual(revised['pricing']['amounts']['total_cents']['cents'],74904)

    def test_menu_change_requires_revision(self):
        draft=self.submit()
        next(i for i in self.menu['items'] if i['id']=='pkg-pasta-duo')['variants'][0]['price']=14
        with self.assertRaises(QuoteError):self.approve(draft)
        self.assertEqual(self.service.detail(draft['quote_id'],actor_id='owner')['revision'],1)

    def test_event_passed_disables_response(self):
        draft=self.submit();self.approve(draft)
        self.now=datetime.fromisoformat('2026-10-24T12:00:00-07:00')
        view=self.service.detail(draft['quote_id'],actor_id='customer')
        self.assertTrue(view['event_passed']);self.assertFalse(view['actions']['accept'])

    def test_view_does_not_mutate_or_expose_internal_rules(self):
        draft=self.submit();record=self.store.get(draft['quote_id'],actor_id='customer')
        before=copy.deepcopy(record)
        view=quote_view(record,actor_id='owner',now=self.now)
        view['pricing']['lines'][0]['name']='changed'
        self.assertEqual(before,record)
        self.assertNotIn('rules_assumptions',view['pricing'])
        self.assertNotIn('customer_id',view)

    def test_partial_revision_can_be_displayed(self):
        draft=self.submit()
        request=dict(self.request);request.pop('headcount');request['event_at']='Friday'
        revised=self.service.revise(draft['quote_id'],request,actor_id='customer',expected_revision=1)
        self.assertIsNone(revised['pricing'])
        self.assertEqual(revised['readiness']['status'],'needs_clarification')

    def test_changed_delivery_context_blocks_approval(self):
        draft=self.submit()
        self.service.context_for=lambda owner,request:dict(menu=self.menu,rules=self.rules,capacity=self.capacity,
                                                          tax_location='Culver City',delivery_miles=20)
        with self.assertRaises(QuoteError):self.approve(draft)
