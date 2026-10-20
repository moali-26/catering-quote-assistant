"""Pure owner menu-edit functions. No IO, no auth: callers pass a trusted menu.

Owners may change only these fields (see data/demo/README.md):
  item:    name, description, available
  variant: price, available
IDs, pricing units, serving sizes, dietary tags and allergens are fixed in the
minimum build because saved quotes, AI tool calls and safety checks depend on them.
"""
import copy
import unicodedata
from decimal import Decimal, InvalidOperation

from quote_engine.pricing import QuoteError

ITEM_FIELDS = {'name', 'description', 'available'}
VARIANT_FIELDS = {'price', 'available'}
MAX_NAME = 120
MAX_DESCRIPTION = 600
MAX_PRICE = Decimal('10000')
MAX_CHANGES_PER_REQUEST = 100


class MenuEditError(QuoteError):
    """Invalid edit request. Message is safe to show to the owner."""


def _text(value, field, limit, allow_empty):
    if not isinstance(value, str):
        raise MenuEditError(f'{field} must be text')
    value = ' '.join(value.split())  # collapse whitespace/newlines
    if any(unicodedata.category(ch).startswith('C') for ch in value):
        raise MenuEditError(f'{field} contains invalid characters')
    if not value and not allow_empty:
        raise MenuEditError(f'{field} cannot be empty')
    if len(value) > limit:
        raise MenuEditError(f'{field} must be at most {limit} characters')
    return value


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MenuEditError('price must be a number')
    try:
        amount = Decimal(str(value).strip().lstrip('$'))
    except InvalidOperation:
        raise MenuEditError('price must be a number') from None
    if not amount.is_finite() or amount <= 0:
        raise MenuEditError('price must be greater than 0')
    if amount > MAX_PRICE:
        raise MenuEditError(f'price must be at most ${MAX_PRICE}')
    if amount != amount.quantize(Decimal('0.01')):
        raise MenuEditError('price can have at most 2 decimal places')
    return float(amount.quantize(Decimal('0.01')))


def _bool(value, field):
    if type(value) is not bool:
        raise MenuEditError(f'{field} must be true or false')
    return value


def _clean(field, value):
    if field == 'name':
        return _text(value, 'name', MAX_NAME, allow_empty=False)
    if field == 'description':
        return _text(value, 'description', MAX_DESCRIPTION, allow_empty=True)
    if field == 'price':
        return _price(value)
    return _bool(value, field)


def apply_menu_changes(menu, changes):
    """Return (new_menu, applied) without mutating menu.

    changes: [{"item_id": ..., "variant_id": optional, "set": {field: value}}, ...]
    applied: [{"item_id", "variant_id", "field", "old", "new"}] for fields that changed.
    All-or-nothing: any invalid change raises MenuEditError and nothing is applied.
    """
    if not isinstance(changes, list) or not changes:
        raise MenuEditError('no changes submitted')
    if len(changes) > MAX_CHANGES_PER_REQUEST:
        raise MenuEditError(f'at most {MAX_CHANGES_PER_REQUEST} changes per save')
    new = copy.deepcopy(menu)
    items = {item['id']: item for item in new.get('items', [])}
    applied = []
    for change in changes:
        if not isinstance(change, dict) or set(change) - {'item_id', 'variant_id', 'set'}:
            raise MenuEditError('each change needs item_id, optional variant_id, and set')
        item = items.get(change.get('item_id'))
        if item is None:
            raise MenuEditError('unknown menu item')
        updates = change.get('set')
        if not isinstance(updates, dict) or not updates:
            raise MenuEditError('nothing to change')
        variant_id = change.get('variant_id')
        if variant_id is None:
            target, allowed = item, ITEM_FIELDS
        else:
            target = next((v for v in item['variants'] if v['id'] == variant_id), None)
            if target is None:
                raise MenuEditError('unknown size/variant for this item')
            allowed = VARIANT_FIELDS
        for field, value in updates.items():
            if field not in allowed:
                level = 'variant' if variant_id else 'item'
                raise MenuEditError(f'{field!r} cannot be edited on an {level}; '
                                    f'allowed: {", ".join(sorted(allowed))}')
            cleaned = _clean(field, value)
            old = target.get(field, True if field == 'available' else None)
            if cleaned != old:
                target[field] = cleaned
                applied.append({'item_id': item['id'], 'variant_id': variant_id,
                                'field': field, 'old': old, 'new': cleaned})
    if not applied:
        raise MenuEditError('no values changed')
    validate_menu_structure(new)
    return new, applied


def validate_menu_structure(menu):
    """Minimal checks that the quote engine and AI rely on. Raises MenuEditError."""
    if not isinstance(menu, dict) or not isinstance(menu.get('items'), list):
        raise MenuEditError('menu must have an items list')
    if not menu.get('meta', {}).get('dataset_id'):
        raise MenuEditError('menu needs meta.dataset_id')
    item_ids, variant_ids = set(), set()
    for item in menu['items']:
        if item.get('id') in item_ids:
            raise MenuEditError(f"duplicate item id {item.get('id')}")
        item_ids.add(item.get('id'))
        if not isinstance(item.get('name'), str) or not item['name'].strip():
            raise MenuEditError(f"{item.get('id')}: name required")
        if type(item.get('available', True)) is not bool:
            raise MenuEditError(f"{item.get('id')}: available must be true/false")
        if not item.get('variants'):
            raise MenuEditError(f"{item.get('id')}: needs at least one variant")
        for variant in item['variants']:
            if variant.get('id') in variant_ids:
                raise MenuEditError(f"duplicate variant id {variant.get('id')}")
            variant_ids.add(variant.get('id'))
            price = variant.get('price')
            if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
                raise MenuEditError(f"{variant.get('id')}: price must be positive")
            if type(variant.get('available', True)) is not bool:
                raise MenuEditError(f"{variant.get('id')}: available must be true/false")
    return True


def owner_menu_view(record):
    """JSON-safe data for the owner's menu page: editable fields only, plus revision."""
    menu = record['menu']
    return {
        'revision': record['revision'],
        'updated_at': record.get('updated_at'),
        'business_name': menu.get('meta', {}).get('branding', {}).get('display_name'),
        'items': [{
            'item_id': item['id'], 'name': item['name'], 'category': item.get('category'),
            'description': item.get('description', ''), 'available': item.get('available', True),
            'dietary_tags': item.get('dietary_tags', []),
            'allergen_status': item.get('allergen_status'),
            'variants': [{
                'variant_id': v['id'], 'label': v.get('label'), 'price': v['price'],
                'pricing_unit': v.get('pricing_unit'), 'serves': v.get('serves_text'),
                'available': v.get('available', True),
            } for v in item['variants']],
        } for item in menu['items']],
        'editable_fields': {'item': sorted(ITEM_FIELDS), 'variant': sorted(VARIANT_FIELDS)},
    }
