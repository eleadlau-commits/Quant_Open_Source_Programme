from titanium.app.workspace import Workspace
from titanium.core.strategy import StrategyGraph


def test_collections_announce_changes():
    ws = Workspace()
    seen = []
    ws.strategies.added.connect(lambda i, _o: seen.append(("added", i)))
    ws.strategies.changed.connect(lambda i, _o: seen.append(("changed", i)))
    ws.strategies.removed.connect(lambda i: seen.append(("removed", i)))
    g = StrategyGraph("S1", "one")
    ws.strategies.put("S1", g)
    ws.strategies.put("S1", g)
    ws.strategies.remove("S1")
    ws.strategies.remove("S1")
    assert seen == [("added", "S1"), ("changed", "S1"), ("removed", "S1")]


# ---- the dataset service ---------------------------------------------------------------
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from titanium.app.datasets import DatasetInUse  # noqa: E402
from titanium.core.data import DataKind, LookAheadError  # noqa: E402

SMALL = {"n_symbols": 3, "n_days": 25, "seed": 2}


def test_add_generate_and_reopen_datasets(tmp_path):
    ws = Workspace(data_root=tmp_path)
    seen = []
    ws.datasets.added.connect(lambda i, _o: seen.append(i))
    core = ws.datasets.add("synthetic_stocks", SMALL)
    assert seen == [core.id] and core.kind is DataKind.CORE
    assert core.storage.startswith(str(tmp_path)) and core.size_bytes > 0
    assert len(core.instruments) == 3 and core.start < core.end
    feat = ws.datasets.generate("realised_vol", core.id, {"window": 5})
    assert feat.kind is DataKind.GENERATED and feat.inputs == [core.id]
    assert ws.datasets.counts()[DataKind.GENERATED] == 1

    again = Workspace(data_root=tmp_path)  # the catalogue survives a restart
    assert set(again.datasets.ids()) == {core.id, feat.id}
    key = core.instruments[0]
    day = again.datasets.open(core.id).daily(key).index[10]
    as_of = pd.Timestamp(day).tz_localize("America/New_York") + pd.Timedelta(hours=16)
    view = again.datasets.view([core.id, feat.id], as_of)
    assert key in view.universe()
    assert len(view.series(feat.series[0], key)) > 0
    with pytest.raises(LookAheadError):
        view.bars(key, "1min", end=as_of + pd.Timedelta(minutes=1))


def test_usage_is_tracked_and_protects_datasets(tmp_path):
    ws = Workspace(data_root=tmp_path)
    core = ws.datasets.add("synthetic_stocks", SMALL)
    feat = ws.datasets.generate("realised_vol", core.id, {"window": 3})
    g = StrategyGraph("S1", "gaps", settings={"datasets": [core.id]})
    ws.strategies.put("S1", g)
    assert ws.datasets.used_by(core.id) == ["S1"]
    with pytest.raises(DatasetInUse):
        ws.datasets.remove(core.id)
    g.settings["datasets"] = []
    ws.strategies.put("S1", g)
    assert ws.datasets.used_by(core.id) == []
    with pytest.raises(DatasetInUse):  # the generated dataset was made from it
        ws.datasets.remove(core.id)
    ws.datasets.remove(feat.id)
    ws.datasets.remove(core.id)
    assert len(ws.datasets) == 0 and not any(tmp_path.glob("synthetic*"))
    assert Workspace(data_root=tmp_path).datasets.ids() == []


def test_import_files(tmp_path):
    idx = pd.date_range("2025-03-03 09:30", periods=60, freq="1min")
    pd.DataFrame({"time": idx, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1}) \
        .to_csv(tmp_path / "qqq.csv", index=False)
    ws = Workspace(data_root=tmp_path / "data")
    info = ws.datasets.import_files([tmp_path / "qqq.csv"])
    assert info.name == "qqq" and info.instruments == ["xnas:QQQ"]
    assert info.source.plugin == "file_import"


def test_sources_not_built_yet_say_so(tmp_path):
    ws = Workspace(data_root=tmp_path)
    with pytest.raises(NotImplementedError):
        ws.datasets.add("polygon")


# ---- strategy ids, names and deleting ---------------------------------------------------
def test_new_strategy_names_reuse_the_lowest_free_number_but_ids_never_repeat():
    ws = Workspace()
    seen = set()
    for _ in range(3):
        sid = ws.new_strategy_id()
        assert sid.startswith("s-") and sid not in seen
        seen.add(sid)
        ws.strategies.put(sid, StrategyGraph(sid, ws.new_strategy_name()))
    names = {sid: ws.strategies.get(sid).name for sid in ws.strategies.ids()}
    assert sorted(names.values()) == ["Strategy 1", "Strategy 2", "Strategy 3"]
    two = next(s for s, n in names.items() if n == "Strategy 2")
    ws.strategies.remove(two)
    assert ws.new_strategy_name() == "Strategy 2"  # the name frees up...
    assert ws.new_strategy_id() not in seen  # ...the id never does


def test_deleting_a_strategy_removes_its_runs_and_backtests_but_not_the_yardstick():
    from titanium.core.baseline import DEFAULT_ID
    from titanium.core.default_strategy import DEFAULT_STRATEGY_ID
    from titanium.core.module_library import momentum_rotation

    ws = Workspace()
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 4, "n_days": 30, "seed": 5})
    keep, gone = momentum_rotation(id="s-keep"), momentum_rotation(id="s-gone")
    for g in (keep, gone):
        g.settings["datasets"] = [info.id]
        ws.strategies.put(g.id, g)
    kept_run = ws.runs.run("s-keep")
    runs = [ws.runs.run("s-gone"), ws.runs.run("s-gone")]
    ws.backtests.run(runs[0].id, "benchmark")  # also adds a default-strategy (yardstick) run
    ws.backtests.run(kept_run.id, "cost_stress")
    yardsticks = [r.id for r in ws.runs.records(DEFAULT_ID)]
    assert yardsticks
    fp = ws.strategy_footprint("s-gone")
    assert (fp.runs, fp.backtests, fp.running) == (2, 1, 0)

    removed = []
    ws.runs.removed.connect(removed.append)
    assert ws.delete_strategy("s-gone") == fp
    assert "s-gone" not in ws.strategies and not ws.runs.records("s-gone")
    assert sorted(removed) == sorted(r.id for r in runs)
    assert not ws.backtests.results(runs[0].id)
    assert [r.id for r in ws.runs.records(DEFAULT_ID)] == yardsticks  # shared: stays
    assert ws.runs.records("s-keep") and ws.backtests.results(kept_run.id)  # others untouched
    assert ws.datasets.used_by(info.id) == ["s-keep"]
    # a run of it that finishes after the delete is dropped
    late = runs[1]
    ws.runs.commit(late)
    assert late.id not in ws.runs
    with pytest.raises(ValueError):
        ws.delete_strategy(DEFAULT_STRATEGY_ID)


def test_the_default_strategy_runs_like_any_strategy():
    from titanium.core.default_strategy import default_strategy

    ws = Workspace()
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 3, "n_days": 30, "seed": 1})
    g = default_strategy()
    g.settings["datasets"] = [info.id]
    ws.strategies.put(g.id, g)
    rec = ws.runs.run(g.id)
    assert rec.status == "done", rec.error
    assert set(g.knobs()) == {"hold.rebalance_monthly", "hold.exposure"}
