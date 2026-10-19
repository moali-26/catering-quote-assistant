"""Run the repository's sample pricing example: python -m quote_engine."""
import json
from pathlib import Path
from .pricing import calculate_quote

root = Path(__file__).resolve().parents[1] / 'data' / 'sample'
menu = json.loads((root / 'menu.json').read_text())
rules = json.loads((root / 'rules.json').read_text())
examples = json.loads((root / 'inquiries.json').read_text())
request = dict(examples['pricing_example'])
request['headcount'] = next(c['expected']['headcount'] for c in examples['inquiries']
                            if c['id'] == request['inquiry_id'])
print(json.dumps(calculate_quote(menu, rules, request), indent=2))
