from honestbt.plugins.testing import fake_context, fake_result, plugin

f = plugin("evaluator", "random_baseline")
CFG = {"strategy": {"plugin": "fake", "params": {"rank_by": "gap"}}}


def test_without_a_ranking_it_cannot_judge():
    assert f(fake_context([[0.01] * 10])).passed is None


def test_beating_every_random_pick_passes():
    ctx = fake_context([[0.01] * 10], config=CFG, run=lambda cfg: fake_result([0.0] * 10))
    v = f(ctx, n=30)
    assert v.passed is True and v.details["p_value"] < 0.05
