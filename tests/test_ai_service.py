"""Offline tests for B's conversation service. No API key or network needed."""
import json
import unittest
from types import SimpleNamespace

from ai_service import Conversation, LLMResponse, ScriptedLLM, ToolCall
from ai_service.data_loader import load_context
from ai_service.menu_tools import search_menu
from ai_service.price_guard import amounts_in_text, unverified_amounts
from ai_service.prompts import build_system_prompt
from ai_service.providers.anthropic_provider import (from_anthropic_response,
                                                     to_anthropic_messages)
from ai_service.providers.openai_provider import from_openai_response, to_openai_messages
from quote_engine import create_quote

NOW = '2026-10-18T12:00:00-07:00'
FULL_ARGS = {
    'headcount': 40, 'event_at': '2026-10-23T12:00:00-07:00', 'service_mode': 'delivery',
    'address': '123 Main St, Culver City, CA', 'allergens': ['peanut', 'tree_nuts'],
    'budget_usd': '800.00',
    'selections': [
        {'item_id': 'pkg-pasta-duo', 'variant_id': 'pkg-pasta-duo-pp', 'quantity': 40},
        {'item_id': 'side-garlic-mashed', 'variant_id': 'side-garlic-mashed-full', 'quantity': 1},
    ],
}


def call(name, args, id_='c1'):
    return LLMResponse(tool_calls=[ToolCall(id=id_, name=name, arguments=args)])


def say(text):
    return LLMResponse(content=text)


def last_tool_result(messages):
    return json.loads([m for m in messages if m['role'] == 'tool'][-1]['content'])


def reply_with_total(system, messages, tools):
    total = last_tool_result(messages)['pricing']['total_cents']
    return say(f'Your draft total is ${total // 100}.{total % 100:02d}. The owner will review it.')


class Base(unittest.TestCase):
    def setUp(self):
        self.ctx = load_context('sample', NOW)

    def convo(self, script):
        self.llm = ScriptedLLM(script)
        return Conversation(self.llm, self.ctx)


class MenuSearchTests(Base):
    def test_vegetarian_includes_vegan_and_excludes_listed_allergens(self):
        out = search_menu(self.ctx.menu, {'dietary': ['vegetarian'], 'exclude_allergens': ['sesame']})
        ids = {i['item_id'] for i in out['items']}
        self.assertIn('salad-garden', ids)          # vegan counts as vegetarian
        self.assertNotIn('app-hummus', ids)         # lists sesame
        self.assertNotIn('salad-caesar', ids)       # not vegetarian-tagged
        self.assertIn('allergen_reminder', out)

    def test_unknown_allergen_name_warns(self):
        out = search_menu(self.ctx.menu, {'exclude_allergens': ['nuts']})
        self.assertIn('warning', out)

    def test_unavailable_items_hidden(self):
        self.ctx.menu['items'][0]['available'] = False
        out = search_menu(self.ctx.menu, {})
        self.assertNotIn(self.ctx.menu['items'][0]['id'], {i['item_id'] for i in out['items']})

    def test_rejects_unexpected_fields(self):
        self.assertEqual(search_menu(self.ctx.menu, {'price': 1})['error'], 'unexpected_fields')


class PromptTests(Base):
    def test_prompt_has_server_date_table_and_rules(self):
        prompt = build_system_prompt(self.ctx)
        self.assertIn('Sunday 2026-10-18 (today)', prompt)
        self.assertIn('Friday 2026-10-23', prompt)
        self.assertIn('Sample Catering Co.', prompt)
        self.assertNotIn('Stonefire', prompt)       # display alias only
        self.assertIn('tree_nuts', prompt)


