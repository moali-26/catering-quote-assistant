"""Read-only, provider-neutral tool boundary for B's conversation service."""
from .checks import check_quote_readiness, validate_customer_notes, MAX_CUSTOMER_NOTES
from .pricing import QuoteError, number, cents

TOOL_DEFINITION = {
    'name': 'evaluate_catering_quote',
    'description': ('Evaluate selected menu quantities against current prices and event rules. '
                    'Call again after changing selections. Returns a draft, never approval, '
                    'a saved request, payment, or reservation. Ask for unknown customer details; '
                    'do not invent item IDs, dates, allergies, or quantities.'),
    'input_schema': {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'customer_notes': {'type': 'string', 'maxLength': MAX_CUSTOMER_NOTES,
                               'description': 'Complete current customer-confirmed package choices and special requests, labeled by dish. Preserve earlier choices unless changed; use an empty string to clear. Notes require owner review and never change prices or allergy checks.'},
            'headcount': {'type': 'integer', 'minimum': 1},
            'event_at': {'type': 'string', 'description': 'Confirmed ISO datetime with timezone offset.'},
            'service_mode': {'type': 'string', 'enum': ['pickup', 'delivery']},
            'address': {'type': 'string', 'description': 'Customer-provided delivery address.'},
            'allergens': {'type': 'array', 'items': {'type': 'string'},
                         'description': 'Confirmed normalized allergens; [] only if customer confirms none.'},
            'budget_usd': {'type': 'string', 'pattern': r'^\d+(\.\d{1,2})?$',
                           'description': 'Optional total budget in USD, e.g. "800.00", including tax/fees.'},
            'selections': {'type': 'array', 'maxItems': 100, 'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['item_id', 'variant_id', 'quantity'],
                'properties': {'item_id': {'type': 'string'}, 'variant_id': {'type': 'string'},
                               'quantity': {'type': 'integer', 'minimum': 1}}}},
        },
    },
}

QUESTIONS = {
    'headcount': 'How many people is the order for?',
    'event_at': 'What is the event date and time?',
    'service_mode': 'Would you like pickup or delivery?',
    'address': 'What is the delivery address?',
    'allergens': 'Are there any food allergies we should know about?',
    'selections': 'Which menu items and quantities would you like to price?',
}


def _response(status, *, code=None, missing=(), questions=(), readiness=None, budget=None):
    result = {'schema_version': '1.0', 'status': status, 'error_code': code,
              'missing_fields': list(missing), 'questions': list(questions),
              'blocking_reasons': [], 'review_reasons': [], 'pricing': None, 'budget': budget,
              'saved': False, 'can_auto_approve': False}
    if readiness:
        result['blocking_reasons'] = readiness['blocking_reasons']
        result['review_reasons'] = readiness['review_reasons']
        quote = readiness['pricing']
        if quote:
            # No raw inquiry, calendar, source URLs, or internal policy notes in model output.
            keep = ('currency', 'lines', 'food_subtotal_cents', 'delivery_fee_cents',
                    'service_charge_cents', 'staffing_fee_cents', 'tax_cents', 'total_cents')
            result['pricing'] = {key: quote[key] for key in keep}
    return result


