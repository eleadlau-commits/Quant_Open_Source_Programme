from titanium.plugins.testing import loaded


def test_starter_modules_adds_its_entries():
    reg = loaded("starter-modules")
    assert reg.get("modules", "starter/Momentum") is not None
