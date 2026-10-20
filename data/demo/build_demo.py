"""Build the frozen demo dataset from the full primary dataset.

Run from the repo root:  python3 data/demo/build_demo.py

The demo menu is a SUBSET of data/menu.json. Item IDs, variant IDs, prices,
serving sizes, dietary tags and allergens are copied unchanged, so provenance
still points to data/raw/. Changes made here:
  - only DEMO_ITEM_IDS are kept;
  - every item and variant gets "available": true (owner can switch off);
  - item names use the display aliases from meta.branding.item_aliases, so
    the real brand never shows in the app; the original is kept as source_name.
Rules and capacity are copied from the full dataset (same dataset_id).
Re-running this script overwrites data/demo/*.json, including owner edits,
so once owner menu editing is live, the database copy becomes the source of truth.
"""
import copy
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent

# 22 items. The 9 items of data/sample are all included so sample inquiries stay valid.
DEMO_ITEM_IDS = [
    # Appetizers
    'app-hummus', 'app-chicken-tenders', 'app-fruit-platter',
    # Catering packages
    'pkg-pasta-duo', 'pkg-sfg-classic',
    # A la carte pans (mains)
    'pan-tri-tip', 'pan-pulled-pork', 'pan-chicken-breast', 'pan-breadsticks',
    # Pastas
    'pasta-marinara', 'pasta-mac-cheese', 'pasta-pesto',
    # Salads
    'salad-garden', 'salad-caesar', 'salad-cobb',
    # Sides
    'side-garlic-mashed', 'side-coleslaw', 'side-roasted-vegetables', 'side-cornbread',
    # Desserts
    'dessert-cookie-platter', 'dessert-brownie',
    # Beverages
    'bev-sodas-water',
]


def load(name):
    return json.loads((DATA / name).read_text())


def build_menu(full):
    by_id = {item['id']: item for item in full['items']}
    missing = [i for i in DEMO_ITEM_IDS if i not in by_id]
    if missing:
        raise SystemExit(f'Items not in data/menu.json: {missing}')
    aliases = full['meta'].get('branding', {}).get('item_aliases', {})

    items = []
    for item_id in DEMO_ITEM_IDS:
        item = copy.deepcopy(by_id[item_id])
        if item['name'] in aliases:
            item['source_name'] = item['name']
            item['name'] = aliases[item['name']]
        item['available'] = True
        for variant in item['variants']:
            variant['available'] = True
        items.append(item)

    used = {item['category'] for item in items}
    meta = copy.deepcopy(full['meta'])
    meta['demo_subset'] = {
        'derived_from': 'data/menu.json',
        'build_script': 'data/demo/build_demo.py',
        'item_count': len(items),
        'note': ('Frozen demo menu: a subset of the full primary dataset. IDs, prices, '
                 'serving sizes, dietary tags and allergens are unchanged from the source. '
                 'Added: available flags, display-alias item names (source_name keeps the original).'),
    }
    return {
        'meta': meta,
        'categories': [c for c in full['categories'] if c['name'] in used],
        'dietary_tag_definitions': full['dietary_tag_definitions'],
        'allergen_definitions': full['allergen_definitions'],
        'items': items,
    }


def main():
    menu = build_menu(load('menu.json'))
    rules = load('rules.json')
    capacity = load('capacity.json')
    rules['meta']['demo_subset_note'] = 'Copied unchanged from data/rules.json for the demo menu.'
    capacity['meta']['demo_subset_note'] = 'Copied unchanged from data/capacity.json (synthetic).'
    for name, obj in (('menu.json', menu), ('rules.json', rules), ('capacity.json', capacity)):
        (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    print(f"Wrote data/demo/: {len(menu['items'])} items, "
          f"{sum(len(i['variants']) for i in menu['items'])} variants, "
          f"{len(menu['categories'])} categories")


if __name__ == '__main__':
    main()
