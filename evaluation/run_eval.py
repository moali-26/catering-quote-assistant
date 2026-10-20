"""Run the held-out evaluation set through the real conversation loop and score it.

    python3 -m evaluation.run_eval --provider openai               # OPENAI_API_KEY + OPENAI_MODEL
    python3 -m evaluation.run_eval --provider openai --only E01,E12
    python3 -m evaluation.run_eval --provider anthropic --repeat 2

Uses the same pieces as the web app: ai_service.Conversation on the demo menu with a
frozen clock, and (by default) the web app's per-turn limits (app.chat.GuardedLLM:
5 model calls / 75 s per customer message), so the scores reflect what customers get.
Writes evaluation/results/<timestamp>-<provider>-<model>.json and .md. Costs API credit.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_service import Conversation  # noqa: E402
from ai_service.data_loader import load_context  # noqa: E402
from evaluation.scoring import score_case, summarize  # noqa: E402

CASES = Path(__file__).resolve().parent / 'cases.json'
# Setup problems that make every case fail: stop instead of writing a misleading 0% report.
FATAL_ERRORS = ('AuthenticationError', 'PermissionDeniedError', 'NotFoundError', 'BadRequestError',
                'APIConnectionError')


class SetupError(RuntimeError):
    pass
RESULTS = Path(__file__).resolve().parent / 'results'


class CountingLLM:
    """Counts model calls; wraps any LLMClient."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def generate(self, system, messages, tools):
        self.calls += 1
        return self.inner.generate(system, messages, tools)


def load_cases(path=CASES):
    data = json.loads(Path(path).read_text())
    return data['meta'], data['cases']


def run_case(case, llm, context, *, web_limits=True):
    """Play the case's customer turns; return the recorded run (see scoring.py)."""
    counter = CountingLLM(llm)
    convo = Conversation(counter, context)
    guard = None
    if web_limits:
        from app.chat import GuardedLLM  # the web app's per-turn caps
        guard = GuardedLLM
    run = {'replies': [], 'calls': [], 'warnings': [], 'quote_after_turn': []}
    started = time.monotonic()
    turn = None
    for index, text in enumerate(case['turns']):
        convo.llm = guard(counter) if guard else counter  # fresh limits for each customer message
        turn = convo.send(text)
        run['replies'].append(turn.reply)
        run['warnings'] += turn.warnings
        run['calls'] += [dict(call, turn=index) for call in turn.tool_calls]
        run['quote_after_turn'].append(convo.latest_quote)
    run['ready'] = bool(turn and turn.ready_to_submit)
    run['latest_quote'] = convo.latest_quote
    run['calls_used'] = counter.calls
    run['seconds'] = round(time.monotonic() - started, 1)
    return run


def _total(run):
    quote = run.get('latest_quote')
    pricing = quote and quote['result'].get('pricing')
    return f"${pricing['total_cents'] / 100:,.2f}" if pricing else None


def evaluate(cases, llm_factory, context, *, web_limits=True, repeat=1, log=print):
    results = []
    for case in cases:
        for attempt in range(repeat):
            run = run_case(case, llm_factory(), context, web_limits=web_limits)
            fatal = [w for w in run['warnings'] if w.startswith('model_error:') and w.split(':', 1)[1] in FATAL_ERRORS]
            if fatal and not results:  # the very first case could not reach the model at all
                raise SetupError(fatal[0].split(':', 1)[1])
            checks = score_case(case, run, context.menu)
            ok = all(checks.values())
            failed = [name for name, passed in checks.items() if not passed]
            status = run['latest_quote']['result']['status'] if run['latest_quote'] else None
            results.append({'case': case, 'attempt': attempt + 1, 'pass': ok, 'checks': checks,
                            'failed_checks': failed, 'ready': run['ready'], 'status': status,
                            'total': _total(run), 'calls_used': run['calls_used'], 'seconds': run['seconds'],
                            'warnings': run['warnings'], 'replies': run['replies'],
                            'last_arguments': next((c['arguments'] for c in reversed(run['calls'])
                                                    if c['name'] == 'evaluate_catering_quote'), None)})
            log(f"{'PASS' if ok else 'FAIL'}  {case['id']} {case['category']:14s} ready={run['ready']!s:5s} "
                f"status={status or '-':22s} calls={run['calls_used']} {run['seconds']}s"
                + (f"  failed: {', '.join(failed)}" if failed else ''))
    return results, summarize(results)


