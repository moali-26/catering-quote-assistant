"""Evaluation harness: the answer key is checked against the real engine, scoring is checked
on synthetic runs, and the runner is exercised end to end with a scripted model (no API)."""
import json
import unittest
from pathlib import Path

from ai_service import LLMResponse, ScriptedLLM, ToolCall
from ai_service.data_loader import load_context
from ai_service.prompts import build_system_prompt
from evaluation.run_eval import evaluate, load_cases, markdown_report, run_case
from evaluation.scoring import GROUPS, local_event, score_case, summarize
from quote_engine.ai_tool import evaluate_catering_quote

ROOT = Path(__file__).resolve().parents[1]
KNOWN_EXPECT = {'ready', 'status', 'blocking_includes', 'fields', 'absent_fields', 'ambiguous_nuts',
                'never_selected_with_allergen', 'reply_any', 'reply_none', 'no_amounts', 'no_evaluate',
                'total_unchanged', 'fake_total_cents', 'within_budget', 'honest_budget', 'selection_has_tag'}
KNOWN_FIELDS = {'headcount', 'date', 'time', 'service_mode', 'allergens_exact', 'allergens_include', 'tax_location'}


class AnswerKeyTests(unittest.TestCase):
    """The expected answers must be true for the real menu, rules, calendar and engine."""

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.cases = load_cases()
        cls.ctx = load_context(cls.meta['dataset'], cls.meta['now'])

    def oracle(self, case):
        request = case['oracle']
        tax, miles = self.ctx.location_for(request)
        return evaluate_catering_quote(request, menu=self.ctx.menu, rules=self.ctx.rules,
                                       capacity=self.ctx.capacity, now=self.ctx.now(),
                                       tax_location=tax, delivery_miles=miles)

    def test_cases_are_well_formed(self):
        ids = [c['id'] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(self.cases), 20)
        for case in self.cases:
            with self.subTest(case=case['id']):
                self.assertTrue(case['turns'] and all(isinstance(t, str) and t for t in case['turns']))
                self.assertLessEqual(set(case['expect']), KNOWN_EXPECT)
                self.assertLessEqual(set(case['expect'].get('fields', {})), KNOWN_FIELDS)

    def test_held_out_from_development_inquiries(self):
        from scripts.live_chat_check import SCENARIOS
        dev = {t.strip().lower() for s in SCENARIOS.values() for t in s['turns']}
        sample = json.loads((ROOT / 'data/sample/inquiries.json').read_text())
        dev |= {i['text'].strip().lower() for i in sample['inquiries']}
        for case in self.cases:
            for text in case['turns']:
                self.assertNotIn(text.strip().lower(), dev, case['id'])

    def test_oracle_requests_confirm_the_expected_outcome(self):
        for case in [c for c in self.cases if 'oracle' in c]:
            with self.subTest(case=case['id']):
                result = self.oracle(case)
                if 'oracle_blocking' in case:
                    self.assertEqual(result['status'], 'blocked', result)
                    self.assertLessEqual(set(case['oracle_blocking']), set(result['blocking_reasons']))
                    if 'blocking_includes' in case['expect']:
                        self.assertLessEqual(set(case['expect']['blocking_includes']), set(result['blocking_reasons']))
                elif 'oracle_status' in case:
                    self.assertEqual(result['status'], case['oracle_status'])
                else:  # a correct assistant can reach a submittable, in-budget quote
                    self.assertEqual(result['status'], 'needs_owner_review', result)
                    if 'budget_usd' in case['oracle']:
                        self.assertTrue(result['budget']['within_budget'], result['budget'])

    def test_oracle_matches_expected_fields(self):
        """The answer key's fields describe the oracle request (catches typos in dates and times)."""
        for case in [c for c in self.cases if 'oracle' in c and c['expect'].get('fields')]:
            with self.subTest(case=case['id']):
                tax, miles = self.ctx.location_for(case['oracle'])
                run = {'replies': ['ok'], 'warnings': [], 'ready': True,
                       'calls': [{'name': 'evaluate_catering_quote', 'arguments': case['oracle'], 'turn': 0}],
                       'latest_quote': {'result': self.oracle(case), 'tax_location': tax}, 'quote_after_turn': []}
                checks = score_case({'expect': {'fields': case['expect']['fields']}}, run, self.ctx.menu)
                self.assertTrue(all(checks.values()), checks)

    def test_impossible_budget_really_is_impossible(self):
        case = next(c for c in self.cases if 'impossible_budget_cents' in c)
        rules = self.ctx.rules
        minimum = rules['service_modes']['delivery']['order_minimum']['subtotal']
        fee = rules['delivery']['fee']['flat_fee']
        rate = rules['tax']['rates']['Culver City']
        cheapest_total_cents = round((minimum + fee) * (1 + rate) * 100)
        self.assertGreater(cheapest_total_cents, case['impossible_budget_cents'])

    def test_calendar_dates_in_cases(self):
        """Weekday names written in the cases match the real calendar (Oct 29 2026 is a Thursday...)."""
        from datetime import date
        import re
        months = {'oct': 10, 'october': 10, 'nov': 11, 'november': 11}
        pattern = re.compile(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) (Oct|October|Nov|November) (\d{1,2})')
        for case in self.cases:
            for text in case['turns']:
                for weekday, month, day in pattern.findall(text):
                    actual = date(2026, months[month.lower()], int(day)).strftime('%A')
                    self.assertEqual(actual, weekday, f"{case['id']}: {weekday} {month} {day}")


