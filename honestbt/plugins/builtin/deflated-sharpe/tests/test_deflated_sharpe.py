from honestbt.plugins.testing import fake_context, noise, plugin

f = plugin("evaluator", "deflated_sharpe")


def test_best_of_many_noise_variants_fails():
    v = f(fake_context([noise(mean=0.0, seed=s) for s in range(30)]))
    assert v.passed is False and v.details["trials"] == 30


def test_strong_single_edge_passes():
    assert f(fake_context([noise(mean=0.02, sd=0.01)])).passed is True