def markdown_report(meta, results, summary, *, provider, model, web_limits):
    pct = lambda r: f"{r['passed']}/{r['total']} ({r['rate']:.0%})" if r['total'] else '—'
    lines = [f"# Evaluation results — {provider} `{model}`", '',
             f"Run {datetime.now():%Y-%m-%d %H:%M}. Held-out set: {len(results)} runs of "
             f"{len({r['case']['id'] for r in results})} cases on the `{meta['dataset']}` menu, "
             f"frozen clock {meta['now']}. Web-app limits: {'on' if web_limits else 'off'}.", '',
             '## Summary', '', '| Measure | Result |', '| --- | --- |',
             f"| Cases fully passed | {pct(summary['cases'])} |"]
    lines += [f"| Category: {name} | {pct(r)} |" for name, r in summary['by_category'].items()]
    lines += [f"| Checks: {name} | {pct(r)} |" for name, r in summary['by_check_group'].items()]
    lines += [f"| Avg model calls per case | {summary['avg_model_calls_per_case']} |",
              f"| Avg seconds per case | {summary['avg_seconds_per_case']} |",
              f"| Price-guard rejections (invented amounts caught) | {summary['price_guard_rejections']} |",
              f"| Over-budget retries | {summary['over_budget_retries']} |",
              f"| Model failures / call-limit hits | {summary['model_failures']} |",
              '', '## Cases', '', '| ID | Category | Case | Result | Failed checks | Ready | Status | Total | Calls | Sec |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in results:
        lines.append(f"| {r['case']['id']} | {r['case']['category']} | {r['case']['title']} | "
                     f"{'✅' if r['pass'] else '❌'} | {', '.join(r['failed_checks']) or '—'} | {r['ready']} | "
                     f"{r['status'] or '—'} | {r['total'] or '—'} | {r['calls_used']} | {r['seconds']} |")
    failures = [r for r in results if not r['pass']]
    if failures:
        lines += ['', '## Failed cases: final reply', '']
        for r in failures:
            reply = r['replies'][-1].replace('\n', ' ')[:600]
            lines += [f"**{r['case']['id']} — {r['case']['title']}** (failed: {', '.join(r['failed_checks'])})", '',
                      f"> {reply}", '']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', required=True, choices=['openai', 'anthropic'])
    parser.add_argument('--model', default=None, help='overrides OPENAI_MODEL / ANTHROPIC_MODEL')
    parser.add_argument('--only', help='comma-separated case IDs, e.g. E01,E12')
    parser.add_argument('--repeat', type=int, default=1, help='runs per case (consistency check)')
    parser.add_argument('--no-web-limits', action='store_true', help='skip the web app per-turn caps')
    parser.add_argument('--out-dir', default=str(RESULTS))
    args = parser.parse_args()

    import logging
    # Model failures are recorded in each case's warnings and the report; don't print tracebacks mid-run.
    logging.getLogger('ai_service.conversation').setLevel(logging.CRITICAL)
    from ai_service.providers import make_llm
    meta, cases = load_cases()
    if args.only:
        wanted = {c.strip().upper() for c in args.only.split(',')}
        cases = [c for c in cases if c['id'] in wanted]
    model = args.model or (os.environ.get('OPENAI_MODEL') if args.provider == 'openai'
                           else os.environ.get('ANTHROPIC_MODEL') or 'default')
    context = load_context(meta['dataset'], meta['now'])
    web_limits = not args.no_web_limits
    print(f"Provider {args.provider}, model {model}, {len(cases)} cases x {args.repeat}, web limits {'on' if web_limits else 'off'}\n")
    try:
        results, summary = evaluate(cases, lambda: make_llm(args.provider, model=args.model), context,
                                    web_limits=web_limits, repeat=args.repeat)
    except SetupError as exc:
        hints = {'AuthenticationError': 'the API key was rejected. Check it is set in THIS terminal '
                                        '(echo ${OPENAI_API_KEY:0:7}) and still valid.',
                 'NotFoundError': 'the model name was not found. Check OPENAI_MODEL / ANTHROPIC_MODEL.',
                 'APIConnectionError': 'could not reach the provider (network, VPN or SSL).'}
        print(f"\nStopped before scoring: {exc}: {hints.get(str(exc), 'check the provider settings.')}\n"
              "No report was written.")
        sys.exit(2)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y%m%d-%H%M}-{args.provider}-{str(model).replace('/', '_')}"
    (out / f'{stem}.json').write_text(json.dumps({'meta': meta, 'provider': args.provider, 'model': model,
                                                  'web_limits': web_limits, 'summary': summary,
                                                  'results': results}, indent=2, default=str))
    (out / f'{stem}.md').write_text(markdown_report(meta, results, summary, provider=args.provider,
                                                    model=model, web_limits=web_limits))
    c = summary['cases']
    print(f"\n{c['passed']}/{c['total']} cases passed ({c['rate']:.0%}). Report: {out / (stem + '.md')}")


if __name__ == '__main__':
    main()
