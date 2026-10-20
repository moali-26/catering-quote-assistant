"""Validate the frozen demo dataset against its source and the quote engine.

Run from the repo root:  python3 data/demo/validate_demo.py
Exit code 1 if any check fails.
"""
import json
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
DATA = DEMO.parent
ROOT = DATA.parent
sys.path.insert(0, str(ROOT))

from quote_engine import QuoteError, calculate_quote  # noqa: E402

ALLOWED_UNITS = {'per_person', 'per_tray', 'per_platter', 'each'}
ALLOWED_STATUS = {'listed', 'listed_none', 'unknown', 'depends_on_selection'}
# Fields that must match the source exactly (provenance). name may differ (display alias).
COPIED_ITEM_FIELDS = ('category', 'description', 'dietary_tags', 'allergens', 'allergen_status')
COPIED_VARIANT_FIELDS = ('id', 'label', 'price', 'pricing_unit', 'serves', 'serves_text', 'serves_basis')
BRAND_WORDS = ('stonefire', 'sfg')
DEMO_DATE = '2026-10-22'  # presentation day; demo event dates come after this


def load(path):
    return json.loads(Path(path).read_text())


def validate(menu, rules, capacity, full_menu, inquiries):
    errors = []
    err = errors.append

    ids = {m['meta'].get('dataset_id') for m in (menu, rules, capacity)}
    if len(ids) != 1:
        err(f'dataset_id differs across menu/rules/capacity: {ids}')
    if menu['meta'].get('sample') or rules['meta'].get('sample'):
        err('demo dataset must not be flagged sample (engine rejects sample/full mixing)')

    source = {i['id']: i for i in full_menu['items']}
    seen = set()
    for item in menu['items']:
        iid = item['id']
        if iid in seen:
            err(f'duplicate item id {iid}')
        seen.add(iid)
        if iid not in source:
            err(f'{iid}: not in data/menu.json')
            continue
        src = source[iid]
        for key in COPIED_ITEM_FIELDS:
            if item.get(key) != src.get(key):
                err(f'{iid}: {key} differs from source')
        if item.get('source_name', item['name']) != src['name']:
            err(f'{iid}: source_name/name does not match source name')
        if any(word in item['name'].lower() for word in BRAND_WORDS):
            err(f'{iid}: real brand appears in display name {item["name"]!r}')
        if type(item.get('available')) is not bool:
            err(f'{iid}: available must be true/false')
        if item.get('allergen_status') not in ALLOWED_STATUS:
            err(f'{iid}: bad allergen_status')
        src_variants = {v['id']: v for v in src['variants']}
        for variant in item['variants']:
            vid = variant['id']
            if vid not in src_variants:
                err(f'{vid}: not in source item')
                continue
            for key in COPIED_VARIANT_FIELDS:
                if variant.get(key) != src_variants[vid].get(key):
                    err(f'{vid}: {key} differs from source')
            if type(variant.get('available')) is not bool:
                err(f'{vid}: available must be true/false')
            if variant.get('pricing_unit') not in ALLOWED_UNITS:
                err(f'{vid}: bad pricing_unit')
            if not (isinstance(variant.get('price'), (int, float)) and variant['price'] > 0):
                err(f'{vid}: price must be positive')

    categories = {c['name'] for c in menu['categories']}
    for item in menu['items']:
        if item['category'] not in categories:
            err(f"{item['id']}: category {item['category']!r} not listed")

    # Coverage the AI demo relies on.
    tags = [set(i['dietary_tags']) for i in menu['items']]
    if sum('vegan' in t for t in tags) < 2:
        err('need at least 2 vegan items')
    if sum(bool({'vegan', 'vegetarian'} & t) for t in tags) < 6:
        err('need at least 6 vegetarian-friendly items')
    statuses = {i['allergen_status'] for i in menu['items']}
    for status in ALLOWED_STATUS:
        if status not in statuses:
            err(f'no item with allergen_status {status} (needed to demo allergen handling)')
    nut_free_desserts = [i for i in menu['items'] if i['category'] == 'Desserts'
                         and not {'peanut', 'tree_nuts'} & set(i['allergens'])
                         and i['allergen_status'] == 'listed']
    if not nut_free_desserts:
        err('need a dessert without listed nuts for the nut-allergy swap demo')

    # Sample inquiries must still refer to real demo items.
    example = inquiries.get('pricing_example', {})
    referenced = {s['item_id'] for s in example.get('selections', [])}
    for inquiry in inquiries.get('inquiries', []):
        expected = inquiry.get('expected', {})
        referenced |= set(expected.get('must_avoid', []))
        referenced |= {f.split(':')[0] for f in expected.get('must_flag', [])}
    for iid in sorted(referenced - seen):
        err(f'sample inquiry references {iid}, which is not in the demo menu')

    # Every variant must be priceable by the quote engine.
    for item in menu['items']:
        for variant in item['variants']:
            request = {'headcount': 10, 'service_mode': 'pickup', 'tax_location': 'Torrance',
                       'selections': [{'item_id': item['id'], 'variant_id': variant['id'], 'quantity': 1}]}
            try:
                calculate_quote(menu, rules, request)
            except QuoteError as exc:
                err(f"{variant['id']}: quote engine rejected it ({exc})")

    # Capacity must offer both an open and a full date after the presentation day.
    future = {d: e for d, e in capacity.get('exceptions', {}).items() if d > DEMO_DATE}
    if not any(e.get('status') == 'full' for e in future.values()):
        err(f'no fully booked date after {DEMO_DATE} to demo a capacity conflict')
    if not any(e.get('status') == 'open' for e in future.values()):
        err(f'no open exception date after {DEMO_DATE}')
    return errors


def main():
    errors = validate(load(DEMO / 'menu.json'), load(DEMO / 'rules.json'),
                      load(DEMO / 'capacity.json'), load(DATA / 'menu.json'),
                      load(DATA / 'sample' / 'inquiries.json'))
    menu = load(DEMO / 'menu.json')
    if errors:
        print('Demo dataset INVALID:')
        for e in errors:
            print(f'  - {e}')
        sys.exit(1)
    print(f"Demo dataset OK: {len(menu['items'])} items, "
          f"{sum(len(i['variants']) for i in menu['items'])} variants.")


if __name__ == '__main__':
    main()
