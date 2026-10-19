"""Validate the simplified Gok Jee Foods dataset.

Run: python data/gokjee/validate_gokjee.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MENU_PATH = ROOT / "menu.json"
RULES_PATH = ROOT / "rules.json"
CAPACITY_PATH = ROOT / "capacity.json"

ALLOWED_UNITS = {"per_person", "per_tray", "per_platter", "each"}
ALLOWED_BASIS = {"published", "assumption", "not_applicable"}
ALLOWED_TAGS = {"vegan", "vegetarian", "gluten_sensitive"}

errors: list[str] = []
warnings: list[str] = []


def error(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def load(path: Path) -> dict:
    if not path.exists():
        error(f"missing file: {path.name}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        error(f"{path.name}: invalid JSON: {exc}")
        return {}


def main() -> int:
    menu = load(MENU_PATH)
    rules = load(RULES_PATH)
    capacity = load(CAPACITY_PATH)
    if not menu or not rules or not capacity:
        report()
        return 1

    meta = menu.get("meta", {})
    for key in ("schema_version", "dataset_id", "captured_at", "currency"):
        if not meta.get(key):
            error(f"menu.meta.{key} is required")
    source = meta.get("source", {})
    for key in ("business_name", "location", "cuisine", "menu_url"):
        if not source.get(key):
            error(f"menu.meta.source.{key} is required")

    categories = menu.get("categories", [])
    category_names: set[str] = set()
    category_ids: set[str] = set()
    for category in categories:
        cid = category.get("id")
        name = category.get("name")
        if not cid or not name:
            error("every category needs id and name")
            continue
        if cid in category_ids:
            error(f"duplicate category id: {cid}")
        if name in category_names:
            error(f"duplicate category name: {name}")
        category_ids.add(cid)
        category_names.add(name)

    items = menu.get("items", [])
    if not items:
        error("menu.items is empty")

    item_ids: set[str] = set()
    variant_ids: set[str] = set()
    prices: list[float] = []
    assumption_servings = 0
    tag_counts = {tag: 0 for tag in ALLOWED_TAGS}

    for item in items:
        item_id = item.get("id")
        name = item.get("name")
        if not item_id or not name:
            error("every item needs id and name")
            continue
        if item_id in item_ids:
            error(f"duplicate item id: {item_id}")
        item_ids.add(item_id)

        category = item.get("category")
        if category not in category_names:
            error(f"{item_id}: unknown category {category!r}")

        if item.get("allergen_status") != "unknown":
            error(f"{item_id}: simplified dataset requires allergen_status='unknown'")
        if item.get("allergens"):
            error(f"{item_id}: simplified dataset requires an empty allergens list")

        for tag in item.get("dietary_tags", []):
            if tag not in ALLOWED_TAGS:
                error(f"{item_id}: unknown dietary tag {tag!r}")
            else:
                tag_counts[tag] += 1

        variants = item.get("variants", [])
        if len(variants) != 1:
            warn(f"{item_id}: expected one variant in the simplified dataset")
        for variant in variants:
            vid = variant.get("id")
            if not vid:
                error(f"{item_id}: variant missing id")
                continue
            if vid in variant_ids:
                error(f"duplicate variant id: {vid}")
            variant_ids.add(vid)

            unit = variant.get("pricing_unit")
            if unit not in ALLOWED_UNITS:
                error(f"{vid}: invalid pricing_unit {unit!r}")

            price = variant.get("price")
            if not isinstance(price, (int, float)) or price < 0:
                error(f"{vid}: price must be a non-negative number")
            else:
                prices.append(float(price))

            serves = variant.get("serves")
            basis = variant.get("serves_basis")
            if basis not in ALLOWED_BASIS:
                error(f"{vid}: invalid serves_basis {basis!r}")
            if serves is None:
                if basis not in {"not_applicable", "assumption"} and not item.get("is_addon"):
                    error(f"{vid}: null serves requires not_applicable or an add-on")
            else:
                minimum = serves.get("min")
                maximum = serves.get("max")
                if not isinstance(minimum, int) or minimum < 1:
                    error(f"{vid}: serves.min must be a positive integer")
                if maximum is not None and (
                    not isinstance(maximum, int) or maximum < minimum
                ):
                    error(f"{vid}: serves.max must be null or >= serves.min")
                if unit == "per_person" and not (minimum == 1 and maximum == 1):
                    error(f"{vid}: per_person servings must be 1..1")
            if basis == "assumption":
                assumption_servings += 1

    rules_meta = rules.get("meta", {})
    if rules_meta.get("dataset_id") != meta.get("dataset_id"):
        error("rules.meta.dataset_id does not match menu.meta.dataset_id")

    modes = rules.get("service_modes", {})
    for mode in ("pickup", "delivery"):
        if mode not in modes:
            error(f"rules.service_modes missing: {mode}")
        actual = modes.get(mode, {}).get("order_minimum", {}).get("guest_count")
        if actual != 5:
            error(f"rules.{mode} minimum should be 5, got {actual}")

    fee = rules.get("delivery", {}).get("fee", {})
    if fee.get("flat_fee", -1) < 0:
        error("rules.delivery.fee.flat_fee must be non-negative")
    if fee.get("per_mile_beyond_included", -1) < 0:
        error("rules.delivery.fee.per_mile_beyond_included must be non-negative")

    tax = rules.get("tax", {})
    for location, rate in tax.get("rates", {}).items():
        if not 0 < rate < 0.2:
            error(f"rules.tax.rates.{location} is not a plausible rate")
    if tax.get("default_rate") not in tax.get("rates", {}).values():
        error("rules.tax.default_rate must appear in rules.tax.rates")

    if not rules.get("assumptions"):
        error("rules.assumptions is empty")

    capacity_meta = capacity.get("meta", {})
    if capacity_meta.get("synthetic") is not True:
        error("capacity.meta.synthetic must be true")
    if capacity_meta.get("dataset_id") != meta.get("dataset_id"):
        error("capacity.meta.dataset_id does not match menu.meta.dataset_id")

    defaults = capacity.get("defaults", {})
    max_events = defaults.get("max_events_per_day")
    max_guests = defaults.get("max_guests_per_day")
    max_per_event = defaults.get("max_guests_per_event")
    if not isinstance(max_events, int) or max_events < 1:
        error("capacity.defaults.max_events_per_day must be a positive integer")
        max_events = 0
    if not isinstance(max_guests, int) or max_guests < 1:
        error("capacity.defaults.max_guests_per_day must be a positive integer")
        max_guests = 0
    if not isinstance(max_per_event, int) or not 1 <= max_per_event <= max_guests:
        error("capacity.defaults.max_guests_per_event must be 1..max_guests_per_day")

    def check_iso_date(value: str, label: str) -> date | None:
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            error(f"capacity.{label}: invalid ISO date {value!r}")
            return None

    for value in capacity.get("closed_dates", {}):
        check_iso_date(value, "closed_dates")

    for value, entry in capacity.get("exceptions", {}).items():
        check_iso_date(value, "exceptions")
        status = entry.get("status")
        if status not in {"open", "full", "closed"}:
            error(f"capacity.exceptions.{value}: invalid status {status!r}")
        booked_events = entry.get("booked_events", 0)
        booked_guests = entry.get("booked_guests", 0)
        if not isinstance(booked_events, int) or not 0 <= booked_events <= max_events:
            error(f"capacity.exceptions.{value}: booked_events must be 0..{max_events}")
        if not isinstance(booked_guests, int) or not 0 <= booked_guests <= max_guests:
            error(f"capacity.exceptions.{value}: booked_guests must be 0..{max_guests}")

    report(items=len(items), variants=len(variant_ids), categories=len(categories), prices=prices, tag_counts=tag_counts, assumption_servings=assumption_servings)
    return 0 if not errors else 1


def report(
    items: int = 0,
    variants: int = 0,
    categories: int = 0,
    prices: list[float] | None = None,
    tag_counts: dict[str, int] | None = None,
    assumption_servings: int = 0,
) -> None:
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for message in errors:
            print(f"  ERROR  {message}")
    else:
        print("OK: Gok Jee dataset is structurally valid")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for message in warnings:
            print(f"  WARN   {message}")
    if items:
        print("\nSummary")
        print(f"  items: {items}")
        print(f"  variants: {variants}")
        print(f"  categories: {categories}")
        if prices:
            print(f"  price range: ${min(prices):.2f} - ${max(prices):.2f}")
        print(f"  assumed serving sizes: {assumption_servings}")
        if tag_counts:
            print("  dietary tags: " + ", ".join(f"{k}={v}" for k, v in tag_counts.items()))


if __name__ == "__main__":
    sys.exit(main())
