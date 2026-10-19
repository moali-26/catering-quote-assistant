"""Parse the saved Gok Jee Foods catering menu into a simplified dataset.

Source snapshot: data/raw/gokjee-menuform-2026-10-18.html
Run: python data/gokjee/parse_menu.py
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
RAW = ROOT.parent / "raw" / "gokjee-menuform-2026-10-18.html"
OUT = ROOT / "menu.json"

CATEGORY_MAP = {
    "Set Menu": "Set Menus",
    "Signature Lite": "Signature Lite",
    "Beef/Pork": "Beef & Pork",
    "Chicken": "Chicken",
    "Fish": "Fish",
    "Seafood": "Seafood",
    "Fried": "Fried",
    "Jobche/DukBoke": "Noodles & Rice Cakes",
    "Cold Dishes": "Cold Dishes",
    "Vegetables": "Vegetables",
    "Pancake": "Pancakes",
    "Kebob/Mari": "Skewers & Rolls",
    "Salad": "Salads",
    "Kimchi": "Kimchi",
    "Kimbab/Rice": "Kimbab & Rice",
    "Dessert": "Dessert",
    "Soup": "Soups",
}

SET_CONTENTS = {
    "A": (
        "Bulgogi, sweet spicy chicken, fried shrimp, jobche (veg. glass noodle), "
        "tofu pancake, veg. kimbab, kimchi, rice, plate/napkin/chopsticks."
    ),
    "B": (
        "Galbijim, sweet spicy chicken, fried shrimp, jobche (veg. glass noodle), "
        "tofu pancake, bulgogi kimbab, kimchi, rice, plate/napkin/chopsticks."
    ),
    "C": (
        "LA galbi (grilled), pork belly (sam set), kanpon shrimp, jobche (veg. glass noodle), "
        "fish and veg shrimp pancake, California roll and bulgogi kimbab, "
        "kimchi and cucumber kimchi, rice, plate/napkin/chopsticks."
    ),
}

DIETARY_NOTES = {
    "Dumplings (Veg.)": "Explicitly labeled veg. on the source menu.",
    "Jobche": "Set menu description calls it veg. glass noodle; confirm the a la carte version.",
}


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "item"


def clean_category(raw: str) -> str:
    raw = raw.strip()
    for key, value in CATEGORY_MAP.items():
        if raw.startswith(key):
            return value
    return raw.split(" / ")[0].strip() or "Add-ons"


def parse_price(raw: str) -> dict:
    raw = raw.replace("Add", "").strip()
    match = re.match(r"\$([\d,]+\.\d{2})\s*/\s*(.+)$", raw)
    if not match:
        raise ValueError(f"unrecognized price: {raw!r}")

    price = float(match.group(1).replace(",", ""))
    unit = match.group(2).strip()
    lowered = unit.lower()

    people = re.search(r"(\d+)\s*people", lowered)
    if people:
        count = int(people.group(1))
        return {
            "price": price,
            "pricing_unit": "per_tray",
            "serves": {"min": count, "max": count},
            "serves_text": f"Serves {count}",
            "serves_basis": "published",
        }

    pieces = re.search(r"(\d+)\s*pcs", lowered)
    if pieces:
        count = int(pieces.group(1))
        return {
            "price": price,
            "pricing_unit": "per_tray",
            "serves": {"min": math.ceil(count / 3), "max": math.ceil(count / 2)},
            "serves_text": f"{count} pieces (assumed 2-3 per guest)",
            "serves_basis": "assumption",
        }

    if "16oz" in lowered:
        return {
            "price": price,
            "pricing_unit": "per_tray",
            "serves": {"min": 10, "max": 10},
            "serves_text": "10 x 16 oz",
            "serves_basis": "published",
        }

    if lowered == "lb":
        return {
            "price": price,
            "pricing_unit": "each",
            "serves": {"min": 3, "max": 4},
            "serves_text": "1 lb (assumed 3-4 servings)",
            "serves_basis": "assumption",
        }

    if "person" in lowered:
        return {
            "price": price,
            "pricing_unit": "per_person",
            "serves": {"min": 1, "max": 1},
            "serves_text": "Per person",
            "serves_basis": "published",
        }

    return {
        "price": price,
        "pricing_unit": "each",
        "serves": None,
        "serves_text": unit,
        "serves_basis": "assumption",
    }


def variant_label(name: str, parsed: dict) -> str:
    if name.startswith("Set Menu"):
        serves = parsed["serves"]
        return f"Set (serves {serves['min']})"
    if parsed["pricing_unit"] == "per_person":
        return "Per person"
    if parsed["serves"] is None:
        return "Each"
    text = parsed["serves_text"]
    if text.lower().startswith("serves "):
        return f"Tray ({text.lower()})"
    return f"Tray ({text})"


def main() -> None:
    html = RAW.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    items = []
    used_ids: set[str] = set()
    seen: set[tuple[str, str, str]] = set()

    for paragraph in soup.select("p.items"):
        names = [node.get_text(" ", strip=True) for node in paragraph.select("strong.name")]
        if not names:
            continue

        english = re.sub(r"\s+", " ", names[0]).strip()
        korean = re.sub(r"\s+", " ", names[1]).strip() if len(names) > 1 else None

        if not re.search(r"[A-Za-z]", english) or re.search(r"[가-힣]", english):
            continue

        price_node = paragraph.select_one("span.price")
        if price_node is None:
            continue
        price_text = price_node.get_text(" ", strip=True)

        image = paragraph.find("img")
        title = image.get("title", "") if image else ""
        match = re.match(r"ITEM#:(\d+),\s*(.*)", title)
        source_item_id = match.group(1) if match else None
        raw_category = match.group(2) if match else ""
        category = clean_category(raw_category)

        parsed = parse_price(price_text)
        key = (category, english, price_text)
        if key in seen:
            continue
        seen.add(key)

        item_id = f"gok-{slugify(english)}"
        if item_id in used_ids:
            suffix = 2
            while f"{item_id}-{suffix}" in used_ids:
                suffix += 1
            item_id = f"{item_id}-{suffix}"
        used_ids.add(item_id)

        set_match = re.match(r"Set Menu \d+([ABC])$", english)
        if set_match:
            description = SET_CONTENTS[set_match.group(1)]
        elif english.startswith("Signature Lite"):
            description = "Signature Lite set; contents are not published on the online menu."
        elif english == "Utensil":
            description = "Plate, napkin, and chopsticks."
        else:
            description = None

        dietary_tags = ["vegetarian"] if english in {"Dumplings (Veg.)", "Jobche"} else []
        dietary_note = DIETARY_NOTES.get(
            english, "Dietary tags are not published on the online menu; confirm with the caterer."
        )

        item = {
            "id": item_id,
            "name": english,
            "korean_name": korean,
            "category": category,
            "description": description,
            "dietary_tags": dietary_tags,
            "dietary_note": dietary_note,
            "allergens": [],
            "allergen_status": "unknown",
            "allergen_note": "No published allergen table; confirm with the caterer.",
            "source_item_id": source_item_id,
            "variants": [
                {
                    "id": f"{item_id}-tray",
                    "label": variant_label(english, parsed),
                    **parsed,
                }
            ],
        }
        if english == "Utensil":
            item["is_addon"] = True
        items.append(item)

    categories = sorted({item["category"] for item in items})
    dataset = {
        "meta": {
            "schema_version": "1.0.0",
            "dataset_id": "gokjee-korean-catering-los-angeles",
            "captured_at": "2026-10-18",
            "currency": "USD",
            "source": {
                "business_name": "Gok Jee Foods",
                "location": "170 S Western Ave # A, Los Angeles, CA 90004",
                "cuisine": "Korean",
                "phone": "213-480-1800",
                "menu_url": "http://www.gokjee.com/menulist.jsp?_pageid=P_E3MtzJaRCarlf1X8IAu0g",
                "menu_form_url": "http://www.gokjee.com/menuform.jsp",
                "set_menu_pdf_url": "http://www.gokjee.com/2026-catering-set-menu_list.pdf",
                "snapshots": [
                    "data/raw/gokjee-catering-menu-list-2026-10-18.html",
                    "data/raw/gokjee-catering-menu-list-2026-10-18.pdf",
                    "data/raw/gokjee-menuform-2026-10-18.html",
                    "data/raw/gokjee-2026-catering-set-menu-2026-10-18.pdf",
                ],
            },
            "branding": {
                "display_name": "Koreatown Catering Co.",
                "anonymized": True,
                "note": "Display alias only. Real source retained in meta.source and data/gokjee/source-log.md.",
            },
            "notes": [
                "Prices are transcribed from the online catering menu captured 2026-10-18.",
                "The source does not publish an allergen table; every item is marked unknown.",
                "Dietary tags are not published except for items explicitly labeled veg.",
                "Prices exclude tax. Set menus include plate, napkin, and chopsticks.",
            ],
        },
        "categories": [{"id": slugify(name), "name": name} for name in categories],
        "items": items,
    }

    OUT.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(items)} items, {len(categories)} categories)")


if __name__ == "__main__":
    main()
