"""Validate the lightweight sample fixture and its hand-checked quote.

Run: python data/sample/validate_sample.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MENU_PATH = ROOT / "menu.json"
RULES_PATH = ROOT / "rules.json"
CAPACITY_PATH = ROOT / "capacity.json"
INQUIRIES_PATH = ROOT / "inquiries.json"

ALLOWED_UNITS = {"per_person", "per_tray", "per_platter", "each"}
ALLOWED_BASIS = {"published", "assumption", "not_applicable"}
ALLOWED_STATUS = {"listed", "listed_none", "unknown", "depends_on_selection"}

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


def money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main() -> int:
    menu = load(MENU_PATH)
    rules = load(RULES_PATH)
    capacity = load(CAPACITY_PATH)
    inquiries = load(INQUIRIES_PATH)
    if not menu or not rules or not capacity or not inquiries:
        report()
        return 1

    menu_meta = menu.get("meta", {})
    dataset_id = menu_meta.get("dataset_id")
    if menu_meta.get("sample") is not True:
        error("menu.meta.sample must be true")
    for name, doc in (("rules", rules), ("capacity", capacity), ("inquiries", inquiries)):
        if doc.get("meta", {}).get("dataset_id") != dataset_id:
            error(f"{name}.meta.dataset_id does not match menu.meta.dataset_id")

    categories = {category.get("name") for category in menu.get("categories", [])}
    tag_definitions = set(menu.get("dietary_tag_definitions", {}))
    allergen_definitions = set(menu.get("allergen_definitions", []))

    items: dict[str, dict] = {}
    variants: dict[str, dict] = {}
    for item in menu.get("items", []):
        item_id = item.get("id")
        if not item_id:
            error("item missing id")
            continue
        if item_id in items:
            error(f"duplicate item id: {item_id}")
        items[item_id] = item
        if item.get("category") not in categories:
            error(f"{item_id}: unknown category {item.get('category')!r}")
        if item.get("allergen_status") not in ALLOWED_STATUS:
            error(f"{item_id}: invalid allergen_status")
        for allergen in item.get("allergens", []):
            if allergen not in allergen_definitions:
                error(f"{item_id}: unknown allergen {allergen!r}")
        for tag in item.get("dietary_tags", []):
            if tag not in tag_definitions:
                error(f"{item_id}: unknown dietary tag {tag!r}")
        if not item.get("variants"):
            error(f"{item_id}: no variants")
        for variant in item.get("variants", []):
            variant_id = variant.get("id")
            if not variant_id:
                error(f"{item_id}: variant missing id")
                continue
            if variant_id in variants:
                error(f"duplicate variant id: {variant_id}")
            variants[variant_id] = {"item": item, "variant": variant}
            if variant.get("pricing_unit") not in ALLOWED_UNITS:
                error(f"{variant_id}: invalid pricing_unit")
            if not isinstance(variant.get("price"), (int, float)) or variant["price"] < 0:
                error(f"{variant_id}: invalid price")
            if variant.get("serves_basis") not in ALLOWED_BASIS:
                error(f"{variant_id}: invalid serves_basis")
            serves = variant.get("serves")
            if serves is not None:
                minimum = serves.get("min")
                maximum = serves.get("max")
                if not isinstance(minimum, int) or minimum < 1:
                    error(f"{variant_id}: invalid serves.min")
                if maximum is not None and (not isinstance(maximum, int) or maximum < minimum):
                    error(f"{variant_id}: invalid serves.max")
                if variant.get("pricing_unit") == "per_person" and not (minimum == 1 and maximum == 1):
                    error(f"{variant_id}: per_person must serve 1..1")

    if len(items) != 9:
        warn(f"expected 9 items, found {len(items)}")
    if len(variants) != 15:
        warn(f"expected 15 variants, found {len(variants)}")

    modes = rules.get("service_modes", {})
    for mode in ("pickup", "delivery", "full_service"):
        if mode not in modes:
            error(f"rules.service_modes missing: {mode}")
    if modes.get("pickup", {}).get("order_minimum", {}).get("guest_count") != 10:
        error("pickup minimum should be 10")
    if modes.get("delivery", {}).get("order_minimum", {}).get("guest_count") != 20:
        error("delivery minimum should be 20")
    if modes.get("delivery", {}).get("order_minimum", {}).get("subtotal") != 300.0:
        error("delivery subtotal minimum should be 300.0")
    if modes.get("full_service", {}).get("order_minimum", {}).get("guest_count") != 30:
        error("full-service minimum should be 30")

    fee = rules.get("delivery", {}).get("fee", {})
    if fee.get("flat_fee") != 50.0:
        error("delivery flat fee should be 50.0")
    if fee.get("included_miles") != 15.0:
        error("delivery included miles should be 15.0")
    if fee.get("per_mile_beyond_included") != 2.5:
        error("delivery per-mile rate should be 2.5")

    tax = rules.get("tax", {})
    if tax.get("default_rate") != 0.1125:
        error("default tax rate should be 0.1125")
    if tax.get("rates", {}).get("Culver City") != 0.1125:
        error("Culver City tax rate should be 0.1125")

    capacity_defaults = capacity.get("defaults", {})
    if capacity.get("meta", {}).get("synthetic") is not True:
        error("capacity.meta.synthetic must be true")
    if capacity_defaults.get("max_events_per_day", 0) < 1:
        error("capacity defaults invalid")
    exceptions = capacity.get("exceptions", {})
    if exceptions.get("2026-10-24", {}).get("status") != "full":
        error("2026-10-24 should be full in the sample capacity")
    if exceptions.get("2026-10-23", {}).get("status") != "open":
        error("2026-10-23 should be open in the sample capacity")

    cases = inquiries.get("inquiries", [])
    if len(cases) != 5:
        warn(f"expected 5 inquiries, found {len(cases)}")
    expected_statuses = {"quote", "clarify", "capacity_conflict", "lead_time_conflict"}
    seen_case_ids: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id:
            error("inquiry missing id")
            continue
        if case_id in seen_case_ids:
            error(f"duplicate inquiry id: {case_id}")
        seen_case_ids.add(case_id)
        expected = case.get("expected", {})
        if expected.get("status") not in expected_statuses:
            error(f"{case_id}: invalid expected status {expected.get('status')!r}")
        if "date" in expected:
            try:
                date.fromisoformat(expected["date"])
            except (TypeError, ValueError):
                error(f"{case_id}: invalid expected date")

    example = inquiries.get("pricing_example", {})
    expected_quote = example.get("expected", {})
    if not example.get("selections") or not expected_quote:
        error("pricing_example is missing selections or expected values")
    else:
        food_subtotal = 0.0
        flags: list[str] = []
        for selection in example["selections"]:
            item_id = selection.get("item_id")
            variant_id = selection.get("variant_id")
            quantity = selection.get("quantity")
            if variant_id not in variants:
                error(f"pricing_example: unknown variant {variant_id!r}")
                continue
            item = variants[variant_id]["item"]
            variant = variants[variant_id]["variant"]
            if item.get("id") != item_id:
                error(f"pricing_example: variant {variant_id} does not belong to {item_id}")
            if not isinstance(quantity, int) or quantity < 1:
                error(f"pricing_example: invalid quantity for {variant_id}")
                continue
            food_subtotal += variant["price"] * quantity
            if item.get("allergen_status") == "depends_on_selection":
                flags.append(f"allergen_depends_on_selection:{item_id}")

        food_subtotal = money(food_subtotal)
        miles = example.get("delivery_miles", 0.0)
        delivery_fee = fee["flat_fee"]
        if miles > fee["included_miles"]:
            delivery_fee += (miles - fee["included_miles"]) * fee["per_mile_beyond_included"]
        delivery_fee = money(delivery_fee)
        service_charge = 0.0
        staffing_fee = 0.0
        taxable = money(food_subtotal + delivery_fee + service_charge + staffing_fee)
        tax_amount = money(taxable * tax["default_rate"])
        total = money(food_subtotal + delivery_fee + service_charge + staffing_fee + tax_amount)

        checks = {
            "food_subtotal": food_subtotal,
            "delivery_fee": delivery_fee,
            "service_charge": service_charge,
            "staffing_fee": staffing_fee,
            "taxable_subtotal": taxable,
            "tax": tax_amount,
            "total": total,
        }
        for key, actual in checks.items():
            expected = expected_quote.get(key)
            if expected is None:
                error(f"pricing_example.expected missing {key}")
            elif abs(float(expected) - actual) > 0.01:
                error(f"pricing_example.{key}: expected {expected}, got {actual}")

        expected_flags = set(expected_quote.get("flags", []))
        if not set(flags).issubset(expected_flags):
            error(f"pricing_example.flags missing: {sorted(set(flags) - expected_flags)}")

    report(items=len(items), variants=len(variants), cases=len(cases))
    return 0 if not errors else 1


def report(items: int = 0, variants: int = 0, cases: int = 0) -> None:
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for message in errors:
            print(f"  ERROR  {message}")
    else:
        print("OK: sample fixture is valid and the expected quote matches")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for message in warnings:
            print(f"  WARN   {message}")
    if items:
        print("\nSummary")
        print(f"  items: {items}")
        print(f"  variants: {variants}")
        print(f"  inquiries: {cases}")


if __name__ == "__main__":
    sys.exit(main())
