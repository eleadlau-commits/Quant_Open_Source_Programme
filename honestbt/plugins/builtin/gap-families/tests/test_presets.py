import json

from honestbt.patchbay import expand_sweep, validate
from honestbt.plugins import presets


def test_presets_are_valid_families():
    mine = [p for p in presets() if p["plugin"] == "gap-families"]
    assert len(mine) == 2
    for p in mine:
        cfg = json.loads(open(p["path"]).read())
        assert validate(cfg) == []
        assert len(expand_sweep(cfg)) >= 6