class PromptCalendarTests(unittest.TestCase):
    def test_calendar_gives_each_day_its_own_utc_offset(self):
        prompt = build_system_prompt(load_context('demo', '2026-10-20T10:00:00-07:00'))
        self.assertIn('Thursday 2026-10-29, UTC-07:00', prompt)
        self.assertIn('Wednesday 2026-11-04, UTC-08:00', prompt)   # after daylight saving time ends
        self.assertIn('Saturday 2026-11-14, UTC-08:00', prompt)


def run_from(calls, replies, ready=False, quote=None, warnings=(), quotes_after=None):
    return {'calls': [{'name': n, 'arguments': a, 'turn': 0} for n, a in calls], 'replies': replies,
            'ready': ready, 'latest_quote': quote, 'warnings': list(warnings),
            'quote_after_turn': quotes_after or [quote]}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.menu = load_context('demo', '2026-10-20T10:00:00-07:00').menu

    def test_local_event_handles_dst(self):
        self.assertEqual(local_event('2026-11-04T12:00:00-08:00'), ('2026-11-04', '12:00'))
        self.assertEqual(local_event('2026-11-04T12:00:00-07:00'), ('2026-11-04', '11:00'))  # wrong offset = wrong time
        self.assertIsNone(local_event('2026-11-04T12:00:00'))
        self.assertIsNone(local_event(None))

    def test_guessed_field_fails_even_if_reply_asks(self):
        case = {'expect': {'ready': False, 'absent_fields': ['headcount'], 'reply_any': [['how many']]}}
        run = run_from([('evaluate_catering_quote', {'headcount': 20})], ['How many guests?'])
        checks = score_case(case, run, self.menu)
        self.assertFalse(checks['no_guessed_fields'])
        self.assertTrue(checks['reply_mentions'])

    def test_allergen_item_selected_fails(self):
        case = {'expect': {'never_selected_with_allergen': 'peanut'}}
        args = {'selections': [{'item_id': 'dessert-cookie-platter', 'variant_id': 'x', 'quantity': 1}]}
        self.assertFalse(score_case(case, run_from([('evaluate_catering_quote', args)], ['ok']), self.menu)['avoids_allergen_items'])

    def test_ambiguous_nuts_rules(self):
        case = {'expect': {'ambiguous_nuts': True}}
        only_peanut = run_from([('evaluate_catering_quote', {'allergens': ['peanut']})], ['Here you go'], ready=True)
        both = run_from([('evaluate_catering_quote', {'allergens': ['peanut', 'tree_nuts']})], ['ok'], ready=True)
        asked = run_from([], ['Is that peanuts or tree nuts?'])
        self.assertFalse(score_case(case, only_peanut, self.menu)['asks_or_both_nuts'])
        self.assertTrue(score_case(case, both, self.menu)['asks_or_both_nuts'])
        self.assertTrue(score_case(case, asked, self.menu)['asks_or_both_nuts'])

    def test_injection_checks(self):
        case = {'expect': {'total_unchanged': True, 'fake_total_cents': 25000, 'reply_none': ['discount applied']}}
        q = lambda total: {'result': {'status': 'needs_owner_review', 'pricing': {'total_cents': total}}}
        good = run_from([], ['ok', "I can't change prices; your total stays $577.89."], quotes_after=[q(57789), q(57789)])
        bad = run_from([], ['ok', 'Discount applied! New total $250.00.'], quotes_after=[q(57789), q(25000)])
        g, b = score_case(case, good, self.menu), score_case(case, bad, self.menu)
        self.assertTrue(all(g.values()), g)
        self.assertFalse(b['total_unchanged'] or b['no_fake_total'] or b['reply_avoids'])

    def test_model_failure_counts_against_reliability(self):
        run = run_from([], ['Sorry'], warnings=['model_error:TurnBudgetExceeded'])
        self.assertFalse(score_case({'expect': {}}, run, self.menu)['no_failures'])

    def test_every_check_has_a_group(self):
        meta, cases = load_cases()
        menu = self.menu
        names = set()
        for case in cases:
            names |= set(score_case(case, run_from([], ['x']), menu))
        self.assertLessEqual(names, set(GROUPS))


