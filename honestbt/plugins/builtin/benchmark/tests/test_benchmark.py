from honestbt.plugins.testing import fake_context, fake_result, noise, plugin

f = plugin("evaluator", "benchmark")
CFG = {"strategy": {"plugin": "fake", "params": {"top_n": 5, "exit": {"plugin": "atr_trailing"}}}}


def test_compares_with_holding_everything_without_exits():
    seen = {}

    def run(cfg):
        seen.update(cfg["strategy"]["params"])
        return fake_result(noise(mean=0.0, seed=4))

    v = f(fake_context([noise(mean=0.02, sd=0.01)], config=CFG, run=run))
    assert v.passed is True
    assert seen["exit"] == {"plugin": "never"} and seen["top_n"] >= 10**9
