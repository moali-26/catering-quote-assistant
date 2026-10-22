"""Parse Stonefire Grill's allergen table into a normalized JSON map.

Source snapshot: data/raw/stonefire-allergen-info-2026-10-18.html
The snapshot is not committed (third-party page). To rerun, save
https://www.stonefiregrill.com/allergen-info/ to that path first.
The table's second column is a "None" marker, not an allergen.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw" / "stonefire-allergen-info-2026-10-18.html"
OUT = ROOT / "allergens.json"

COLUMNS = ["none", "egg", "fish", "milk", "peanut", "soy", "tree_nuts", "wheat", "gluten"]


def main() -> None:
    soup = BeautifulSoup(RAW.read_text(encoding="utf-8"), "html.parser")
    table = soup.find("table", id="table")
    if table is None:
        raise SystemExit("allergen table not found")

    items: dict[str, dict] = {}
    category = None

    for row in table.find_all("tr"):
        heading = row.find("h2")
        if heading is not None:
            category = heading.get_text(" ", strip=True)
            continue

        cells = row.find_all("td", recursive=False)
        if len(cells) < len(COLUMNS) + 1:
            continue

        name = cells[0].get_text(" ", strip=True)
        if not name:
            continue

        marked = [
            column
            for column, cell in zip(COLUMNS, cells[1:])
            if "has_allergen" in (cell.get("class") or [])
        ]
        items[name] = {
            "category": category,
            "listed_none": "none" in marked,
            "allergens": [column for column in marked if column != "none"],
        }

    OUT.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(items)} items)")


if __name__ == "__main__":
    main()
