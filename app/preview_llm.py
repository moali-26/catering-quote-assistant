"""A stand-in model for local previews and browser tests (LLM_PROVIDER=scripted, never production).

It behaves like a very literal assistant: on the first message it asks for missing
details; once the customer has written a few words it prices a sample order through the
real tools and summarises the tool result. It picks up the basics the customer typed
(guest count, pickup or delivery, a street address, a nut or dairy allergy, a budget) so a
demo never shows details the customer didn't give; the menu items are always the same. Amounts in its replies come
only from tool output, so the price guard accepts them.
"""
import json
import re
from datetime import timedelta

from ai_service.llm import LLMResponse, ToolCall

ASK = ('Happy to help! To put a quote together I need the date and time, how many guests, '
       'pickup or delivery (and the address), any food allergies, and what you’d like to serve.')


class PreviewLLM:
    def __init__(self, clock):
        self.clock = clock

    def _request(self, text):
        now = self.clock()
        days = (4 - now.weekday()) % 7 + 7  # next week's Friday, matching the sample request
        event = (now + timedelta(days=days)).replace(hour=12, minute=0, second=0, microsecond=0)
        lower = text.lower()
        guests = re.search(r'(\d{1,4})\s*(?:people|guests|persons|ppl)', lower) or re.search(r'for\s+(\d{1,4})\b', lower)
        headcount = max(1, min(int(guests.group(1)), 500)) if guests else 40
        pickup = 'pickup' in lower or 'pick up' in lower or 'pick-up' in lower
        allergens = []
        if re.search(r'\bnuts?\b|peanut', lower) and not re.search(r'no (nut|allerg)', lower):
            allergens += ['peanut', 'tree_nuts']
        if re.search(r'dairy|lactose|milk allerg', lower):
            allergens.append('milk')
        street = re.search(r'\b\d{2,6}\s+[A-Za-z][A-Za-z .]{2,40}?\b(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Way)\b\.?', text)
        request = {'headcount': headcount, 'event_at': event.isoformat(),
                   'service_mode': 'pickup' if pickup else 'delivery', 'allergens': allergens,
                   'selections': [{'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': headcount}]}
        if 'milk' not in allergens:
            request['selections'].append({'item_id': 'side-garlic-mashed', 'variant_id': 'side-garlic-mashed-full',
                                          'quantity': max(1, round(headcount / 40))})
        if not pickup:
            request['address'] = (street.group(0).strip() + ', Culver City, CA') if street else '9300 Culver Blvd, Culver City, CA'
        choices = re.search(r'pasta duo[^.?!]*?\bwith\s+([^.?!]+)', text, re.I)
        if choices:  # e.g. "The Pasta Duo ..., with marinara and mac & cheese, plus the garden salad"
            parts = re.split(r',?\s*\bplus\b\s*(?:the\s+)?', choices.group(1).strip(), flags=re.I)
            request['customer_notes'] = 'Pasta Duo: ' + '; '.join(x.strip(' ,') for x in parts if x.strip(' ,'))
        budget = re.search(r'\$\s?(\d{2,6})(?:\.\d{2})?', text)
        if budget:
            request['budget_usd'] = budget.group(1)
        return request

    def generate(self, system, messages, tools):
        last = messages[-1]
        if last['role'] == 'tool':
            result = json.loads(last['content'])
            pricing = result.get('pricing') or {}
            total = pricing.get('total_display') or pricing.get('total')
            if result.get('status') == 'needs_owner_review' and total:
                return LLMResponse(content=f'Here’s a draft priced from the menu: The Pasta Duo for everyone, '
                                           f'with a side where it fits your allergies. The total comes to {total}. '
                                           f'If the draft details look right, send it to the owner for review.')
            if 'unavailable' in json.dumps(result).lower():
                return LLMResponse(content='That dish isn’t available right now, so I can’t price it. Would you like something else from the menu?')
            return LLMResponse(content='I couldn’t price that yet. Could you confirm the date, guest count and address?')
        customer_turns = sum(1 for m in messages if m['role'] == 'user' and not m.get('server_note'))
        if customer_turns == 1 and len(last.get('content', '')) < 40:
            return LLMResponse(content=ASK)
        said = ' '.join(m.get('content', '') for m in messages if m['role'] == 'user' and not m.get('server_note'))
        return LLMResponse(tool_calls=[ToolCall('preview-1', 'evaluate_catering_quote', self._request(said))])
