"""Testing the testers: no-edge data should fail, planted-edge data should pass."""
from honestbt.patchbay import with_overrides
from honestbt.runner import run_config


def _run(cfg, gm):
    cfg = with_overrides(cfg, {"data.params.gap_momentum": gm})
    cfg["evaluators"] = [e for e in cfg["evaluators"] if e["plugin"] != "random_baseline"] + [
        {"plugin": "random_baseline", "params": {"n": 39}}]
    return run_config(cfg)


def test_no_edge_does_not_survive(base_config):
    out = _run(base_config, 0.0)
    assert out["summary"]["overall"] == "did not survive"
    v = {x["name"]: x["passed"] for x in out["verdicts"]}
    assert v["Deflated Sharpe"] is False and v["Parameter stability"] is False


def test_planted_edge_survives(base_config):
    out = _run(base_config, 1.0)
    assert out["summary"]["overall"] == "survived all tests", out["verdicts"]
