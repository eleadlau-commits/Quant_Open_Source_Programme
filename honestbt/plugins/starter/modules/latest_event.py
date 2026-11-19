def latest_event(F, symbol, name="earnings_surprise"):
    """Data -> Data: the latest complementary value for symbol known at decision time (or None)."""
    if name not in F.series_names():
        return None
    return F.series_last(name, symbol)
