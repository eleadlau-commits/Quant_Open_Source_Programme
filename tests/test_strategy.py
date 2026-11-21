"""The strategy model, its file, the code bridge and the compiled strategy."""
from datetime import datetime, timezone

import pytest

from titanium.core.module_library import (
    STARTER, add_to_graph, folders, momentum_rotation, register_starters,
)
from titanium.core.plugins import Library, Registry
from titanium.core.portfolio import PortfolioState
from titanium.core.strategy import (
    Decision, KnobType, Strategy, StrategyGraph, graph_from_dict, graph_to_dict, load_strategy, save_strategy,
)
from titanium.core.strategy_code import (
    StrategyCodeError, generate, import_python, knob, make_knob, parse, update_from_code,
)
from titanium.core.strategy_compile import StrategyRunError, compile_graph

T0 = datetime(2025, 3, 3, 20, 50, tzinfo=timezone.utc)


class FakeView:
    """A tiny GuardedView: daily closes per instrument, already cut at as_of."""

    def __init__(self, closes: dict[str, list[float]]):
        self.as_of = T0
        self.closes = closes

    def universe(self):
        return list(self.closes)

    def bars(self, instrument, frequency, start=None, end=None):
        assert frequency == "1d"
        return {"close": self.closes[instrument]}

    def series(self, name, instrument=None):
        raise KeyError(name)


def rising(n, rate):
    return [100 * (1 + rate) ** i for i in range(n)]


VIEW = FakeView({"AAA": rising(80, 0.01), "BBB": rising(80, 0.002), "CCC": rising(80, -0.005),
                 "DDD": rising(80, 0.004)})
PORT = PortfolioState(time=T0, cash=1e6, equity=1e6, capital=1e6)

PLAIN = '''"""Hold stocks above their moving average."""
from honestbt.sdk import knob

SETTINGS = {"decide_at": "15:50", "every": "day"}

LOOKBACK_FLOOR = 2


def average(F, symbol, n):
    c = F.bars(symbol, "1d")["close"]
    return sum(c[-n:]) / n if len(c) >= n else None


def decide(F, p):
    n = knob("n", 50, lo=5, hi=200)
    held = [s for s in F.universe() if (a := average(F, s, max(n, LOOKBACK_FLOOR))) and F.bars(s, "1d")["close"][-1] > a]
    return {s: 1 / len(held) for s in held}
'''


# ---------------------------------------------------------------- model and file
def test_strategy_file_round_trips(tmp_path):
    g = momentum_rotation()
    g.knob_values["m3.top"] = 2
    save_strategy(g, tmp_path / "s.json")
    back = load_strategy(tmp_path / "s.json")
    assert graph_to_dict(back) == graph_to_dict(g)
    assert back.knob_value("m3.top") == 2 and back.knob_value("m1.days") == 20


def test_strategy_file_rejects_other_json():
    with pytest.raises(ValueError):
        graph_from_dict({"id": "x"})


def test_knob_types_and_ranges():
    g = momentum_rotation()
    k = g.knobs()
    assert k["m1.days"].type is KnobType.INT and (k["m1.days"].lo, k["m1.days"].hi) == (5, 120)
    assert k["m3.positive_only"].type is KnobType.BOOL


# ---------------------------------------------------------------- code bridge
def test_generated_code_round_trips_modules_links_and_knob_values():
    g = momentum_rotation()
    g.knob_values = {"m1.days": 30, "m3.positive_only": False}
    src = generate(g)
    back = parse(src, previous=g)
    assert [m.id for m in back.modules] == ["m1", "m2", "m3"]
    assert back.links == g.links
    assert back.knob_values == g.knob_values
    assert [m.layout for m in back.modules] == [m.layout for m in g.modules]
    assert [m.source for m in back.modules] == [m.source for m in g.modules]
    assert generate(back) == src  # stable


def test_an_edit_changes_only_what_was_edited():
    g = momentum_rotation()
    src = generate(g).replace('knob("top", 5, lo=1, hi=20)', 'knob("top", 8, lo=1, hi=30)')
    src = src.replace("    return scores\n", "    # strongest first\n    return scores\n", 1)
    back = update_from_code(g, src)
    assert back.id == g.id and back.name == g.name
    assert back.knobs()["m3.top"].default == 8 and back.knobs()["m3.top"].hi == 30
    assert "# strongest first" in back.module("m1").code
    assert back.module("m2").code == g.module("m2").code
    assert back.links == g.links


def test_adding_a_module_and_a_link_in_code():
    g = momentum_rotation()
    src = generate(g) + '''

@module(id="m9", kind="transform", outputs=["scores"], links={"scores": "m1.scores"})
def drop_small(scores):
    return {s: v for s, v in scores.items() if abs(v) > 0.01}
'''
    back = update_from_code(g, src)
    assert back.module("m9").inputs[0].name == "scores"
    assert any(ln.dst_module == "m9" and ln.src_module == "m1" for ln in back.links)


def test_a_file_may_say_where_a_module_sits_and_comes_from():
    src = '''@module(id="a", kind="decide", source="starter/Top N equal weight", layout=(10, 20))
def pick(view):
    return {}
'''
    m = parse(src).modules[0]
    assert m.source == "starter/Top N equal weight" and m.layout == (10.0, 20.0)