def evaluate_catering_quote(arguments, *, menu, rules, now, capacity=None,
                            tax_location=None, delivery_miles=None):
    """Tool args are untrusted. All keyword context must be resolved by the server.

    tax_location/delivery_miles must correspond to the current confirmed address
    (pickup tax location to the business), never be copied from model arguments.
    Partial tool args are supported; omitted fields trigger clarification.
    """
    if not isinstance(arguments, dict) or set(arguments) - set(TOOL_DEFINITION['input_schema']['properties']):
        return _response('invalid_input', code='unexpected_or_invalid_fields')
    try:
        _validate(arguments)
        budget = None
        if 'budget_usd' in arguments:
            value = number(arguments['budget_usd'], 'budget_usd')
            if value * 100 != (value * 100).to_integral_value():
                raise QuoteError('budget precision')
            budget = cents(value)
    except (QuoteError, ValueError, ArithmeticError):
        return _response('invalid_input', code='invalid_field_value')
    missing = [key for key in ('headcount','event_at','service_mode','selections','allergens')
               if key not in arguments or (key != 'allergens' and not arguments[key])]
    if arguments.get('service_mode') == 'delivery' and not arguments.get('address', '').strip():
        missing.append('address')
    if missing:
        return _response('needs_clarification', missing=missing,
                         questions=[{'field': key, 'question': QUESTIONS[key]} for key in missing])
    # Missing server-derived facts are not questions the AI should answer by guessing.
    if tax_location is None or (arguments['service_mode'] == 'delivery' and delivery_miles is None):
        return _response('needs_server_context', code='delivery_or_tax_context_required')
    request = {key: value for key, value in arguments.items() if key != 'budget_usd'}
    request.update(tax_location=tax_location, delivery_miles=delivery_miles)
    try:
        ready = check_quote_readiness(menu, rules, request, now=now, capacity=capacity)
    except QuoteError as exc:
        known = {
            'headcount below service minimum': ('blocked', 'headcount_below_minimum'),
            'food subtotal below service minimum': ('blocked', 'subtotal_below_minimum'),
            'outside delivery radius': ('blocked', 'outside_delivery_radius'),
            'selected menu item/variant is unavailable': ('blocked', 'menu_item_unavailable'),
            'unknown variant ID': ('invalid_input', 'unknown_variant'),
            'variant does not belong to item': ('invalid_input', 'mismatched_item_variant'),
            'duplicate selection: combine quantities first': ('invalid_input', 'duplicate_selection'),
            'event_at must be a valid ISO datetime': ('invalid_input', 'invalid_event_datetime'),
            'event_at requires a timezone offset': ('invalid_input', 'event_timezone_required'),
        }
        if str(exc) in known:
            status, code = known[str(exc)]
            result = _response(status, code=code)
            if status == 'blocked':
                result['blocking_reasons'] = [code]
            return result
        # Keep malformed config/internal exception details out of model context.
        return _response('cannot_evaluate', code='invalid_request_or_configuration')
    result = _response(ready['status'], readiness=ready)
    if budget is not None and ready['pricing']:
        total = ready['pricing']['total_cents']
        result['budget'] = {'limit_cents': budget, 'within_budget': total <= budget,
                            'over_budget_cents': max(0, total - budget)}
    return result


def _validate(args):
    validate_customer_notes(args)
    if 'headcount' in args and (type(args['headcount']) is not int or not 1 <= args['headcount'] <= 100000):
        raise QuoteError('invalid headcount')
    for key in ('event_at', 'address', 'budget_usd'):
        if key in args and (not isinstance(args[key], str) or len(args[key]) > 1000):
            raise QuoteError('invalid text field')
    if 'budget_usd' in args:
        import re
        if not re.fullmatch(r'\d{1,9}(\.\d{1,2})?', args['budget_usd']):
            raise QuoteError('invalid budget')
    if 'service_mode' in args and args['service_mode'] not in ('pickup', 'delivery'):
        raise QuoteError('unsupported mode')
    if 'allergens' in args and (not isinstance(args['allergens'], list) or len(args['allergens']) > 50
                               or any(not isinstance(x,str) or len(x)>100 for x in args['allergens'])):
        raise QuoteError('invalid allergens')
    if 'selections' in args:
        if not isinstance(args['selections'],list) or len(args['selections']) > 100:
            raise QuoteError('invalid selections')
        for entry in args['selections']:
            if not isinstance(entry,dict) or set(entry) != {'item_id','variant_id','quantity'}:
                raise QuoteError('invalid selection fields')
            if any(not isinstance(entry[k],str) or not entry[k] or len(entry[k])>200 for k in ('item_id','variant_id')):
                raise QuoteError('invalid menu ID')
            if type(entry['quantity']) is not int or not 1 <= entry['quantity'] <= 100000:
                raise QuoteError('invalid quantity')
