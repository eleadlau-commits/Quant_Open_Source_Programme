from honestbt.plugins.testing import plugin


def test_linear_clips():
    f = plugin("mapping", "linear")
    assert f(0.5, slope=10, intercept=1) == 6
    assert f(10, slope=10, hi=20) == 20 and f(-10, slope=1, lo=0) == 0


def test_piecewise_and_step():
    assert plugin("mapping", "piecewise")(0.5, points=[[0, 0], [1, 10]]) == 5
    assert plugin("mapping", "step")(0.7, thresholds=[0.3, 0.6], values=[1, 2, 3]) == 3
    assert plugin("mapping", "constant")(123, value=4) == 4 and plugin("mapping", "identity")(7) == 7