def test_bad_links_and_syntax_are_reported_with_lines():
    g = momentum_rotation()
    with pytest.raises(StrategyCodeError) as e:
        parse(generate(g).replace('"m1.scores"', '"m7.scores"'))
    assert "m7" in str(e.value)
    with pytest.raises(StrategyCodeError) as e:
        parse("def broken(:\n    pass\n")
    assert e.value.line == 1


def test_shared_code_and_comments_are_kept():
    g = momentum_rotation()
    g.preamble = "import math\n\nMIN_PRICE = 5"
    src = generate(g)
    back = parse(src, previous=g)
    assert "import math" in back.preamble and "MIN_PRICE = 5" in back.preamble
    assert generate(back) == src


def test_plain_python_file_imports_as_one_module():
    g = import_python(PLAIN, "S7", "Above average")
    assert [m.id for m in g.modules] == ["decide"] and g.modules[0].kind == "decide"
    assert g.settings == {"decide_at": "15:50", "every": "day"}
    assert "def average" in g.preamble and "LOOKBACK_FLOOR = 2" in g.preamble
    assert list(g.knobs()) == ["decide.n"]
    assert g.doc == "Hold stocks above their moving average."
    # and it keeps working after a trip through the code view
    again = update_from_code(g, generate(g))
    assert graph_to_dict(again) == graph_to_dict(g)


def test_empty_strategy_generates_and_parses():
    g = StrategyGraph(id="S1", name="Strategy 1")
    back = update_from_code(g, generate(g))
    assert back.modules == [] and back.name == "Strategy 1"


def test_two_copies_of_a_library_module_get_distinct_function_names():
    g = StrategyGraph(id="S1", name="Two momentums")
    reg = Registry()
    register_starters(reg)
    add_to_graph(g, reg, f"{STARTER}/Momentum")
    add_to_graph(g, reg, f"{STARTER}/Momentum")
    src = generate(g)
    assert "def momentum(" in src and "def momentum_2(" in src
    assert [m.id for m in parse(src, previous=g).modules] == ["m1", "m2"]


# ---------------------------------------------------------------- make knob
def test_make_knob_on_an_assignment_uses_its_name():
    src = generate(momentum_rotation())
    line_no, line = next((i, ln) for i, ln in enumerate(src.splitlines(), 1) if "> 0 or" in ln)
    src = src.replace("scores[s] > 0 or", "scores[s] > 0.02 or")
    col = src.splitlines()[line_no - 1].index("0.02") + 1
    out, name = make_knob(src, line_no, col)
    assert name == "value"
    g = parse(out)
    assert g.knobs()["m3.value"].default == 0.02 and g.knobs()["m3.value"].type is KnobType.REAL


def test_make_knob_names_from_the_assignment_and_avoids_clashes():
    src = 'from titanium.sdk import knob, module\n\n\n@module(id="a", kind="decide")\ndef pick(view):\n    days = 14\n    top = -3\n    return {}\n'
    out, name = make_knob(src, 6, 12)
    assert name == "days" and 'days = knob("days", 14, lo=3, hi=56)' in out
    out2, name2 = make_knob(out, 7, 11)
    assert name2 == "top" and 'knob("top", -3' in out2
    assert set(parse(out2).knobs()) == {"a.days", "a.top"}


def test_make_knob_refuses_outside_a_module_or_off_a_number():
    with pytest.raises(StrategyCodeError):
        make_knob(PLAIN, 6, 18)  # LOOKBACK_FLOOR = 2 is shared code
    with pytest.raises(StrategyCodeError):
        make_knob(PLAIN, 15, 6)  # on a name


# ---------------------------------------------------------------- compiled strategy
def test_compiled_graph_decides_with_knobs():
    g = momentum_rotation()
    strat = compile_graph(g)
    assert isinstance(strat, Strategy)
    d = strat.decide(VIEW, PORT)
    assert isinstance(d, Decision) and set(d.targets) == {"AAA", "BBB", "DDD"}
    g.knob_values["m3.top"] = 1
    assert compile_graph(g).decide(VIEW, PORT).targets == {"AAA": 1.0}


def test_compiled_plain_file_decides():
    g = import_python(PLAIN, "S7")
    d = compile_graph(g).decide(VIEW, PORT)
    assert set(d.targets) == {"AAA", "BBB", "DDD"}
    g.knob_values["decide.n"] = 200  # not enough history: holds nothing
    assert compile_graph(g).decide(VIEW, PORT).targets == {}


def test_module_errors_name_the_module():
    g = momentum_rotation()
    g.module("m2").code = g.module("m2").code.replace("kept = {}", "kept = {}\n    1 / 0")
    with pytest.raises(StrategyRunError) as e:
        compile_graph(g).decide(VIEW, PORT)
    assert e.value.module_id == "m2"


def test_knob_outside_a_run_returns_its_default():
    assert knob("x", 3) == 3


# ---------------------------------------------------------------- library
def test_starter_folder_in_the_module_library():
    reg = Registry()
    register_starters(reg)
    f = folders(reg)
    assert list(f) == [STARTER]
    assert {e.name for e in f[STARTER]} == {"starter/Momentum", "starter/Above moving average",
                                            "starter/Top N equal weight"}
    assert reg.get(Library.MODULES, "starter/Momentum").kind == "transform"
