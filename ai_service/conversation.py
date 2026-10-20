"""Conversation loop: model <-> tools, with server context and safety checks.

One Conversation object per customer chat. The app (D) stores `messages`
between requests if it needs the chat to survive restarts.
"""
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from quote_engine.ai_tool import TOOL_DEFINITION as EVALUATE_TOOL, evaluate_catering_quote

from .menu_tools import SEARCH_MENU_TOOL, search_menu
from .price_guard import add_display_amounts, format_cents, unverified_amounts
from .prompts import build_system_prompt

log = logging.getLogger(__name__)

MAX_MODEL_CALLS_PER_TURN = 12
TOOLS = [SEARCH_MENU_TOOL, EVALUATE_TOOL]

FALLBACK_ERROR = ("Sorry, I ran into a problem putting that together. Could you rephrase, "
                  "or submit your request and the owner will help you directly?")
CORRECTION_NOTE = ("[Automated server check - not from the customer] Your last reply mentioned "
                   "dollar amounts that do not appear in any tool result: {amounts}. Rewrite the "
                   "reply using only amounts returned by the tools (call evaluate_catering_quote "
                   "if you need a total). Do not do arithmetic on prices.")
BUDGET_NOTE = ("[Automated server check - not from the customer] The draft you are about to present is "
               "{over} over the customer's budget. Before presenting it, swap to cheaper items or smaller "
               "quantities and call evaluate_catering_quote again. If no reasonable menu fits, present "
               "the closest option and say plainly that it is over budget.")


@dataclass
class TurnResult:
    reply: str
    # Latest evaluate_catering_quote outcome in this conversation (or None).
    quote: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ready_to_submit(self) -> bool:
        return bool(self.quote and self.quote['result'].get('status') == 'needs_owner_review')


