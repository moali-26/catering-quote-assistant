"""Read-only views of the active business data for public pages.

Prices shown here come from the menu file; the example quote is calculated by
C's pricing engine, so the landing page never hard-codes a dollar amount.
"""
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from ai_service.data_loader import DATASETS
from quote_engine import calculate_quote
from quote_engine.presentation import money

ROOT = Path(__file__).resolve().parents[1]

UNIT_LABELS = {
    'per_person': 'per person',
    'per_tray': 'per tray',
    'per_platter': 'per platter',
}
DIETARY_LABELS = {
    'vegan': 'Vegan',
    'vegetarian': 'Vegetarian',
    'gluten_sensitive': 'Gluten-sensitive',
}


def _pretty_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return value or ''
    return f'{parsed:%b} {parsed.day}, {parsed.year}'


def _load(folder: Path, name: str):
    return json.loads((folder / name).read_text(encoding='utf-8'))


@lru_cache(maxsize=2)
def business(dataset: str = 'sample') -> dict:
    folder = DATASETS[dataset]
    menu, rules = _load(folder, 'menu.json'), _load(folder, 'rules.json')
    meta = menu.get('meta', {})
    origin = rules.get('delivery', {}).get('origin', {})
    if origin.get('city'):
        place = ', '.join(part for part in (origin.get('city'), origin.get('state')) if part)
    else:
        place = meta.get('source', {}).get('location', '')
    return {
        'name': meta.get('branding', {}).get('display_name', 'Catering Co.'),
        'place': place,
        'captured_at': _pretty_date(meta.get('captured_at', '')),
        'menu': menu,
        'rules': rules,
    }


def make_scrubber(menu: dict):
    """Return a function that keeps the provenance business name out of UI text.

    Applies the dataset's explicit item_aliases first, then replaces any remaining
    mention of the source name (and its possessive) with neutral wording.
    """
    meta = menu.get('meta', {})
    branding = meta.get('branding', {})
    aliases = sorted(branding.get('item_aliases', {}).items(), key=lambda kv: -len(kv[0]))
    source = meta.get('source', {}).get('business_name', '')
    display = branding.get('display_name', 'the caterer')
    names = [n for n in {source, source.split(' ')[0] if source else ''} if n]
    names.sort(key=len, reverse=True)

    def scrub(text: str) -> str:
        if not text:
            return text
        for original, alias in aliases:
            text = text.replace(original, alias)
        for name in names:
            for possessive in (f"{name}'s", f"{name}\u2019s"):
                text = text.replace(possessive, 'our')
            text = text.replace(name, display)
        return 'Our' + text[3:] if text.startswith('our ') else text

    return scrub


def _price_from(item: dict) -> dict:
    variant = min(item['variants'], key=lambda v: v['price'])
    return {
        'amount': money(round(variant['price'] * 100)),
        'unit': UNIT_LABELS.get(variant.get('pricing_unit'), variant.get('pricing_unit', '')),
        'serves': variant.get('serves_text', ''),
        'several': len(item['variants']) > 1,
    }


def menu_highlights(dataset: str = 'sample', limit: int = 8, *, current_menu=None) -> list:
    menu = current_menu if current_menu is not None else business(dataset)['menu']
    scrub = make_scrubber(menu)
    return [
        {
            'name': scrub(item['name']),
            'category': item.get('category', ''),
            'description': scrub(item.get('description', '')),
            'tags': [DIETARY_LABELS[t] for t in item.get('dietary_tags', []) if t in DIETARY_LABELS],
            'price': _price_from(item),
        }
        for item in [dict(i, variants=[v for v in i['variants'] if v.get('available', True)])
                     for i in menu.get('items', []) if i.get('available', True)
                     and any(v.get('available', True) for v in i['variants'])][:limit]
    ]


def example_quote(dataset: str = 'sample', *, current_menu=None):
    """Price the fixture's worked example with the real engine, or None if absent."""
    path = DATASETS[dataset] / 'inquiries.json'
    if not path.exists():  # demo menu has no fixture; its items include the sample's, so reuse that example
        path = DATASETS['sample'] / 'inquiries.json'
    if not path.exists():
        return None
    fixture = json.loads(path.read_text(encoding='utf-8'))
    example = fixture.get('pricing_example')
    if not example:
        return None
    inquiry = next((i for i in fixture.get('inquiries', []) if i['id'] == example['inquiry_id']), None)
    headcount = (inquiry or {}).get('expected', {}).get('headcount')
    request = {key: example[key] for key in ('service_mode', 'delivery_miles', 'tax_location', 'selections')}
    if headcount:
        request['headcount'] = headcount
    data = dict(business(dataset))
    if current_menu is not None:
        data['menu'] = current_menu
    scrub = make_scrubber(data['menu'])
    from quote_engine.pricing import QuoteError
    try:
        quote = calculate_quote(data['menu'], data['rules'], request)
    except QuoteError:
        return None  # Example selections may have been disabled by the owner.
    return {
        'request_text': scrub((inquiry or {}).get('text', '')),
        'headcount': quote['headcount'],
        'service_mode': quote['service_mode'].replace('_', ' '),
        'tax_location': quote.get('tax_location', ''),
        'tax_rate': f"{float(quote['tax_rate']) * 100:.2f}%",
        'lines': [
            {
                'name': scrub(line['name']),
                'label': line['label'],
                'quantity': line['quantity'],
                'unit': money(line['unit_price_cents']),
                'total': money(line['line_total_cents']),
            }
            for line in quote['lines']
        ],
        'subtotal': money(quote['food_subtotal_cents']),
        'delivery': money(quote['delivery_fee_cents']),
        'tax': money(quote['tax_cents']),
        'total': money(quote['total_cents']),
        'needs_review': quote.get('requires_owner_review', True),
    }
