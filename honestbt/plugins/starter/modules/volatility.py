def volatility(F, symbol, n):
    """Data -> Data: annualised volatility of daily returns over the last n days."""
    import numpy as np
    c = F.daily(symbol).close
    if len(c) <= n:
        return None
    r = np.diff(np.log(c[-n - 1:]))
    return float(r.std(ddof=1) * np.sqrt(252))
