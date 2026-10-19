"""Pure quote transitions. Records and actor IDs must come from trusted server storage/auth."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from .checks import check_quote_readiness
from .pricing import QuoteError


def _stamp(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise QuoteError('now must be a timezone-aware server datetime')
    return now.astimezone(timezone.utc).isoformat()


def _identity(value):
    if not isinstance(value, str) or not value.strip():
        raise QuoteError('owner and customer IDs must be nonempty strings')
    return value


def _version(menu, rules, request, capacity, now, number):
    return {'version': number, 'status': 'draft', 'created_at': _stamp(now),
            'request': deepcopy(request),
            'readiness': check_quote_readiness(menu, rules, request, now=now, capacity=capacity),
            'approval': None, 'response': None}


def create_quote(menu, rules, request, *, owner_id, customer_id, now, capacity=None):
    """Create using server-selected menu/rules and server-resolved participant IDs."""
    return {'quote_id': str(uuid4()), 'owner_id': _identity(owner_id),
            'customer_id': _identity(customer_id), 'revision': 1,
            'updated_at': _stamp(now),
            'versions': [_version(menu, rules, request, capacity, now, 1)]}


def _edit(record, actor_id, expected_revision, now, allowed):
    if actor_id not in allowed:
        raise QuoteError('actor is not authorized for this action')
    if type(expected_revision) is not int or expected_revision != record['revision']:
        raise QuoteError('stale quote: reload before making changes')
    stamp = _stamp(now)
    if datetime.fromisoformat(stamp) < datetime.fromisoformat(record['updated_at']):
        raise QuoteError('server time cannot precede the last change')
    result = deepcopy(record)
    result['revision'] += 1
    result['updated_at'] = stamp
    return result


def revise_quote(record, menu, rules, request, *, actor_id, expected_revision, now, capacity=None):
    """Explicitly reprice into a new draft, preserving all previous versions."""
    result = _edit(record, actor_id, expected_revision, now,
                   [record['owner_id'], record['customer_id']])
    result['versions'].append(_version(menu, rules, request, capacity, now,
                                      len(result['versions']) + 1))
    return result


def approve_quote(record, menu, rules, *, actor_id, expected_revision, now,
                  acknowledged_reviews, capacity=None):
    """Recheck with current server data; changed pricing requires an explicit revision."""
    result = _edit(record, actor_id, expected_revision, now, [record['owner_id']])
    current = result['versions'][-1]
    if current['status'] != 'draft':
        raise QuoteError('only a draft can be approved')
    ready = check_quote_readiness(menu, rules, current['request'], now=now, capacity=capacity)
    if ready['status'] != 'needs_owner_review' or ready['blocking_reasons'] or ready['missing_fields']:
        raise QuoteError('resolve missing information or blocking reasons before approval')
    if ready['pricing'] != current['readiness']['pricing']:
        raise QuoteError('menu or pricing changed: create a revised draft first')
    if not isinstance(acknowledged_reviews, list) or any(not isinstance(x, str) for x in acknowledged_reviews):
        raise QuoteError('acknowledged_reviews must be a list of review codes')
    if not set(ready['review_reasons']).issubset(acknowledged_reviews):
        raise QuoteError('owner must explicitly acknowledge every review reason')
    current['readiness'] = ready
    current['status'] = 'owner_approved'
    current['approval'] = {'actor_id': actor_id, 'at': result['updated_at'],
                           'acknowledged_reviews': sorted(set(acknowledged_reviews))}
    return result


def respond_to_quote(record, *, actor_id, expected_revision, now, decision):
    """Record customer intent only. Acceptance does not book capacity or charge money."""
    result = _edit(record, actor_id, expected_revision, now, [record['customer_id']])
    current = result['versions'][-1]
    if current['status'] != 'owner_approved':
        raise QuoteError('only an owner-approved quote can receive a response')
    if decision not in ('accept', 'decline'):
        raise QuoteError('decision must be accept or decline')
    if datetime.fromisoformat(current['request']['event_at']) <= now:
        raise QuoteError('event has passed: request a new quote')
    current['status'] = 'customer_accepted' if decision == 'accept' else 'customer_declined'
    current['response'] = {'actor_id': actor_id, 'at': result['updated_at'], 'decision': decision}
    return result
