import json
from pathlib import Path

import pytest

from honestbt.registry import load_plugins

load_plugins()
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def base_config():
    return json.loads((ROOT / "configs" / "monday_gap_top5.json").read_text())


@pytest.fixture(scope="session")
def small_data():
    from honestbt.data.synthetic import synthetic
    return synthetic(n_symbols=20, n_days=60, seed=3)
