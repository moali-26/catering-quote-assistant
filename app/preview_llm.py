"""A stand-in model for local previews and browser tests (LLM_PROVIDER=scripted, never production).

It behaves like a very literal assistant: on the first message it asks for missing
details; once the customer has written a few words it prices one fixed sample order
through the real tools and summarises the tool result. Amounts in its replies come
only from tool output, so the price guard accepts them.
"""
import json
from datetime import timedelta

from ai_service.llm import LLMResponse, ToolCall

ASK = ('Happy to help! To put a quote together I need the date and time, how many guests, '
       'pickup or delivery (and the address), any food allergies, and what you’d like to serve.')


class PreviewLLM:
    def __init__(self, clock):
        self.clock = clock

    def _request(self):
        now = self.clock()
        days = (4 - now.weekday()) % 7 + 7  # next week's Friday, matching the sample request
        event = (now + timedelta(days=days)).replace(hour=12, minute=0, second=0, microsecond=0)
        return {'headcount': 40, 'event_at': event.isoformat(), 'service_mode': 'delivery',
                'address': '9300 Culver Blvd, Culver City, CA', 'allergens': [],
                'selections': [{'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': 40},
                               {'item_id': 'side-garlic-mashed', 'variant_id': 'side-garlic-mashed-full', 'quantity': 1}]}

    def generate(self, system, messages, tools):
        last = messages[-1]
        if last['role'] == 'tool':
            result = json.loads(last['content'])
            pricing = result.get('pricing') or {}
            total = pricing.get('total_display') or pricing.get('total')
            if result.get('status') == 'needs_owner_review' and total:
                return LLMResponse(content=f'Here’s a draft for 40 guests: The Pasta Duo for everyone plus a full '
                                           f'tray of garlic mashed potatoes, delivered. The total comes to {total} '
                                           f'including delivery and tax. If that looks right, send it to the owner '
                                           f'for review.')
            return LLMResponse(content='I couldn’t price that yet. Could you confirm the date, guest count and address?')
        customer_turns = sum(1 for m in messages if m['role'] == 'user' and not m.get('server_note'))
        if customer_turns == 1 and len(last.get('content', '')) < 40:
            return LLMResponse(content=ASK)
        return LLMResponse(tool_calls=[ToolCall('preview-1', 'evaluate_catering_quote', self._request())])
