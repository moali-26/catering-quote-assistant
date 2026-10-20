"""Owner menu page: turn the posted form into A's MenuService changes, and back into a view.

The form posts every editable field. Only fields whose value really changed are sent to
MenuService.update, and each change is validated on its own first, so an error can be shown
next to the field it belongs to. A save is still all-or-nothing (MenuService.update).
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from menu_admin import MenuEditError, apply_menu_changes

FIELD_NAMES = {'name': 'name', 'description': 'description', 'available': 'availability', 'price': 'price'}


def field_key(item_id, field, variant_id=None):
    return f'm:{item_id}:{variant_id}:{field}' if variant_id else f'm:{item_id}:{field}'


def _same_text(raw, current):
    return ' '.join((raw or '').split()) == ' '.join((current or '').split())


def _same_price(raw, current):
    try:
        return Decimal(str(raw).strip().lstrip('$')) == Decimal(str(current))
    except (InvalidOperation, ValueError):
        return False


def read_form(view, form):
    """Return (changes, submitted) from the posted form.

    submitted maps field_key -> the raw value the owner typed (to re-show on errors).
    Items missing from the form are left alone (e.g. a stale page that predates an item).
    """
    changes, submitted = [], {}
    for item in view['items']:
        item_id = item['item_id']
        if field_key(item_id, 'name') not in form:
            continue
        item_set = {}
        name = form.get(field_key(item_id, 'name'), '')
        description = form.get(field_key(item_id, 'description'), '')
        available = field_key(item_id, 'available') in form
        submitted[field_key(item_id, 'name')] = name
        submitted[field_key(item_id, 'description')] = description
        submitted[field_key(item_id, 'available')] = available
        if not _same_text(name, item['name']):
            item_set['name'] = name
        if not _same_text(description, item['description']):
            item_set['description'] = description
        if available != item['available']:
            item_set['available'] = available
        if item_set:
            changes.append({'item_id': item_id, 'set': item_set})
        for variant in item['variants']:
            variant_id = variant['variant_id']
            price = form.get(field_key(item_id, 'price', variant_id), '')
            if re.fullmatch(r'\s*\$?\s*\d{1,3}(,\d{3})+(\.\d*)?\s*', price or ''):
                price = price.replace(',', '')  # "1,200.00" is a price people type
            v_available = field_key(item_id, 'available', variant_id) in form
            submitted[field_key(item_id, 'price', variant_id)] = price
            submitted[field_key(item_id, 'available', variant_id)] = v_available
            v_set = {}
            if not _same_price(price, variant['price']):
                v_set['price'] = price
            if v_available != variant['available']:
                v_set['available'] = v_available
            if v_set:
                changes.append({'item_id': item_id, 'variant_id': variant_id, 'set': v_set})
    return changes, submitted


def field_errors(menu, changes):
    """Validate each changed field on its own; return {field_key: owner-safe message}."""
    errors = {}
    for change in changes:
        for field, value in change['set'].items():
            single = [{k: v for k, v in change.items() if k != 'set'} | {'set': {field: value}}]
            try:
                apply_menu_changes(menu, single)
            except MenuEditError as exc:
                message = str(exc)
                if message == 'no values changed':
                    continue
                errors[field_key(change['item_id'], field, change.get('variant_id'))] = message[0].upper() + message[1:]
    return errors


def editor_view(view, *, submitted=None, errors=None):
    """Owner view plus what the form should show (typed values after an error) and grouping by category."""
    submitted, errors = submitted or {}, errors or {}
    groups, order = {}, []
    for item in view['items']:
        item_id = item['item_id']
        shown = {
            'item_id': item_id, 'category': item.get('category') or 'Other',
            'dietary_tags': item.get('dietary_tags', []), 'allergen_status': item.get('allergen_status'),
            'name': submitted.get(field_key(item_id, 'name'), item['name']),
            'description': submitted.get(field_key(item_id, 'description'), item['description']),
            'available': submitted.get(field_key(item_id, 'available'), item['available']),
            'saved_name': item['name'], 'saved_description': item['description'], 'saved_available': item['available'],
            'errors': {f: errors[field_key(item_id, f)] for f in ('name', 'description', 'available')
                       if field_key(item_id, f) in errors},
            'variants': [],
        }
        for variant in item['variants']:
            variant_id = variant['variant_id']
            price = submitted.get(field_key(item_id, 'price', variant_id))
            shown['variants'].append({
                'variant_id': variant_id, 'label': variant.get('label') or 'Standard',
                'serves': variant.get('serves') or '', 'pricing_unit': variant.get('pricing_unit') or '',
                'price': price if price is not None else f"{variant['price']:.2f}",
                'saved_price': f"{variant['price']:.2f}", 'saved_available': variant['available'],
                'available': submitted.get(field_key(item_id, 'available', variant_id), variant['available']),
                'errors': {f: errors[field_key(item_id, f, variant_id)] for f in ('price', 'available')
                           if field_key(item_id, f, variant_id) in errors},
            })
        if shown['category'] not in groups:
            groups[shown['category']] = []
            order.append(shown['category'])
        groups[shown['category']].append(shown)
    return [{'name': name, 'items': groups[name]} for name in order]


def describe_change(entry, names, tz=None):
    """One change-log line in plain words, e.g. 'Brownie (Per person) price $3.29 → $4.29'."""
    who = names.get(entry.get('variant_id') or entry['item_id'], entry['item_id'])
    field = entry['field']
    old, new = entry.get('old'), entry.get('new')
    if field == 'price':
        what = f'price ${old:,.2f} → ${new:,.2f}' if isinstance(old, (int, float)) else f'price → ${new:,.2f}'
    elif field == 'available':
        what = 'back on the menu' if new else 'taken off the menu'
    elif field == 'name':
        what = f'renamed from “{old}”'
    else:
        what = 'description updated'
    when = ''
    try:
        stamp = datetime.fromisoformat(entry['at'])
        if tz is not None:
            stamp = stamp.astimezone(tz)
        when = f"{stamp:%b} {stamp.day} · {stamp.strftime('%I:%M %p').lstrip('0')}"
    except (KeyError, TypeError, ValueError):
        pass
    return {'who': who, 'what': what, 'when': when}
