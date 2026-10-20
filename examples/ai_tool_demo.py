"""Offline tool examples. Run: python3 -m examples.ai_tool_demo"""
import copy
import json
from pathlib import Path
from datetime import datetime
from quote_engine.ai_tool import evaluate_catering_quote


def main():
    folder=Path(__file__).resolve().parents[1]/'data/sample'
    menu,rules,capacity,inquiries=[json.loads((folder/name).read_text()) for name in
                                  ('menu.json','rules.json','capacity.json','inquiries.json')]
    example=inquiries['pricing_example']
    request=dict(headcount=40,event_at='2026-10-23T12:00:00-07:00',service_mode='delivery',
                 address='Demo office',allergens=[],selections=example['selections'],budget_usd='800.00')
    context=dict(menu=menu,rules=rules,capacity=capacity,
                 now=datetime.fromisoformat('2026-10-18T12:00:00-07:00'),
                 tax_location='Culver City',delivery_miles=15)
    cases={'within_budget':request,'over_budget':dict(request,budget_usd='700.00'),
           'missing_details':{'headcount':40},'ambiguous_allergy':dict(request,allergens=['nuts'])}
    for name,args in cases.items():
        print(json.dumps({'scenario':name,'result':evaluate_catering_quote(copy.deepcopy(args),**context)},indent=2))


if __name__=='__main__':
    main()
