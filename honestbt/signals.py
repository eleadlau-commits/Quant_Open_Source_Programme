"""What exit-signal plugins receive, and the causality check run on them.

The signals themselves are plugin folders (``exit-signals``).

A signal is ``f(path, ctx, **params) -> bool array`` over the minute bars of a
position, starting at the entry bar. ``out[i]`` means "at the close of bar i,
exit". The engine fills the exit at the *next* bar's open, so a signal can
never trade on the bar that triggered it.

Causality contract: ``out[i]`` may depend only on ``path[:i+1]`` and on
``ctx`` (which holds values known at entry). :func:`check_causal` enforces this
by perturbing the future and checking the past did not change; the engine runs
it on the first position of every run in strict mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .registry import get


@dataclass
class Path:
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @classmethod
    def from_array(cls, ts, arr):
        return cls(ts, arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4])

    def __len__(self):
        return len(self.close)

    @property
    def minutes_held(self) -> np.ndarray:
        return ((self.ts - self.ts[0]) // np.timedelta64(1, "m")).astype(np.int64)


@dataclass
class EntryContext:
    symbol: str
    entry_time: np.datetime64
    entry_price: float
    feature: Callable[[str], float] = field(repr=False, default=lambda name: float("nan"))


def run_signal(spec: dict, path: Path, ctx: EntryContext) -> np.ndarray:
    fn = get("signal", spec["plugin"])
    out = np.asarray(fn(path, ctx, **spec.get("params", {})), dtype=bool)
    if out.shape != (len(path),):
        raise ValueError(f"signal {spec['plugin']} returned shape {out.shape}, expected {(len(path),)}")
    return out


class CausalityError(RuntimeError):
    pass


def check_causal(spec: dict, path: Path, ctx: EntryContext, trials: int = 3, seed: int = 0) -> None:
    """Raise CausalityError if the signal's past output changes when the future changes."""
    n = len(path)
    if n < 4:
        return
    rng = np.random.default_rng(seed)
    base = run_signal(spec, path, ctx)
    for _ in range(trials):
        cut = int(rng.integers(1, n - 1))
        scale = rng.uniform(0.5, 1.5, n - cut - 1)
        def bump(x):
            y = x.copy()
            y[cut + 1:] = y[cut + 1:] * scale
            return y
        alt = Path(path.ts, bump(path.open), bump(path.high), bump(path.low), bump(path.close), bump(path.volume))
        out = run_signal(spec, alt, ctx)
        if not np.array_equal(out[: cut + 1], base[: cut + 1]):
            raise CausalityError(
                f"signal {spec['plugin']!r} looks ahead: its output at bar <= {cut} changed when only bars after {cut} changed")