class ConversationTests(Base):
    def test_clarification_then_full_quote(self):
        convo = self.convo([
            call('evaluate_catering_quote', {'headcount': 40}),
            say('Happy to help! What time on Friday Oct 23, and what is the delivery address? '
                'Any food allergies?'),
            call('search_menu', {'dietary': ['vegetarian'], 'exclude_allergens': ['peanut', 'tree_nuts']}),
            call('evaluate_catering_quote', FULL_ARGS, 'c2'),
            reply_with_total,
        ])
        t1 = convo.send('Lunch for 40 next Friday at our Culver City office.')
        self.assertEqual(t1.quote['result']['status'], 'needs_clarification')
        self.assertFalse(t1.ready_to_submit)

        t2 = convo.send('Noon, 123 Main St Culver City. One peanut and tree nut allergy. Budget $800.')
        self.assertEqual(t2.warnings, [])
        self.assertTrue(t2.ready_to_submit)
        total = t2.quote['result']['pricing']['total_cents']
        self.assertIn(f'{total // 100}.{total % 100:02d}', t2.reply)
        # server-resolved context, not from the model
        self.assertEqual(t2.quote['tax_location'], 'Culver City')
        self.assertEqual(t2.quote['delivery_miles'], 15.0)

    def test_submission_request_is_accepted_by_quote_engine(self):
        convo = self.convo([call('evaluate_catering_quote', FULL_ARGS), reply_with_total])
        convo.send('...')
        request = convo.submission_request()
        self.assertNotIn('budget_usd', request)
        record = create_quote(self.ctx.menu, self.ctx.rules, request, owner_id='owner-1',
                              customer_id='cust-1', now=self.ctx.now(), capacity=self.ctx.capacity)
        self.assertEqual(record['versions'][-1]['readiness']['pricing']['total_cents'],
                         convo.latest_quote['result']['pricing']['total_cents'])

    def test_chat_to_quote_service_submit_and_my_quotes(self):
        import tempfile
        from pathlib import Path
        from quote_engine.service import QuoteService
        from quote_engine.storage import SQLiteQuoteStore
        convo = self.convo([call('evaluate_catering_quote', FULL_ARGS), reply_with_total])
        convo.send('...')
        with tempfile.TemporaryDirectory() as folder:
            service = QuoteService(SQLiteQuoteStore(Path(folder) / 'q.sqlite3'),
                                   context_for=self.ctx.quote_service_context, clock=self.ctx.now)
            view = service.submit(convo.submission_request(), actor_id='cust-1', owner_id='owner-1')
            self.assertEqual(view['pricing']['amounts']['total_cents']['cents'],
                             convo.latest_quote['result']['pricing']['total_cents'])
            mine = service.list_quotes(actor_id='cust-1', workspace='customer')
            self.assertEqual(len(mine), 1)

    def test_model_cannot_supply_tax_or_distance(self):
        convo = self.convo([call('evaluate_catering_quote', dict(FULL_ARGS, tax_location='Torrance')),
                            say('Let me fix that.')])
        turn = convo.send('...')
        self.assertEqual(turn.tool_calls[0]['result']['status'], 'invalid_input')

    def test_unknown_city_needs_server_context(self):
        convo = self.convo([call('evaluate_catering_quote', dict(FULL_ARGS, address='1 Main St, Pasadena')),
                            say('The caterer needs to verify that address.')])
        turn = convo.send('...')
        self.assertEqual(turn.quote['result']['status'], 'needs_server_context')

    def test_pickup_uses_business_tax_location(self):
        args = {k: v for k, v in FULL_ARGS.items() if k != 'address'}
        args['service_mode'] = 'pickup'
        convo = self.convo([call('evaluate_catering_quote', args), reply_with_total])
        turn = convo.send('...')
        self.assertEqual(turn.quote['tax_location'], 'Torrance')

    def test_invented_price_is_corrected(self):
        convo = self.convo([call('evaluate_catering_quote', FULL_ARGS),
                            say('That comes to about $812.50.'),   # invented
                            reply_with_total])                      # corrected
        turn = convo.send('...')
        self.assertTrue(any(w.startswith('unverified_amounts') for w in turn.warnings))
        self.assertNotIn('812.50', turn.reply)
        assistant_text = [m['content'] for m in convo.messages if m['role'] == 'assistant']
        self.assertFalse(any('812.50' in t for t in assistant_text))  # rejected reply not kept

    def test_repeated_invented_price_falls_back_to_code_summary(self):
        # Repeating the same invented amount after the correction must still be caught.
        convo = self.convo([call('evaluate_catering_quote', FULL_ARGS),
                            say('About $812.50.'), say('Sorry, it is $812.50.')])
        turn = convo.send('...')
        total = turn.quote['result']['pricing']['total_cents']
        self.assertIn(f'${total // 100}.{total % 100:02d}', turn.reply)
        self.assertIn('calculated by our pricing system', turn.reply)

    def test_model_sees_ready_made_dollar_strings(self):
        convo = self.convo([call('evaluate_catering_quote', FULL_ARGS), say('Total is $749.04.')])
        turn = convo.send('...')
        sent = json.loads([m for m in convo.messages if m['role'] == 'tool'][-1]['content'])
        self.assertEqual(sent['pricing']['total_display'], '$749.04')
        self.assertEqual(sent['pricing']['lines'][0]['line_total_display'], '$539.60')
        self.assertNotIn('total_display', turn.quote['result']['pricing'])  # code keeps cents only
        self.assertEqual(turn.warnings, [])

    def test_cents_read_as_dollars_is_caught(self):
        convo = self.convo([call('evaluate_catering_quote', FULL_ARGS),
                            say('The pasta is $53,960 and the total is $74,904.'), reply_with_total])
        turn = convo.send('...')
        self.assertTrue(any(w.startswith('unverified_amounts') for w in turn.warnings))
        self.assertNotIn('53,960', turn.reply)

    def test_running_out_of_calls_after_pricing_shows_code_written_quote(self):
        script = [call('evaluate_catering_quote', FULL_ARGS)] + [call('search_menu', {}, f's{i}') for i in range(20)]
        turn = self.convo(script).send('...')
        self.assertIn('too_many_model_calls', turn.warnings)
        self.assertTrue(turn.ready_to_submit)
        self.assertIn('Total: $749.04', turn.reply)
        self.assertIn('The Pasta Duo (Per person) x40: $539.60', turn.reply)

    def test_over_budget_draft_gets_one_retry(self):
        over = dict(FULL_ARGS, budget_usd='700.00')   # $749.04 > $700
        cheaper = dict(over, selections=[FULL_ARGS['selections'][0]])
        convo = self.convo([call('evaluate_catering_quote', over), say('Here it is.'),
                            call('evaluate_catering_quote', cheaper, 'c2'), reply_with_total])
        turn = convo.send('...')
        self.assertIn('over_budget_retry:4904', turn.warnings)
        self.assertTrue(turn.quote['result']['budget']['within_budget'])
        notes = [m for m in convo.messages if m.get('server_note')]
        self.assertEqual(len(notes), 1)
        self.assertNotIn('Here it is.', [m['content'] for m in convo.messages if m['role'] == 'assistant'])

    def test_over_budget_nudge_only_once(self):
        over = dict(FULL_ARGS, budget_usd='700.00')
        convo = self.convo([call('evaluate_catering_quote', over), say('Here it is.'),
                            call('evaluate_catering_quote', over, 'c2'),
                            say('No cheaper menu fits; this is $49.04 over budget.')])
        turn = convo.send('...')
        self.assertEqual(turn.reply, 'No cheaper menu fits; this is $49.04 over budget.')
        self.assertTrue(turn.ready_to_submit)

    def test_no_budget_retry_when_blocked(self):
        blocked = dict(FULL_ARGS, budget_usd='700.00', event_at='2026-10-19T12:00:00-07:00')  # <48 h
        convo = self.convo([call('evaluate_catering_quote', blocked),
                            say('Delivery needs 48 hours notice; want pickup instead?')])
        turn = convo.send('...')
        self.assertEqual(turn.quote['result']['status'], 'blocked')
        self.assertFalse(any(w.startswith('over_budget_retry') for w in turn.warnings))
        self.assertFalse(turn.ready_to_submit)

    def test_customer_amount_and_menu_unit_price_allowed(self):
        convo = self.convo([call('search_menu', {'item_ids': ['app-hummus']}),
                            say('Hummus small is $25.00; that fits your $500 budget nicely.')])
        turn = convo.send('Budget is $500. What appetizers do you have?')
        self.assertEqual(turn.warnings, [])

    def test_unknown_tool_and_malformed_arguments(self):
        convo = self.convo([call('delete_database', {}), call('evaluate_catering_quote', None, 'c2'),
                            say('Sorry, could you repeat that?')])
        turn = convo.send('...')
        self.assertEqual(turn.tool_calls[0]['result']['error'], 'unknown_tool')
        self.assertEqual(turn.tool_calls[1]['result']['status'], 'invalid_input')

    def test_model_failure_returns_friendly_message(self):
        def boom(*_):
            raise ConnectionError('network down')
        turn = self.convo([boom]).send('hello')
        self.assertIn('model_error:ConnectionError', turn.warnings)
        self.assertIn('Sorry', turn.reply)

    def test_tool_loop_is_bounded(self):
        convo = self.convo([call('search_menu', {}, f'c{i}') for i in range(20)])
        turn = convo.send('...')
        self.assertIn('too_many_model_calls', turn.warnings)

    def test_history_is_json_serializable(self):
        convo = self.convo([call('evaluate_catering_quote', FULL_ARGS), reply_with_total])
        convo.send('...')
        restored = Conversation(ScriptedLLM([]), self.ctx, json.loads(json.dumps(convo.messages)))
        self.assertEqual(len(restored.messages), len(convo.messages))


