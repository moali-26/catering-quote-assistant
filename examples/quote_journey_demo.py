"""Offline persisted journey; no model, Auth, or Supabase credentials required."""
from datetime import datetime
from pathlib import Path
import json
import tempfile
from quote_engine.service import QuoteService
from quote_engine.storage import SQLiteQuoteStore


def main():
    folder=Path(__file__).resolve().parents[1]/'data/sample'
    menu,rules,capacity,inquiries=[json.loads((folder/name).read_text()) for name in
                                  ('menu.json','rules.json','capacity.json','inquiries.json')]
    request=dict(inquiries['pricing_example'],headcount=40,event_at='2026-10-23T12:00:00-07:00',
                 address='Demo office',allergens=[])
    now=datetime.fromisoformat('2026-10-18T12:00:00-07:00')
    def context(owner,request):
        # Fixed sample scenario ONLY; production must resolve for the actual address/business.
        return dict(menu=menu,rules=rules,capacity=capacity,tax_location='Culver City',delivery_miles=15)
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'quotes.sqlite3'
        service=QuoteService(SQLiteQuoteStore(path),context_for=context,clock=lambda:now)
        draft=service.submit(request,actor_id='demo-customer',owner_id='demo-owner')
        print('1. Submitted:',draft['status'],draft['pricing']['amounts']['total_cents']['display'])
        owner=service.detail(draft['quote_id'],actor_id='demo-owner')
        approved=service.approve(draft['quote_id'],actor_id='demo-owner',expected_revision=1,
                                 acknowledged_reviews=owner['approval_requires_acknowledgment'])
        print('2. Owner reviewed demo flags and approved:',approved['status'])
        reopened=QuoteService(SQLiteQuoteStore(path),context_for=context,clock=lambda:now)
        customer=reopened.detail(draft['quote_id'],actor_id='demo-customer')
        print('3. Customer reopened saved quote; accept enabled:',customer['actions']['accept'])
        accepted=reopened.respond(draft['quote_id'],actor_id='demo-customer',expected_revision=2,decision='accept')
        print('4. Customer response saved:',accepted['status'])
        print('5. Owner inbox:',json.dumps(service.list_quotes(actor_id='demo-owner',workspace='owner'),indent=2))
    print('Temporary demo database removed. This was not a live AI or login demo.')


if __name__=='__main__': main()
