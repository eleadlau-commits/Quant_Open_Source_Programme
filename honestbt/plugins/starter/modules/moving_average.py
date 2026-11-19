def moving_average(F, symbol, n):
    """Data -> Data: average of the last n completed daily closes."""
    c = F.daily(symbol).close
    return float(c[-n:].mean()) if len(c) >= n else None
