# Owner Menu Editing (Part A) — Backend + Handoff to D

The owner can change an item's **name, description and availability**, and a size's **price and availability**. Everything else (IDs, pricing units, serving sizes, dietary tags, allergens) is fixed in the minimum build. Python backend, storage and tests are done; **the page and HTTP routes are D's**, and the Supabase migration has not been applied yet.

```sh
python3 -m unittest tests.test_menu_admin -v
```

## How it fits

```
Owner page ──► D's endpoint (verifies Auth) ──► MenuService.update ──► menus table
                                                                          │
Customer chat / submit ◄── ServerContext / QuoteService.context_for ◄─────┘ current_menu(owner_id)
```

- New chats and new quotes read `current_menu(owner_id)`, so edits apply immediately.
- Saved quotes keep their price snapshot. Approving an old draft after a price change is refused ("menu or pricing changed: create a revised draft first"), so repricing always goes through an explicit revision (C's workflow).
- Unavailable items disappear from the AI's `search_menu` and the engine rejects them.

## Wiring (D)

```python
from menu_admin import MenuService
from menu_admin.postgres_storage import PostgresMenuStore   # SQLiteMenuStore for local dev
from ai_service import ServerContext

menus = MenuService(PostgresMenuStore(), clock=utc_now)

# One-time setup script (not an HTTP route):
menus.seed(owner_uuid, json.load(open('data/demo/menu.json')))

# Shared by chat and QuoteService so both see the same current menu:
def load_current_business_context(owner_id, request):
    ctx = ServerContext(menu=menus.current_menu(owner_id), rules=rules, capacity=capacity)
    return ctx.quote_service_context(owner_id, request)
```

## Routes to build (D)

| UI action | Call | Browser sends | Server supplies |
| --- | --- | --- | --- |
| Open menu page | `owner_view(owner_id, actor_id=...)` | nothing | verified Auth ID, business owner ID |
| Save edits | `update(owner_id, changes, actor_id=..., expected_revision=...)` | `changes`, the revision shown on the page | verified Auth ID, business owner ID |
| Edit history | `change_log(owner_id, actor_id=...)` | nothing | same |

`changes` format (one save can hold several):

```json
[
  {"item_id": "dessert-brownie", "variant_id": "dessert-brownie-pp", "set": {"price": "4.29"}},
  {"item_id": "pan-tri-tip", "set": {"available": false, "name": "Smoked Tri Tip"}}
]
```

`owner_view` returns the business name, `revision`, every item with its editable fields, category, dietary tags, allergen status, and variants (label, price, unit, serves, available), plus `editable_fields`. Build the form from it; send back only fields that changed.

## Errors

| Error | Meaning | UI |
| --- | --- | --- |
| `MenuEditError` | Invalid value or field (message is owner-safe, e.g. "price can have at most 2 decimal places") | Show the message; nothing was saved |
| `MenuConflict` | Menu changed since the page loaded (another tab/device) | Reload the page, re-apply edits |
| `MenuNotFound` | No menu, **or** the user is not this business's owner | Generic "not found"; do not reveal other businesses |
| `MenuStorageUnavailable` | Database down | "Try again later"; do not claim it saved |

Validation: price > 0, ≤ $10,000, at most 2 decimals (`"4.29"`, `4.29` or `"$4.29"`); name 1–120 chars; description ≤ 600; whitespace collapsed; control characters rejected; `available` must be a real boolean. A save is all-or-nothing. Saving without any real change is rejected.

## Security notes

- `actor_id` must come from server-verified Supabase Auth, never a form field. The service checks `actor_id == owner_id`; customers and other owners get `MenuNotFound`.
- The menus table is server-only (RLS on, no client grants), same as quotes. Menus are not secret, but all writes go through Python so validation can't be skipped.
- Each save checks `expected_revision` atomically, so two tabs can't silently overwrite each other.
- The last 200 edits are kept in `change_log` with old/new values, time and editor.

## Setup checklist (D + A)

1. Apply `supabase/migrations/202610190002_menu_storage.sql` **after** C's `202610190001_quote_storage.sql` (it reuses the `catering_private` schema).
2. Seed the business menu from `data/demo/menu.json` with the owner's Auth UUID.
3. Point chat and `QuoteService` at `menus.current_menu(owner_id)` as shown above.
4. Build the owner page + routes; test as a customer (must be refused) and as the owner.

## Limits

- One owner account per business, matching C's quote model.
- Rules (minimums, fees, tax) and capacity are not owner-editable; they stay in `data/demo/`.
- The Postgres adapter has mocked contract tests only; it has not run against a live database.
- Adding new items or editing allergens/dietary tags is out of scope for the minimum build.

## Refresh an existing chat (B/D)

Bind the loader to the server-verified business ID, once per conversation. Reloading
only when creating a new chat is insufficient: an owner may edit prices while a
customer is still chatting. Use the same current-menu loader for chat and quotes:

```python
from ai_service import Conversation

def fresh_chat_context():
    return ServerContext(menu=menus.current_menu(trusted_owner_id),
                         rules=rules, capacity=capacity)

chat = Conversation(llm, fresh_chat_context(), messages=saved_messages,
                    context_loader=fresh_chat_context)
```

The loader runs before each customer turn, so both search and pricing use the new
menu. If loading fails, the turn stops without using cached data. Each new customer
turn clears submission readiness; the model must evaluate the current request again
before the submit action is enabled. Use `TurnResult.ready_to_submit` to update the UI.
The callback is server code and must not accept owner IDs from model/customer fields.
Static file demos may omit the callback. D still needs to wire this into the real chat
endpoint. QuoteService must continue reloading current data at submit/approve time;
show its returned total if prices changed after the last chat turn.
