def top_n_equal_weight(scores, n):
    """Data -> Buy/Sell: hold the n highest scores ({symbol: score}), equal weight."""
    best = sorted((s for s in scores if scores[s] is not None), key=scores.get, reverse=True)[:n]
    return {s: 1 / len(best) for s in best} if best else {}
