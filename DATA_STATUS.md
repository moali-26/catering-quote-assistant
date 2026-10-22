# Data status

Updated October 22, 2026.

- **App and evaluation:** `data/demo/`, 22 items and 37 variants. Owner edits use database-backed menu storage.
- **Test fixtures:** `data/sample/`, retained for unit tests and offline examples.
- **Source and validation:** the full primary dataset, Stonefire snapshots and allergen parser remain because the demo builder, provenance validator and tests depend on them.
- **Removed:** unused second-caterer dataset, its parser/validator and five PDF/HTML snapshots. No application code used that dataset.
- **Unchanged:** active menus, prices, item IDs, allergen information, rules, capacity, saved quotes and evaluation cases.

See [README](README.md#menu-data), [demo details](data/demo/README.md), [source log](data/source-log.md) and [assumptions](data/assumptions.md).

Deleted files remain recoverable in Git history. This cleanup does not change repository visibility or rewrite history.
