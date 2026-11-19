"""Code modules for strategies written in Python: small functions you can drop into a file.

Data → Data modules take F (all data up to now) and return a number or None.
Data → Buy/Sell modules take F and p (current positions) and return positions.
"""

CODE_MODULES = {
    "moving_average": ("Data → Data", "Average of the last n completed daily closes.", '''
def moving_average(F, symbol, n):
    """Data -> Data: average of the last n completed daily closes."""
    c = F.daily(symbol).close
    return float(c[-n:].mean()) if len(c) >= n else None
'''),
    "momentum": ("Data → Data", "Return over the last n completed days.", '''
def momentum(F, symbol, days):
    """Data -> Data: return over the last `days` completed days."""
    c = F.daily(symbol).close
    return c[-1] / c[-days - 1] - 1 if len(c) > days else None
'''),
    "volatility": ("Data → Data", "Annualised standard deviation of daily returns over n days.", '''
def volatility(F, symbol, n):
    """Data -> Data: annualised volatility of daily returns over the last n days."""
    import numpy as np
    c = F.daily(symbol).close
    if len(c) <= n:
        return None
    r = np.diff(np.log(c[-n - 1:]))
    return float(r.std(ddof=1) * np.sqrt(252))
'''),
    "dollar_volume": ("Data → Data", "Average daily dollar volume over n days (a liquidity filter).", '''
def dollar_volume(F, symbol, n):
    """Data -> Data: average daily dollar volume over the last n completed days."""
    d = F.daily(symbol)
    return float(d.dollar_volume[-n:].mean()) if len(d) >= n else None
'''),
    "premarket_gap": ("Data → Data", "Today's last pre-market price against yesterday's close.", '''
def premarket_gap(F, symbol):
    """Data -> Data: last pre-market price today vs yesterday's close (decide at or before 09:30)."""
    c = F.daily(symbol).close
    pm = F.premarket_last(symbol)
    return pm / c[-1] - 1 if len(c) and pm == pm else None
'''),
    "top_n_equal_weight": ("Data → Buy/Sell", "Hold the n best-scoring names, equal weight.", '''
def top_n_equal_weight(scores, n):
    """Data -> Buy/Sell: hold the n highest scores ({symbol: score}), equal weight."""
    best = sorted((s for s in scores if scores[s] is not None), key=scores.get, reverse=True)[:n]
    return {s: 1 / len(best) for s in best} if best else {}
'''),
    "keep_until_reversal": ("Data → Buy/Sell", "Keep what you hold until its score turns negative (uses p).", '''
def keep_until_reversal(p, scores):
    """Data -> Buy/Sell: keep each current position while its score stays positive (uses p)."""
    return {s: w for s, w in p.items() if (scores.get(s) or 0) > 0}
'''),
}
