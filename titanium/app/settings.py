"""Settings the app layer needs: defaults for every run, and where the module library lives.

The desktop app saves these in its settings store and hands them to the workspace
(``Workspace.run_defaults``, ``Workspace.library_folder``). The run service starts every
run from them: defaults, then the strategy's own settings, then the run's. No Qt here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any

EVERY = {"day": "Every day", "week": "Every week", "month": "Every month"}  # the engine's ``every``


@dataclass(frozen=True)
class RunDefaults:
    """What a new run starts with unless the strategy or the run says otherwise.

    The names follow the engine's settings (``core/sim``): ``capital`` (notional
    starting cash), ``every`` and ``decide_at`` (when the strategy decides, exchange
    local time), and the cost model: for stocks the half spread and slippage in basis
    points of the price plus a commission per share; for futures a commission per
    contract per side and slippage in ticks.
    """

    capital: float = 100_000.0
    every: str = "day"
    decide_at: str = "15:50"
    half_spread_bps: float = 5.0
    slippage_bps: float = 3.0
    commission_per_share: float = 0.0
    futures_commission: float = 0.85
    futures_slippage_ticks: float = 1.0

    def __post_init__(self) -> None:
        if not self.capital > 0:
            raise ValueError("capital must be more than zero")
        costs = (self.half_spread_bps, self.slippage_bps, self.commission_per_share, self.futures_commission,
                 self.futures_slippage_ticks)
        if any(c < 0 for c in costs):
            raise ValueError("costs can't be negative")
        if self.every not in EVERY:
            raise ValueError(f"every must be one of {', '.join(EVERY)}")
        h, _, m = self.decide_at.partition(":")
        if not (h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60):
            raise ValueError(f"decide_at must look like 15:50, not {self.decide_at!r}")

    def to_dict(self) -> dict[str, Any]:
        """Flat, for saving."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RunDefaults":
        """Read saved values; anything missing or broken falls back to its default."""
        out = cls()
        for f in fields(cls):
            if not data or data.get(f.name) in (None, ""):
                continue
            try:
                out = replace(out, **{f.name: type(getattr(out, f.name))(data[f.name])})
            except (TypeError, ValueError):
                continue
        return out

    def engine_settings(self) -> dict[str, Any]:
        """These defaults as the engine reads them."""
        return {
            "capital": self.capital, "every": self.every, "decide_at": self.decide_at,
            "costs": {"equity": {"half_spread_bps": self.half_spread_bps, "slippage_bps": self.slippage_bps,
                                 "commission_per_share": self.commission_per_share},
                      "futures": {"commission_per_side": self.futures_commission,
                                  "slippage_ticks": self.futures_slippage_ticks}},
        }

    def apply(self, *layers: dict[str, Any] | None) -> dict[str, Any]:
        """A run's settings: these defaults, then each layer on top (strategy, then run).
        ``costs`` merge key by key, so a strategy can change one cost and keep the rest."""
        return merge(self.engine_settings(), *layers)


def merge(base: dict[str, Any], *layers: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base)
    for layer in layers:
        for k, v in (layer or {}).items():
            if k == "costs" and isinstance(v, dict) and isinstance(out.get(k), dict):
                costs = {**out[k]}
                for part, value in v.items():
                    costs[part] = ({**costs[part], **value} if isinstance(value, dict)
                                   and isinstance(costs.get(part), dict) else value)
                out[k] = costs
            else:
                out[k] = v
    return out
