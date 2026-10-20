# AI Conversation Service (B)

Provider-neutral conversation loop for the customer chat. Built on C's `quote_engine.ai_tool.evaluate_catering_quote`. **The deployed app uses OpenAI `gpt-5.5`**; adapters for OpenAI and Anthropic are ready, and tests run offline with a scripted fake model.

## Run

```sh
python3 -m unittest tests.test_ai_service -v      # offline, no API key
python3 -m examples.ai_conversation_demo           # scripted end-to-end demo

# Live model (pip install openai  OR  pip install anthropic):
export OPENAI_API_KEY=... OPENAI_MODEL=gpt-5.5     # or ANTHROPIC_API_KEY
python3 -m ai_service.cli --provider openai --now 2026-10-18T12:00:00-07:00 --debug
```

`--now` freezes the clock; the sample inquiries assume October 18, 2026.

## How it works

| Step | Who | Where |
| --- | --- | --- |
| Understand message, ask questions, pick items | Model | `prompts.py` system prompt |
| Find real item/variant IDs (dietary, allergen filters) | Code | `menu_tools.search_menu` |
| Totals, fees, tax, budget, lead time, capacity, allergen checks | Code (C) | `quote_engine.ai_tool` |
| Current time, tax location, delivery miles | Server | `context.ServerContext` |
| Reject replies with dollar amounts not from tools/customer | Code | `price_guard.py` |
| Translate to a provider API | Adapter | `providers/` |

The system prompt is rebuilt every turn from the server clock and current menu/rules, including a 35-day date table so "next Friday" is a lookup, not model arithmetic. Each date lists its UTC offset, because Pacific time changes when daylight saving time ends.

**Price guard:** if the reply mentions a dollar amount that is not in a tool result, the customer's own messages, or the server prompt, it is discarded and the model is asked once to rewrite. If it still invents a number, a code-written summary using the computed total is sent instead.

## Integration for D (app)

```python
from ai_service import Conversation, ServerContext
from ai_service.providers import make_llm

context = ServerContext(menu=..., rules=..., capacity=...)   # trusted, from the DB
convo = Conversation(make_llm('openai'), context, messages=saved_messages)
turn = convo.send(customer_text)
# turn.reply           -> show in chat
# turn.ready_to_submit -> enable "Submit for owner review"
# convo.messages       -> JSON-serialisable; save it to keep the chat across requests
# convo.submission_request() -> request dict for create_quote / QuoteService
```

`submission_request()` returns the last evaluated arguments plus server-resolved `tax_location` and `delivery_miles`, without `budget_usd`. The submit endpoint must still re-run checks via C's workflow functions with current data; the conversation result is not authorization.

**Submit through C's `QuoteService`** and share the same context so chat pricing and the saved quote resolve the address identically:

```python
from quote_engine.service import QuoteService

service = QuoteService(store, context_for=context.quote_service_context, clock=context.now)
if turn.ready_to_submit:
    view = service.submit(convo.submission_request(), actor_id=auth_customer_id, owner_id=business_owner_id)
```

`QuoteService` overwrites tax/miles from `context_for`, so the values in the request are not trusted. `tests/test_ai_service.py::test_chat_to_quote_service_submit_and_my_quotes` covers chat → submit → My Quotes with the SQLite store.

## Decisions and open items

1. **Provider: OpenAI `gpt-5.5` in the deployed app.** Set `OPENAI_API_KEY` and `OPENAI_MODEL` (never commit the key). The Anthropic adapter is still available (`ANTHROPIC_API_KEY`, default model `claude-sonnet-5-5`).
2. **Address → tax location and miles** — `context.demo_location_resolver` is a DEMO table (Culver City 15 mi, Torrance 3 mi). Unknown cities return `needs_server_context`. Needs a real resolver or owner verification (D/C).
3. **Final dataset** — the CLI and the web app use the frozen `data/demo` menu (22 items); `--dataset sample` or `--dataset full` loads the others.
4. **Chat persistence** — the web app saves `convo.messages` per conversation (see [app.md](app.md)), so a refresh or sign-out keeps the chat.
5. Live-model evaluation over 22 held-out inquiries is in [evaluation/](../evaluation/README.md); conversation length and cost limits are in the web app (see [app.md](app.md)).
