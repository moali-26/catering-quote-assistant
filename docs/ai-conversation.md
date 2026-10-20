# AI Conversation Service (B)

Provider-neutral conversation loop for the customer chat. Built on C's `quote_engine.ai_tool.evaluate_catering_quote`. **No LLM provider has been chosen yet**; adapters for Anthropic and OpenAI are ready, and tests run offline with a scripted fake model.

## Run

```sh
python3 -m unittest tests.test_ai_service -v      # offline, no API key
python3 -m examples.ai_conversation_demo           # scripted end-to-end demo

# Once a provider is chosen (pip install anthropic  OR  pip install openai):
export ANTHROPIC_API_KEY=...                        # or OPENAI_API_KEY + OPENAI_MODEL
python3 -m ai_service.cli --provider anthropic --now 2026-10-18T12:00:00-07:00 --debug
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

The system prompt is rebuilt every turn from the server clock and current menu/rules, including a 21-day date table so "next Friday" is a lookup, not model arithmetic.

**Price guard:** if the reply mentions a dollar amount that is not in a tool result, the customer's own messages, or the server prompt, it is discarded and the model is asked once to rewrite. If it still invents a number, a code-written summary using the computed total is sent instead.

## Integration for D (app)

```python
from ai_service import Conversation, ServerContext
from ai_service.providers import make_llm

context = ServerContext(menu=..., rules=..., capacity=...)   # trusted, from the DB
convo = Conversation(make_llm('anthropic'), context, messages=saved_messages)
turn = convo.send(customer_text)
# turn.reply           -> show in chat
# turn.ready_to_submit -> enable "Submit for owner review"
# convo.messages       -> JSON-serialisable; save it to keep the chat across requests
# convo.submission_request() -> request dict for create_quote / QuoteService
```

`submission_request()` returns the last evaluated arguments plus server-resolved `tax_location` and `delivery_miles`, without `budget_usd`. The submit endpoint must still re-run checks via C's workflow functions with current data; the conversation result is not authorization.

## Open items / decisions needed

1. **Provider and API key** — team decision. Adding another provider means one ~50-line file in `providers/`.
2. **Address → tax location and miles** — `context.demo_location_resolver` is a DEMO table (Culver City 15 mi, Torrance 3 mi). Unknown cities return `needs_server_context`. Needs a real resolver or owner verification (D/C).
3. **Final dataset** — defaults to `data/sample`; `--dataset full` loads the full primary menu. A must confirm the frozen subset.
4. **Chat persistence** — D decides whether to store `convo.messages`; only submitted quotes must persist per the plan.
5. Not yet done: live-model evaluation over held-out inquiries (with E), and conversation length limits.
