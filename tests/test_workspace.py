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
