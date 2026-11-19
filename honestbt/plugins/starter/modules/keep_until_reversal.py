def keep_until_reversal(p, scores):
    """Data -> Buy/Sell: keep each current position while its score stays positive (uses p)."""
    return {s: w for s, w in p.items() if (scores.get(s) or 0) > 0}
