from titanium.plugins.testing import loaded


def test_realised_volatility_adds_its_entries():
    reg = loaded("realised-volatility")
    assert reg.get("generators", "realised_vol") is not None