class Conversation:
    def __init__(self, llm, context, messages=None, *, context_loader=None):
        self.llm = llm
        self.context = context
        self.context_loader = context_loader
        self.messages: List[Dict[str, Any]] = list(messages or [])
        self.latest_quote: Optional[Dict[str, Any]] = None

    # ---------- public API ----------

    def send(self, text: str) -> TurnResult:
        # Customer edits must never leave the previous request submittable.
        self.latest_quote = None
        self.messages.append({'role': 'user', 'content': text})
        turn = TurnResult(reply='')
        if self.context_loader is not None:
            try:
                # Trusted server callback bound to this chat's business, not model args.
                self.context = self.context_loader()
            except Exception:
                log.exception('business context refresh failed')
                turn.warnings.append('context_refresh_failed')
                return self._finish(turn, 'Sorry, I could not load the current menu. Please try again.')
        corrected = False
        budget_nudged = False
        for _ in range(MAX_MODEL_CALLS_PER_TURN):
            system = build_system_prompt(self.context)
            try:
                response = self.llm.generate(system, self.messages, TOOLS)
            except Exception as exc:  # provider/network failure: never crash the chat
                log.exception('model call failed')
                # Class name only (e.g. AuthenticationError): never the message, which may echo secrets.
                turn.warnings.append(f'model_error:{type(exc).__name__}')
                return self._finish(turn, self._safe_summary())

            self.messages.append({'role': 'assistant', 'content': response.content or '',
                                  'tool_calls': [asdict(c) for c in response.tool_calls]})
            if response.tool_calls:
                for call in response.tool_calls:
                    result = self._run_tool(call.name, call.arguments)
                    turn.tool_calls.append({'name': call.name, 'arguments': call.arguments,
                                            'result': result})
                    self.messages.append({'role': 'tool', 'tool_call_id': call.id,
                                          'name': call.name, 'content': json.dumps(result)})
                continue

            reply = (response.content or '').strip()
            over = self._over_budget_cents()
            if over and not budget_nudged:
                # Deterministic nudge, once per turn: try to fit the budget before presenting.
                budget_nudged = True
                turn.warnings.append(f'over_budget_retry:{over}')
                self.messages.pop()
                self.messages.append({'role': 'user', 'server_note': True,
                                      'content': BUDGET_NOTE.format(over=format_cents(over))})
                continue
            bad = unverified_amounts(reply, system, self.messages[:-1])
            if not bad:
                self.messages[-1]['content'] = reply
                return self._finish(turn, reply, stored=True)
            turn.warnings.append('unverified_amounts:' + ','.join(map(str, bad)))
            self.messages.pop()  # drop the rejected reply
            if corrected:
                return self._finish(turn, self._safe_summary())
            corrected = True
            # server_note: excluded from "customer said this amount" in the price guard
            self.messages.append({'role': 'user', 'server_note': True, 'content': CORRECTION_NOTE.format(
                amounts=', '.join(format_cents(c) for c in bad))})

        turn.warnings.append('too_many_model_calls')
        # A priced quote exists: show it (code-written) rather than an error next to "ready".
        return self._finish(turn, self._safe_summary())

    def submission_request(self) -> Optional[Dict[str, Any]]:
        """Request dict for quote_engine create_quote / QuoteService, built from the last
        evaluated tool call plus server-resolved context. None if not ready to submit."""
        quote = self.latest_quote
        if not quote or quote['result'].get('status') != 'needs_owner_review':
            return None
        request = {k: v for k, v in quote['arguments'].items() if k != 'budget_usd'}
        request['tax_location'] = quote['tax_location']
        request['delivery_miles'] = quote['delivery_miles']
        return request

    # ---------- internals ----------

    def _finish(self, turn, reply, stored=False):
        if not stored:  # code-written fallback: record it so history matches what the user saw
            self.messages.append({'role': 'assistant', 'content': reply, 'tool_calls': []})
        turn.reply = reply
        turn.quote = self.latest_quote
        return turn

    def _run_tool(self, name, arguments):
        try:
            if name == SEARCH_MENU_TOOL['name']:
                return search_menu(self.context.menu, arguments)
            if name == EVALUATE_TOOL['name']:
                return self._evaluate(arguments)
            return {'error': 'unknown_tool', 'available_tools': [t['name'] for t in TOOLS]}
        except Exception:
            if name == EVALUATE_TOOL['name']:
                self.latest_quote = None
            log.exception('tool %s failed', name)
            return {'status': 'cannot_evaluate', 'error_code': 'tool_failure'}

    def _evaluate(self, arguments):
        self.latest_quote = None
        if not isinstance(arguments, dict):
            return {'status': 'invalid_input', 'error_code': 'arguments_must_be_object'}
        tax_location, miles = self.context.location_for(arguments)
        result = evaluate_catering_quote(
            arguments, menu=self.context.menu, rules=self.context.rules,
            capacity=self.context.capacity, now=self.context.now(),
            tax_location=tax_location, delivery_miles=miles)
        self.latest_quote = {'id': str(uuid.uuid4()), 'arguments': arguments, 'result': result,
                             'tax_location': tax_location, 'delivery_miles': miles}
        return add_display_amounts(result)  # model sees "$539.60" strings; code keeps cents

    def _over_budget_cents(self):
        # Blocked requests can't be submitted anyway: fix the blocker first, not the budget.
        result = self.latest_quote and self.latest_quote['result']
        if not result or result.get('status') == 'blocked':
            return None
        budget = result.get('budget')
        if budget and budget.get('within_budget') is False:
            return budget.get('over_budget_cents') or None
        return None

    def _safe_summary(self):
        """Code-written reply when the model fails or keeps inventing amounts."""
        quote = self.latest_quote
        pricing = quote and quote['result'].get('pricing')
        if not pricing:
            return FALLBACK_ERROR
        lines = [f"- {l['name']} ({l['label']}) x{l['quantity']}: {format_cents(l['line_total_cents'])}"
                 for l in pricing['lines']]
        extras = [('Food subtotal', 'food_subtotal_cents'), ('Delivery', 'delivery_fee_cents'),
                  ('Tax', 'tax_cents')]
        lines += [f"{label}: {format_cents(pricing[key])}" for label, key in extras if pricing.get(key)]
        return ("Here is the draft quote calculated by our pricing system:\n" + "\n".join(lines) +
                f"\nTotal: {format_cents(pricing['total_cents'])}\n"
                "The owner will review it before it is final. Would you like to change anything?")
