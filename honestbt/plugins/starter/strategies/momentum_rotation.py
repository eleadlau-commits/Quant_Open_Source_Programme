"""Weekly momentum rotation, keep winners until they turn"""
from honestbt.sdk import knob

SETTINGS = {
    'data': {'plugin': 'synthetic', 'params': {'n_symbols': 40, 'n_days': 130, 'seed': 7, 'gap_momentum': 0.0}},
    'decide_at': '09:45',
    'every': 'week',
    'costs': {'half_spread_bps': 5, 'slippage_bps': 3, 'open_multiplier': 3},
    'evaluators': [
        {'plugin': 'out_of_sample', 'params': {'split': 0.6}},
        {'plugin': 'bootstrap'},
        {'plugin': 'cost_stress', 'params': {'multiplier': 2}},
        {'plugin': 'benchmark'},
    ],
}


def momentum(F, symbol, days):
    """Data -> Data: return over the last `days` completed days."""
    c = F.daily(symbol).close
    return c[-1] / c[-days - 1] - 1 if len(c) > days else None


def dollar_volume(F, symbol, n):
    """Data -> Data: average daily dollar volume over the last n completed days."""
    d = F.daily(symbol)
    return float(d.dollar_volume[-n:].mean()) if len(d) >= n else None


def decide(F, p):
    """Data -> Buy/Sell: keep winners that still rise, fill the rest with the strongest names."""
    days = knob("days", 10, lo=2, hi=60)
    top = knob("top", 5, lo=1, hi=15)
    min_price = knob("min_price", 5.0, lo=1.0, hi=20.0)
    scores = {}
    for s in F.universe():
        c = F.daily(s).close
        if len(c) == 0 or c[-1] < min_price or (dollar_volume(F, s, 20) or 0) < 5e6:
            continue
        m = momentum(F, s, days)
        if m is not None:
            scores[s] = m
    keep = [s for s in p if (scores.get(s) or 0) > 0]           # uses p: hold winners until they turn
    fresh = sorted((s for s in scores if s not in keep and scores[s] > 0), key=scores.get, reverse=True)
    names = (keep + fresh)[:top]
    return {s: 1 / len(names) for s in names} if names else {}
