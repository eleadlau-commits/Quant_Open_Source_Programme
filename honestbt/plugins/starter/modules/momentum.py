def momentum(F, symbol, days):
    """Data -> Data: return over the last `days` completed days."""
    c = F.daily(symbol).close
    return c[-1] / c[-days - 1] - 1 if len(c) > days else None
