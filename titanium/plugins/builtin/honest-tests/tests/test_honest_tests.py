from titanium.plugins.testing import loaded

IDS = ["out_of_sample", "walk_forward", "bootstrap", "deflated_sharpe", "cost_stress", "random_baseline",
       "benchmark", "parameter_stability", "ablation"]


def test_honest_tests_add_every_backtest_with_its_info():
    reg = loaded("honest-tests")
    for i in IDS:
        test = reg.get("backtests", i)
        assert test.info.id == i and test.info.name and test.info.doc