class PriceGuardTests(unittest.TestCase):
    def test_parses_amounts(self):
        self.assertEqual(amounts_in_text('$1,234.5 and $7 and $0.99'), {123450, 700, 99})

    def test_flags_unknown_amounts(self):
        msgs = [{'role': 'tool', 'content': json.dumps({'total_cents': 74904})}]
        self.assertEqual(unverified_amounts('Total $749.04, about $750', '', msgs), [75000])


class ProviderTranslationTests(unittest.TestCase):
    HISTORY = [
        {'role': 'user', 'content': 'hi'},
        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 't1', 'name': 'search_menu', 'arguments': {}}]},
        {'role': 'tool', 'tool_call_id': 't1', 'name': 'search_menu', 'content': '{"count": 0}'},
        {'role': 'user', 'content': '[Automated server check] ...'},
        {'role': 'assistant', 'content': 'ok', 'tool_calls': []},
    ]

    def test_anthropic_roles_alternate(self):
        msgs = to_anthropic_messages(self.HISTORY)
        roles = [m['role'] for m in msgs]
        self.assertEqual(roles, ['user', 'assistant', 'user', 'assistant'])
        self.assertEqual(msgs[2]['content'][0]['type'], 'tool_result')

    def test_anthropic_response(self):
        resp = SimpleNamespace(content=[SimpleNamespace(type='text', text='hi'),
                                        SimpleNamespace(type='tool_use', id='x', name='search_menu', input={})])
        out = from_anthropic_response(resp)
        self.assertEqual((out.content, out.tool_calls[0].name), ('hi', 'search_menu'))

    def test_openai_messages_and_bad_json(self):
        msgs = to_openai_messages('sys', self.HISTORY)
        self.assertEqual(msgs[0], {'role': 'system', 'content': 'sys'})
        self.assertEqual(msgs[2]['tool_calls'][0]['function']['arguments'], '{}')
        call_obj = SimpleNamespace(id='x', function=SimpleNamespace(name='search_menu', arguments='{bad'))
        resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call_obj]))])
        self.assertIsNone(from_openai_response(resp).tool_calls[0].arguments)


if __name__ == '__main__':
    unittest.main()
