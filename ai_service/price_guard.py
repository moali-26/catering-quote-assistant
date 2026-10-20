"""Checks that every dollar amount in the AI's reply came from code or the customer.

This is the "not just an LLM wrapper" safety net: if the model invents or does its
own arithmetic on a price, the reply is rejected and regenerated.
"""
import json
import re
from decimal import Decimal, InvalidOperation

_DOLLAR = re.compile(r'\$\s?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)')


def amounts_in_text(text):
    """Return the set of dollar amounts in text, as integer cents."""
    found = set()
    for match in _DOLLAR.finditer(text or ''):
        try:
            value = Decimal(match.group(1).replace(',', ''))
        except InvalidOperation:
            continue
        found.add(int((value * 100).to_integral_value()))
    return found


def amounts_in_tool_result(obj):
    """Collect cents from *_cents fields and "$x.xx" strings anywhere in a tool result."""
    found = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.endswith('_cents') and type(value) is int:
                found.add(value)
            else:
                found |= amounts_in_tool_result(value)
    elif isinstance(obj, list):
        for value in obj:
            found |= amounts_in_tool_result(value)
    elif isinstance(obj, str):
        found |= amounts_in_text(obj)
    return found


def allowed_amounts(system_prompt, messages):
    """Amounts the reply may mention: from tool results, customer messages, and the prompt."""
    allowed = amounts_in_text(system_prompt)
    for message in messages:
        if message['role'] == 'user' and not message.get('server_note'):
            allowed |= amounts_in_text(message.get('content', ''))
        elif message['role'] == 'tool':
            try:
                allowed |= amounts_in_tool_result(json.loads(message['content']))
            except (TypeError, ValueError):
                allowed |= amounts_in_text(message.get('content', ''))
    return allowed


def unverified_amounts(reply, system_prompt, messages):
    """Return sorted cents values in reply that no trusted source supports."""
    return sorted(amounts_in_text(reply) - allowed_amounts(system_prompt, messages))


def format_cents(cents):
    return f"${Decimal(cents) / 100:,.2f}"


def add_display_amounts(result):
    """Copy of a tool result with ready-made dollar strings next to every *_cents field.

    Small models misread cents (writing 53960 as $53,960). Giving them "$539.60" to copy
    removes the conversion entirely; the cents fields stay for code.
    """
    if isinstance(result, dict):
        out = {}
        for key, value in result.items():
            out[key] = add_display_amounts(value)
            if isinstance(key, str) and key.endswith('_cents') and type(value) is int:
                out[key[:-len('_cents')] + '_display'] = format_cents(value)
        return out
    if isinstance(result, list):
        return [add_display_amounts(v) for v in result]
    return result
