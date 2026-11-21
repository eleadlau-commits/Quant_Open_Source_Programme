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
