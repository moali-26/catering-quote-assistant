"""Menu lookup tool. Gives the model real item/variant IDs so it never invents them.

Read-only view of the trusted server menu. Unit prices are shown so the model
can choose sensibly, but totals always come from evaluate_catering_quote.
"""
from decimal import Decimal

SEARCH_MENU_TOOL = {
    'name': 'search_menu',
    'description': (
        'Search the current catering menu. Returns real item IDs, variant IDs, unit prices, '
        'pricing units and serving sizes. Use these exact IDs when pricing. Unit prices are '
        'for choosing items only; never add them up yourself, call evaluate_catering_quote '
        'for totals. Items whose allergen_status is "unknown" or "depends_on_selection" are '
        'NOT confirmed safe for any allergy.'),
    'input_schema': {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'query': {'type': 'string', 'description': 'Optional words to match in name/description.'},
            'category': {'type': 'string', 'description': 'Optional category name, e.g. "Salads".'},
            'dietary': {'type': 'array', 'items': {'type': 'string',
                        'enum': ['vegan', 'vegetarian', 'gluten_sensitive']},
                        'description': 'Only items carrying ALL of these tags. vegan items also count as vegetarian.'},
            'exclude_allergens': {'type': 'array', 'items': {'type': 'string'},
                                  'description': 'Remove items whose listed allergens include any of these.'},
            'item_ids': {'type': 'array', 'items': {'type': 'string'},
                         'description': 'Optional exact item IDs to look up.'},
        },
    },
}

MAX_RESULTS = 40


def _has_tags(item, wanted):
    tags = set(item.get('dietary_tags', []))
    if 'vegan' in tags:
        tags.add('vegetarian')  # vegan implies vegetarian
    return set(wanted).issubset(tags)


def _price_text(value):
    return f'${Decimal(str(value)).quantize(Decimal("0.01"))}'


def _view(item):
    view = {
        'item_id': item['id'],
        'name': item.get('name'),
        'category': item.get('category'),
        'description': item.get('description', ''),
        'dietary_tags': item.get('dietary_tags', []),
        'allergens': item.get('allergens', []),
        'allergen_status': item.get('allergen_status', 'unknown'),
        'variants': [
            {'variant_id': v['id'], 'label': v.get('label'), 'unit_price': _price_text(v['price']),
             'pricing_unit': v.get('pricing_unit'), 'serves': v.get('serves_text')}
            for v in item.get('variants', []) if v.get('available', True) is True
        ],
    }
    if item.get('allergen_note'):
        view['allergen_note'] = item['allergen_note']
    return view


def search_menu(menu, arguments):
    """Return {'items': [...], 'count': n} or {'error': code}."""
    if not isinstance(arguments, dict):
        return {'error': 'arguments_must_be_object'}
    allowed = set(SEARCH_MENU_TOOL['input_schema']['properties'])
    if set(arguments) - allowed:
        return {'error': 'unexpected_fields', 'allowed_fields': sorted(allowed)}
    query = arguments.get('query') or ''
    category = arguments.get('category') or ''
    dietary = arguments.get('dietary') or []
    exclude = arguments.get('exclude_allergens') or []
    item_ids = arguments.get('item_ids') or []
    for value in (query, category):
        if not isinstance(value, str):
            return {'error': 'invalid_text_field'}
    for value in (dietary, exclude, item_ids):
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            return {'error': 'invalid_list_field'}

    known_allergens = set(menu.get('allergen_definitions', []))
    unknown_requested = sorted(set(exclude) - known_allergens)

    results = []
    for item in menu.get('items', []):
        if item.get('available', True) is not True:
            continue
        if item_ids and item['id'] not in item_ids:
            continue
        if category and category.lower() != str(item.get('category', '')).lower():
            continue
        if query:
            haystack = f"{item.get('name', '')} {item.get('description', '')}".lower()
            if not all(word in haystack for word in query.lower().split()):
                continue
        if dietary and not _has_tags(item, dietary):
            continue
        if exclude and set(exclude).intersection(item.get('allergens', [])):
            continue
        view = _view(item)
        if view['variants']:
            results.append(view)

    out = {'count': len(results), 'items': results[:MAX_RESULTS]}
    if len(results) > MAX_RESULTS:
        out['truncated'] = True
    if unknown_requested:
        out['warning'] = ('These allergen names are not in the menu vocabulary and were not '
                          f'filtered: {unknown_requested}. Valid names: {sorted(known_allergens)}. '
                          'Clarify with the customer.')
    if exclude:
        out['allergen_reminder'] = ('Only listed allergens were filtered. Items with '
                                    'allergen_status unknown/depends_on_selection still need '
                                    'caterer confirmation.')
    return out
