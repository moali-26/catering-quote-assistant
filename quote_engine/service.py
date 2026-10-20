"""Server action orchestration. Framework/auth/database-provider independent.

The application verifies Auth and business routing before calling this service.
Do not bind these methods directly to arbitrary browser-provided keyword args.
"""
from .checks import check_quote_readiness
from .workflow import create_quote, revise_quote, approve_quote, respond_to_quote
from .presentation import quote_view, quote_card
from .pricing import QuoteError


class QuoteService:
    def __init__(self, store, *, context_for, clock):
        """context_for(owner_id, request) loads trusted menu/rules/capacity.

        It must resolve/validate delivery miles and tax location for the current
        address before returning a context; request values are not authoritative.
        Return keys menu/rules/capacity and tax_location/delivery_miles.
        clock returns an aware server datetime. Store must support atomic save.
        """
        self.store=store
        self.context_for=context_for
        self.clock=clock

    def _context(self, owner_id, request):
        from copy import deepcopy
        request=deepcopy(request)
        context=self.context_for(owner_id,deepcopy(request))
        request['tax_location']=context.get('tax_location')
        request['delivery_miles']=context.get('delivery_miles')
        return context, request

    def submit(self, request, *, actor_id, owner_id):
        """owner_id comes from trusted business routing; actor is verified customer."""
        if not isinstance(request,dict) or 'allergens' not in request:
            raise QuoteError('confirm customer allergies before submission')
        context,request=self._context(owner_id,request)
        now=self.clock()
        ready=check_quote_readiness(context['menu'],context['rules'],request,now=now,capacity=context.get('capacity'))
        if ready['status'] != 'needs_owner_review':
            raise QuoteError('resolve missing information or blockers before submission')
        record=create_quote(context['menu'],context['rules'],request,owner_id=owner_id,
                            customer_id=actor_id,now=now,capacity=context.get('capacity'))
        self.store.insert(record,actor_id=actor_id)
        return quote_view(record,actor_id=actor_id,now=now)

    def detail(self, quote_id, *, actor_id):
        record=self.store.get(quote_id,actor_id=actor_id)
        return quote_view(record,actor_id=actor_id,now=self.clock())

    def list_quotes(self, *, actor_id, workspace, limit=50, offset=0):
        records=self.store.list_quotes(actor_id=actor_id,workspace=workspace,limit=limit,offset=offset)
        now=self.clock()
        return [quote_card(record,actor_id=actor_id,now=now) for record in records]

    def approve(self, quote_id, *, actor_id, expected_revision, acknowledged_reviews):
        record=self.store.get(quote_id,actor_id=actor_id)
        if actor_id != record['owner_id']:
            raise QuoteError('only the owner can approve')
        context,request=self._context(record['owner_id'],record['versions'][-1]['request'])
        # Changed delivery/tax context requires revision, not a hidden price update.
        old=record['versions'][-1]['request']
        if any(request.get(k) != old.get(k) for k in ('tax_location','delivery_miles')):
            raise QuoteError('delivery or tax context changed: revise the quote first')
        now=self.clock()
        updated=approve_quote(record,context['menu'],context['rules'],actor_id=actor_id,
                              expected_revision=expected_revision,now=now,
                              acknowledged_reviews=acknowledged_reviews,capacity=context.get('capacity'))
        self.store.save(updated,actor_id=actor_id,expected_revision=expected_revision)
        return quote_view(updated,actor_id=actor_id,now=now)

    def revise(self, quote_id, request, *, actor_id, expected_revision):
        record=self.store.get(quote_id,actor_id=actor_id)
        if not isinstance(request,dict) or 'allergens' not in request:
            raise QuoteError('confirm customer allergies before revision')
        context,request=self._context(record['owner_id'],request)
        now=self.clock()
        updated=revise_quote(record,context['menu'],context['rules'],request,actor_id=actor_id,
                             expected_revision=expected_revision,now=now,capacity=context.get('capacity'))
        self.store.save(updated,actor_id=actor_id,expected_revision=expected_revision)
        return quote_view(updated,actor_id=actor_id,now=now)

    def respond(self, quote_id, *, actor_id, expected_revision, decision):
        record=self.store.get(quote_id,actor_id=actor_id)
        now=self.clock()
        updated=respond_to_quote(record,actor_id=actor_id,expected_revision=expected_revision,now=now,decision=decision)
        self.store.save(updated,actor_id=actor_id,expected_revision=expected_revision)
        return quote_view(updated,actor_id=actor_id,now=now)
