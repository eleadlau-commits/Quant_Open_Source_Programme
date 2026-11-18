from honestbt.patchbay import expand_evaluators, validate
from honestbt.plugins import suites
from honestbt.registry import has


def test_every_suite_names_loaded_evaluators():
    s = suites()
    assert {"honest-stocks", "honest-futures", "quick"} <= set(s)
    for specs in s.values():
        assert specs and all(has("evaluator", e["plugin"]) for e in specs)


def test_suite_reference_expands_in_place():
    cfg = {"evaluators": [{"plugin": "bootstrap"}, {"$suite": "quick"}]}
    assert [e["plugin"] for e in expand_evaluators(cfg)] == ["bootstrap", "out_of_sample", "deflated_sharpe", "cost_stress"]


def test_unknown_suite_is_a_config_problem():
    problems = validate({"strategy": {"plugin": "weekly_topn"}, "evaluators": [{"$suite": "nope"}]})
    assert any("no test suite named 'nope'" in p for p in problems)
