"""Offline demo of the conversation loop with a scripted (fake) model.

    python3 -m examples.ai_conversation_demo

No API key needed. The "model" turns are pre-written; everything else (menu search,
pricing, checks, price guard, server context) is the real code path.
"""
import json

from ai_service import Conversation, LLMResponse, ScriptedLLM, ToolCall
from ai_service.data_loader import load_context

ARGS = {
    'headcount': 40, 'event_at': '2026-10-23T12:00:00-07:00', 'service_mode': 'delivery',
    'address': '123 Main St, Culver City, CA', 'allergens': ['peanut', 'tree_nuts'],
    'budget_usd': '800.00',
    'selections': [
        {'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': 40},
        {'item_id': 'side-garlic-mashed', 'variant_id': 'side-garlic-mashed-full', 'quantity': 1},
    ],
}


def tool(name, args, id_):
    return LLMResponse(tool_calls=[ToolCall(id=id_, name=name, arguments=args)])


def present_quote(system, messages, tools):
    result = json.loads([m for m in messages if m['role'] == 'tool'][-1]['content'])
    p = result['pricing']
    money = lambda c: f'${c // 100}.{c % 100:02d}'
    lines = '\n'.join(f"- {l['name']} x{l['quantity']}: {money(l['line_total_cents'])}" for l in p['lines'])
    return LLMResponse(content=(
        f"Here's a draft for 40 guests on Fri Oct 23 at noon:\n{lines}\n"
        f"Delivery: {money(p['delivery_fee_cents'])}  Tax: {money(p['tax_cents'])}\n"
        f"Total: {money(p['total_cents'])} (within your budget).\n"
        "The Pasta Duo's allergens depend on the pastas chosen, so the owner will confirm the "
        "nut allergy. You can submit this for owner review and check it later in My Quotes."))


def main():
    llm = ScriptedLLM([
        tool('evaluate_catering_quote', {'headcount': 40}, 'c1'),
        LLMResponse(content='Great! What time on Friday Oct 23, what is the delivery address, '
                            'and are there any food allergies?'),
        tool('search_menu', {'dietary': ['vegetarian'], 'exclude_allergens': ['peanut', 'tree_nuts']}, 'c2'),
        tool('evaluate_catering_quote', ARGS, 'c3'),
        present_quote,
    ])
    convo = Conversation(llm, load_context('sample', '2026-10-18T12:00:00-07:00'))
    for text in ['Lunch for 40 next Friday at our Culver City office, a few vegetarians.',
                 'Noon, 123 Main St Culver City. One peanut + tree nut allergy. Budget $800.']:
        print(f'Customer: {text}')
        turn = convo.send(text)
        for c in turn.tool_calls:
            print(f"  [tool] {c['name']} -> status={c['result'].get('status', 'ok')}")
        print(f'Assistant: {turn.reply}\n')
    print('Ready to submit:', turn.ready_to_submit)
    print('Request for quote_engine.create_quote:')
    print(json.dumps(convo.submission_request(), indent=2))


if __name__ == '__main__':
    main()
