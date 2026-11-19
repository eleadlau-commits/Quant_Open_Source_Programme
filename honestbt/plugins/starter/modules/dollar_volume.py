def dollar_volume(F, symbol, n):
    """Data -> Data: average daily dollar volume over the last n completed days."""
    d = F.daily(symbol)
    return float(d.dollar_volume[-n:].mean()) if len(d) >= n else None
