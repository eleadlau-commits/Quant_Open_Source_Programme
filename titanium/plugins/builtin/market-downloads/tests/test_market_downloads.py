from titanium.plugins.testing import loaded


def test_market_downloads_adds_its_entries():
    reg = loaded("market-downloads")
    assert reg.get("data_sources", "polygon") is not None
