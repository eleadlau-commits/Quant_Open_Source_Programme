from titanium.plugins.testing import loaded


def test_synthetic_data_adds_its_entries():
    reg = loaded("synthetic-data")
    assert reg.get("data_sources", "synthetic_stocks") is not None
