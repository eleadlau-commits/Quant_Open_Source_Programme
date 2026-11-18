from honestbt.plugins.testing import fake_context, noise, plugin

f = plugin("evaluator", "bootstrap")


def test_clear_edge_passes_and_zero_mean_fails():
    assert f(fake_context([noise(mean=0.02, sd=0.01)]), n=500).passed is True
    assert f(fake_context([noise(mean=0.0, sd=0.02)]), n=500).passed is False
