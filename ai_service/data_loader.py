"""Load a dataset folder into a ServerContext. The real app (D) will load from Supabase instead."""
import json
from datetime import datetime
from pathlib import Path

from .context import ServerContext

ROOT = Path(__file__).resolve().parents[1]
# demo = frozen menu for the presentation/eval (data/demo/build_demo.py); sample = small dev fixture.
DATASETS = {'demo': ROOT / 'data' / 'demo', 'sample': ROOT / 'data' / 'sample', 'full': ROOT / 'data'}


def load_context(dataset='sample', now=None):
    """now: optional ISO datetime with offset to freeze the clock (tests, eval, demo)."""
    folder = DATASETS[dataset]
    menu, rules, capacity = [json.loads((folder / name).read_text())
                             for name in ('menu.json', 'rules.json', 'capacity.json')]
    kwargs = {}
    if now:
        frozen = datetime.fromisoformat(now)
        kwargs['clock'] = lambda: frozen
    return ServerContext(menu=menu, rules=rules, capacity=capacity, **kwargs)
