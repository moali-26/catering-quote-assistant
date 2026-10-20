"""Price explicit selections using trusted menu/rules snapshots."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class QuoteError(ValueError):
    """Invalid input/configuration or unsupported pricing; never a guessed quote."""


def number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise QuoteError(f"{field}: expected a nonnegative number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise QuoteError(f"{field}: invalid number") from exc
    if not result.is_finite() or result < 0:
        raise QuoteError(f"{field}: expected a finite nonnegative number")
    return result


def cents(value):
    return int((value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def positive_int(value, field):
    if type(value) is not int or value < 1:
        raise QuoteError(f"{field}: expected a positive integer")
    return value


def calculate_quote(menu, rules, request):
    """Validate container/config shape and return a deterministic draft snapshot."""
    if not all(isinstance(x, dict) for x in (menu, rules, request)):
        raise QuoteError('menu, rules, and request must be objects')
    try:
        return _calculate_quote(menu, rules, request)
    except (KeyError, TypeError, AttributeError, InvalidOperation, OverflowError) as exc:
        raise QuoteError('malformed pricing input or server configuration') from exc


def _calculate_quote(menu, rules, request):
    """Return JSON-safe pricing snapshot; callers must enforce auth and readiness.

    Supports pickup/delivery and explicit unit counts, not automatic portioning,
    full service, booking, or allergy-safety certification. Monetary outputs are
    integer cents. Menu/rules must come from server-side trusted storage.
    """
    mid = menu.get('meta', {}).get('dataset_id')
    rid = rules.get('meta', {}).get('dataset_id')
    if not mid or mid != rid:
        raise QuoteError('menu and rules dataset IDs must match')
    if bool(menu.get('meta', {}).get('sample')) != bool(rules.get('meta', {}).get('sample')):
        raise QuoteError('do not mix sample and full datasets')
    if menu['meta'].get('currency') != 'USD' or rules['meta'].get('currency') != 'USD':
        raise QuoteError('only matching USD configurations are supported')
    mode = request.get('service_mode')
    if mode not in ('pickup', 'delivery'):
        raise QuoteError('only pickup and delivery pricing are supported')
    headcount = positive_int(request.get('headcount'), 'headcount')
    config = rules.get('service_modes', {}).get(mode)
    if not config:
        raise QuoteError('service mode configuration is missing')
    minimum = config['order_minimum']
    if headcount < positive_int(minimum['guest_count'], 'minimum guest count'):
        raise QuoteError('headcount below service minimum')
    selections = request.get('selections')
    if not isinstance(selections, list) or not selections:
        raise QuoteError('selections must be a nonempty list')
    index = {}
    for item in menu['items']:
        for variant in item['variants']:
            if variant['id'] in index:
                raise QuoteError('duplicate variant ID in menu')
            index[variant['id']] = (item, variant)
    lines, flags, seen = [], [], set()
    for selection in selections:
        if not isinstance(selection, dict):
            raise QuoteError('each selection must be an object')
        vid = selection.get('variant_id')
        if not isinstance(vid, str) or vid not in index:
            raise QuoteError('unknown variant ID')
        if vid in seen:
            raise QuoteError('duplicate selection: combine quantities first')
        seen.add(vid)
        item, variant = index[vid]
        if selection.get('item_id') != item['id']:
            raise QuoteError('variant does not belong to item')
        if item.get('available', True) is not True or variant.get('available', True) is not True:
            raise QuoteError('selected menu item/variant is unavailable')
        quantity = positive_int(selection.get('quantity'), 'quantity')
        unit = variant['pricing_unit']
        if unit not in ('per_person', 'per_tray', 'per_platter', 'each'):
            raise QuoteError('unsupported pricing unit')
        price = number(variant['price'], 'menu price')
        if price * 100 != (price * 100).to_integral_value():
            raise QuoteError('menu price must have at most two decimal places')
        unit_cents = cents(price)
        lines.append({'item_id': item['id'], 'variant_id': vid,
                      'name': item['name'], 'label': variant['label'],
                      'pricing_unit': unit, 'quantity': quantity,
                      'unit_price_cents': unit_cents,
                      'line_total_cents': unit_cents * quantity})
        status = item.get('allergen_status', 'unknown')
        if status == 'depends_on_selection':
            flags.append(f"allergen_depends_on_selection:{item['id']}")
        elif status not in ('listed', 'listed_none'):
            flags.append(f"allergen_unknown:{item['id']}")
        if variant.get('serves_basis') == 'assumption':
            flags.append(f'assumed_servings:{vid}')
    food = sum(line['line_total_cents'] for line in lines)
    if minimum.get('subtotal') is not None and food < cents(number(minimum['subtotal'], 'minimum subtotal')):
        raise QuoteError('food subtotal below service minimum')
    delivery = 0
    if mode == 'delivery':
        miles = number(request.get('delivery_miles'), 'delivery_miles')
        fee = rules['delivery']['fee']
        if fee['type'] != 'flat_plus_mileage':
            raise QuoteError('unsupported delivery fee type')
        if miles > number(rules['delivery']['radius']['max_miles'], 'radius'):
            raise QuoteError('outside delivery radius')
        extra = max(Decimal(0), miles - number(fee['included_miles'], 'included miles'))
        delivery = cents(number(fee['flat_fee'], 'delivery fee') + extra * number(fee['per_mile_beyond_included'], 'mileage rate'))
    tax_config = rules['tax']
    location = request.get('tax_location')
    if not isinstance(location, str) or location not in tax_config['rates']:
        raise QuoteError('explicit supported tax_location required')
    rate = number(tax_config['rates'][location], 'tax rate')
    if rate >= 1:
        raise QuoteError('tax rate must be less than 1')
    parts = {'food_subtotal': food, 'delivery_fee': delivery, 'service_charge': 0, 'staffing_fee': 0}
    base_keys = tax_config['taxable_base']
    if len(base_keys) != len(set(base_keys)) or any(k not in parts for k in base_keys):
        raise QuoteError('invalid taxable base configuration')
    taxable = sum(parts[k] for k in base_keys)
    tax = int((Decimal(taxable) * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return {'schema_version': '0.1', 'status': 'priced_draft',
            'dataset_id': mid, 'sample_data': bool(menu['meta'].get('sample')),
            'service_mode': mode, 'headcount': headcount, 'currency': 'USD',
            'lines': lines, **{k + '_cents': v for k, v in parts.items()},
            'taxable_subtotal_cents': taxable, 'tax_rate': str(rate),
            'tax_location': location, 'tax_cents': tax,
            'total_cents': food + delivery + tax,
            'flags': sorted(set(flags)), 'requires_owner_review': True,
            'pending_checks': ['event_details', 'lead_time', 'capacity',
                               'allergen_and_dietary_review', 'portion_coverage'],
            'rules_assumptions': deepcopy(list(rules.get('assumptions', [])))}
