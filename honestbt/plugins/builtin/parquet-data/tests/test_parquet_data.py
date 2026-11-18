import pandas as pd
import pytest

from honestbt.plugins.testing import plugin


def test_reads_what_synthetic_writes(tmp_path):
    pytest.importorskip("pyarrow")
    src = plugin("data", "synthetic")(n_symbols=3, n_days=10, seed=1)
    (tmp_path / "minute").mkdir()
    for s in src.symbols:
        df = pd.DataFrame(src.arr[s], columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex(src.ts[s]))
        df.to_parquet(tmp_path / "minute" / f"{s}.parquet")
    got = plugin("data", "parquet")(root=str(tmp_path))
    assert got.symbols == src.symbols and (got.arr[src.symbols[0]] == src.arr[src.symbols[0]]).all()