class RunnerTests(unittest.TestCase):
    """End to end with a scripted model: the runner, web limits, scoring and report all work offline."""

    def test_scripted_run_scores_and_reports(self):
        meta, cases = load_cases()
        chosen = {c['id']: c for c in cases if c['id'] in ('E02', 'E22')}
        e02 = chosen['E02']
        args = dict(e02['oracle'])
        scripts = {
            'E02': [LLMResponse(tool_calls=[ToolCall('s', 'search_menu', {})]),
                    LLMResponse(tool_calls=[ToolCall('q', 'evaluate_catering_quote', args)]),
                    lambda system, messages, tools: LLMResponse(content='Draft ready for Wednesday, October 28 at 5:30 PM.')],
            'E22': [LLMResponse(content='I can only help with catering quotes. Planning an event?')],
        }
        order = iter(['E02', 'E22'])
        factory = lambda: ScriptedLLM(scripts[next(order)])
        ctx = load_context(meta['dataset'], meta['now'])
        results, summary = evaluate([chosen['E02'], chosen['E22']], factory, ctx, web_limits=True, log=lambda *_: None)
        self.assertTrue(all(r['pass'] for r in results), [(r['case']['id'], r['failed_checks']) for r in results])
        self.assertEqual(summary['cases'], {'passed': 2, 'total': 2, 'rate': 1.0})
        self.assertEqual(results[0]['calls_used'], 3)
        report = markdown_report(meta, results, summary, provider='scripted', model='none', web_limits=True)
        self.assertIn('| E02 | complete |', report)
        self.assertIn('Cases fully passed | 2/2 (100%)', report)

    def test_bad_api_key_stops_before_writing_a_report(self):
        from evaluation.run_eval import SetupError

        class Rejecting:
            def generate(self, *a):
                raise type('AuthenticationError', (Exception,), {})('bad key')
        meta, cases = load_cases()
        with self.assertRaises(SetupError):
            evaluate(cases[:2], Rejecting, load_context(meta['dataset'], meta['now']), log=lambda *_: None)

    def test_web_limits_cap_model_calls_per_turn(self):
        meta, cases = load_cases()
        case = {'id': 'X', 'turns': ['hi'], 'expect': {}}
        endless = ScriptedLLM([LLMResponse(tool_calls=[ToolCall(f'c{i}', 'search_menu', {})]) for i in range(20)])
        run = run_case(case, endless, load_context(meta['dataset'], meta['now']), web_limits=True)
        self.assertEqual(run['calls_used'], 5)                         # app.chat.MODEL_CALLS_PER_TURN
        self.assertTrue(any(w.startswith('model_error') for w in run['warnings']))


if __name__ == '__main__':
    unittest.main()
