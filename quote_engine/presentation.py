"""Framework-neutral data for quote detail and list screens; no HTML rendering."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from .pricing import QuoteError
from .storage import QuoteNotFound

LABELS = {'draft':'Pending owner review', 'owner_approved':'Ready for your response',
          'customer_accepted':'Accepted', 'customer_declined':'Declined'}


def money(cents):
    return f'${Decimal(cents) / 100:,.2f}'


def quote_view(record, *, actor_id, now):
    if actor_id not in (record['owner_id'], record['customer_id']):
        raise QuoteNotFound('quote not found')
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise QuoteError('now must be timezone-aware')
    version = record['versions'][-1]
    ready = version['readiness']
    pricing = ready['pricing']
    event = version['request'].get('event_at')
    try:
        parsed = datetime.fromisoformat(event) if event else None
        valid_event = parsed is not None and parsed.tzinfo is not None and parsed.utcoffset() is not None
    except (ValueError, TypeError):
        parsed, valid_event = None, False
    expired = bool(valid_event and parsed <= now)
    status = version['status']
    owner = actor_id == record['owner_id']
    customer = actor_id == record['customer_id']
    can_approve = (owner and status == 'draft' and valid_event and not expired
                   and ready['status'] == 'needs_owner_review'
                   and not ready['blocking_reasons'] and not ready['missing_fields'])
    can_respond = customer and status == 'owner_approved' and valid_event and not expired
    fields = ('headcount','event_at','service_mode','address','allergens','dietary_needs','budget_usd','customer_notes')
    result = {'quote_id':record['quote_id'], 'revision':record['revision'],
              'version':version['version'], 'status':status,
              'status_label':('Awaiting customer response' if owner and status == 'owner_approved' else LABELS[status]),
              'event_passed':expired,
              'event':deepcopy({key:version['request'][key] for key in fields if key in version['request']}),
              'readiness':{key:deepcopy(ready[key]) for key in ('status','missing_fields','blocking_reasons','review_reasons')},
              'actions':{'revise':True, 'approve':bool(can_approve), 'accept':bool(can_respond), 'decline':bool(can_respond)},
              'approval_requires_acknowledgment':deepcopy(ready['review_reasons']) if can_approve else [],
              'pricing':None,
              'history':[{'version':v['version'],'status':v['status'],
                          'total_cents':v['readiness']['pricing']['total_cents'] if v['readiness']['pricing'] else None}
                         for v in record['versions']],
              'notice':'Quote acceptance is not payment or a confirmed booking. Actions are rechecked by the server.'}
    if pricing:
        lines=[]
        for line in pricing['lines']:
            row=deepcopy(line)
            row['unit_price_display']=money(line['unit_price_cents'])
            row['line_total_display']=money(line['line_total_cents'])
            lines.append(row)
        keys=('food_subtotal_cents','delivery_fee_cents','service_charge_cents','staffing_fee_cents','tax_cents','total_cents')
        result['pricing']={'currency':pricing['currency'],'lines':lines,
                           'amounts':{k:{'cents':pricing[k],'display':money(pricing[k])} for k in keys}}
    return result


def quote_card(record, *, actor_id, now):
    view=quote_view(record,actor_id=actor_id,now=now)
    return {key:view[key] for key in ('quote_id','revision','version','status','status_label','event_passed')} | {
        'event_at':view['event'].get('event_at'), 'headcount':view['event'].get('headcount'),
        'total':view['pricing']['amounts']['total_cents'] if view['pricing'] else None}
