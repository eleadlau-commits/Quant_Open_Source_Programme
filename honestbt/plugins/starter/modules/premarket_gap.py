def premarket_gap(F, symbol):
    """Data -> Data: last pre-market price today vs yesterday's close (decide at or before 09:30)."""
    c = F.daily(symbol).close
    pm = F.premarket_last(symbol)
    return pm / c[-1] - 1 if len(c) and pm == pm else None
