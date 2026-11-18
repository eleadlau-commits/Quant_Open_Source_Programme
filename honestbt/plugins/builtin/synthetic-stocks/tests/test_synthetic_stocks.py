from honestbt.plugins.testing import plugin


def test_shape_and_seed():
    make = plugin("data", "synthetic")
    a, b = make(n_symbols=6, n_days=20, seed=4), make(n_symbols=6, n_days=20, seed=4)
    assert len(a.symbols) == 6 and len(a.trading_days) == 20
    s = a.symbols[0]
    assert (a.arr[s] == b.arr[s]).all()
