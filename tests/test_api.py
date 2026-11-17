from fastapi.testclient import TestClient

from honestbt.api import app

client = TestClient(app)


def test_plugins_and_configs():
    cat = client.get("/api/plugins").json()
    assert {"data", "feature", "mapping", "signal", "strategy", "evaluator"} <= set(cat)
    assert "monday_gap_top5" in client.get("/api/configs").json()


def test_run_small():
    cfg = client.get("/api/configs/monday_gap_top5").json()
    cfg["data"]["params"].update(n_symbols=15, n_days=50)
    cfg["sweep"] = {"strategy.params.exit.params.k": [0.5, 1.0, 2.0]}
    cfg["evaluators"] = [{"plugin": "bootstrap"}, {"plugin": "parameter_stability"}]
    r = client.post("/api/run", json=cfg)
    assert r.status_code == 200, r.text
    assert len(r.json()["sweep"]) == 3


def test_bad_config_is_400():
    r = client.post("/api/run", json={"strategy": {"plugin": "nope"}, "data": {"plugin": "synthetic"}})
    assert r.status_code == 400
