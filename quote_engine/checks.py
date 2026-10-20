"""Preflight checks with an injected clock; never books capacity or approves."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .pricing import QuoteError, calculate_quote


MAX_CUSTOMER_NOTES = 2000


def validate_customer_notes(request):
    """Optional plain text; never authoritative pricing or allergen data."""
    if 'customer_notes' in request:
        notes = request['customer_notes']
        if not isinstance(notes, str) or len(notes) > MAX_CUSTOMER_NOTES or '\x00' in notes:
            raise QuoteError('customer_notes must be text of at most 2000 characters')


def check_quote_readiness(menu, rules, request, *, now, capacity=None):
    """Return controlled errors for invalid data/configuration, never approval."""
    try:
        return _check_quote_readiness(menu, rules, request, now=now, capacity=capacity)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise QuoteError('malformed readiness input or server configuration') from exc


def _check_quote_readiness(menu, rules, request, *, now, capacity=None):
    """Return clarification/block/review reasons separately from price arithmetic.

    event_at must be timezone-aware ISO 8601. now is an aware datetime from the
    server. Address is explicitly required for delivery. Calendar date is Pacific.
    Optional capacity is a snapshot, not a reservation or concurrency-safe booking.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise QuoteError('now must be a timezone-aware server datetime')
    if not all(isinstance(v, dict) for v in (menu, rules, request)):
        raise QuoteError('menu, rules, request must be objects')
    validate_customer_notes(request)
    if capacity is not None and not isinstance(capacity, dict):
        raise QuoteError('capacity must be an object')
    missing, blockers, review = [], [], []
    for key in ('headcount', 'event_at', 'service_mode', 'tax_location', 'selections'):
        if request.get(key) is None or request.get(key) == '' or request.get(key) == []:
            missing.append(key)
    if request.get('service_mode') == 'delivery':
        if not isinstance(request.get('address'), str) or not request['address'].strip():
            missing.append('address')
        if request.get('delivery_miles') is None:
            missing.append('delivery_miles')
    quote = None
    if not missing:
        quote = calculate_quote(menu, rules, request)
        try:
            event = datetime.fromisoformat(request['event_at'])
        except (TypeError, ValueError) as exc:
            raise QuoteError('event_at must be a valid ISO datetime') from exc
        if event.tzinfo is None or event.utcoffset() is None:
            raise QuoteError('event_at requires a timezone offset')
        mode = rules['service_modes'][request['service_mode']]
        hours = mode.get('lead_time_hours')
        if type(hours) not in (int, float) or hours < 0 or hours != hours or hours == float('inf'):
            raise QuoteError('valid lead_time_hours configuration required')
        elapsed = (event.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()/3600
        if elapsed < 0:
            blockers.append('event_in_past')
        elif elapsed < hours:
            blockers.append('insufficient_lead_time')
        if capacity is None:
            review.append('capacity_not_checked')
        else:
            if capacity.get('meta', {}).get('dataset_id') != menu['meta']['dataset_id']:
                raise QuoteError('capacity dataset ID mismatch')
            if capacity.get('meta', {}).get('synthetic') is True:
                review.append('synthetic_capacity_requires_owner_confirmation')
            day = event.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
            defaults = capacity.get('defaults', {})
            entry = dict(defaults)
            if day in capacity.get('closed_dates', {}):
                entry['status'] = 'closed'
            entry.update(capacity.get('exceptions', {}).get(day, {}))
            if entry.get('status') not in ('open', 'full', 'closed'):
                raise QuoteError('invalid capacity status')
            for key in ('max_events_per_day', 'max_guests_per_day', 'max_guests_per_event'):
                if type(entry.get(key)) is not int or entry[key] < 1:
                    raise QuoteError('invalid capacity limit')
            for key in ('booked_events', 'booked_guests'):
                if type(entry.get(key, 0)) is not int or entry.get(key, 0) < 0:
                    raise QuoteError('invalid booked capacity')
            if (entry['status'] != 'open'
                or entry.get('booked_events', 0) >= entry['max_events_per_day']
                or request['headcount'] > entry['max_guests_per_event']
                or entry.get('booked_guests', 0) + request['headcount'] > entry['max_guests_per_day']):
                blockers.append('capacity_conflict')
        allergens = request.get('allergens', [])
        if not isinstance(allergens, list) or any(not isinstance(a, str) for a in allergens):
            raise QuoteError('allergens must be a list of normalized allergen names')
        if not set(allergens).issubset(set(menu.get('allergen_definitions', []))):
            review.append('unrecognized_allergen_requires_clarification')
            blockers.append('unrecognized_allergen_requires_clarification')
        items = {item['id']:item for item in menu['items']}
        for line in quote['lines']:
            item = items[line['item_id']]
            for allergen in sorted(set(allergens).intersection(item.get('allergens', []))):
                blockers.append(f"allergen_conflict:{item['id']}:{allergen}")
        review.extend(quote['flags'])
        review.extend(['owner_confirmation_required', 'portion_and_dietary_review_required'])
    return {'status': 'needs_clarification' if missing else 'blocked' if blockers else 'needs_owner_review',
            'missing_fields': sorted(set(missing)), 'blocking_reasons': sorted(set(blockers)),
            'review_reasons': sorted(set(review)), 'pricing': quote,
            'can_auto_approve': False}
