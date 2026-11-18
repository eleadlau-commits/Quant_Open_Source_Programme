from honestbt.plugins.testing import fake_context, plugin

f = plugin("evaluator", "parameter_stability")


def test_lonely_winner_fails_and_broad_plateau_passes():
    assert f(fake_context([[0.01] * 10] + [[-0.01] * 10] * 4)).passed is False
    assert f(fake_context([[0.01] * 10] * 4 + [[-0.01] * 10])).passed is True


def test_needs_a_sweep():
    assert f(fake_context([[0.01] * 10])).passed is None
