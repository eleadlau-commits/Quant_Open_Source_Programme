from honestbt.plugins.testing import fake_context, fake_result, noise, plugin

f = plugin("evaluator", "ablation")
CFG = {"strategy": {"plugin": "fake", "params": {"trend_filter": True}}}


def test_missing_ingredient_cannot_be_judged():
    assert f(fake_context([[0.01] * 10])).passed is None


def test_ingredient_that_clearly_helps_passes():
    ctx = fake_context([noise(mean=0.02, sd=0.01)], config=CFG, run=lambda cfg: fake_result(noise(mean=0.0, seed=9)))
    assert f(ctx).passed is True
