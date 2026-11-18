from honestbt.plugins.testing import fake_context, fake_result, plugin

f = plugin("evaluator", "cost_stress")


def test_passes_only_if_still_profitable_when_costs_rise():
    seen = {}

    def run(cfg):
        seen.update(cfg)
        return fake_result([0.001] * 20 if cfg["costs"]["multiplier"] == 2 else [-0.001] * 20)

    assert f(fake_context([[0.01] * 20], run=run), multiplier=2).passed is True
    assert seen["costs"]["multiplier"] == 2
    assert f(fake_context([[0.01] * 20], run=run), multiplier=3).passed is False
