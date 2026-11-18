from honestbt.plugins.testing import fake_context, noise, plugin

f = plugin("evaluator", "out_of_sample")


def test_steady_edge_passes_and_noise_fails():
    assert f(fake_context([noise(mean=0.01, seed=1), noise(mean=0.01, seed=2)])).passed is True
    assert f(fake_context([noise(mean=0.0, seed=s) * 0 - 0.001 for s in range(3)])).passed is False


def test_too_short_cannot_be_judged():
    assert f(fake_context([[0.01] * 5])).passed is None
