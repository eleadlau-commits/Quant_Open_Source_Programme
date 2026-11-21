"""Settings the app layer needs: defaults for every run, market defaults, and where the module library lives.

The desktop app saves these in its settings store and hands them to the workspace
(``Workspace.run_defaults``, ``Workspace.set_market_defaults``, ``Workspace.library_folder``).
A run's settings resolve in layers (``core/layers.py``): the app's run defaults, then the
traded market's defaults (with the app's edits), then the strategy's settings, then the run's.
No Qt here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any

from ..core.layers import merge_settings
from ..core.markets import MARKETS, MarketDefaults

EVERY = {"day": "Every day", "week": "Every week", "month": "Every month"}  # the engine's ``every``


@dataclass(frozen=True)
class RunDefaults:
    """App-wide values a new run starts with unless the market, strategy or run says otherwise.

    ``capital`` (notional starting cash), ``every`` (how often the strategy decides),
    ``max_gross`` (the exposure cap, as a fraction of equity) and ``min_trade`` (skip target
    trades smaller than this fraction of equity). Decision time, sessions and costs depend on
    the venue, so they are market defaults (``core/markets.py``).
    """

    capital: float = 100_000.0
    every: str = "day"
    max_gross: float = 1.0
    min_trade: float = 0.0

    def __post_init__(self) -> None:
        if not self.capital > 0:
            raise ValueError("capital must be more than zero")
        if self.every not in EVERY:
            raise ValueError(f"every must be one of {', '.join(EVERY)}")
        if not 0 < self.max_gross <= 10:
            raise ValueError("the exposure cap must be more than zero and at most 10")
        if not 0 <= self.min_trade < 1:
            raise ValueError("the smallest trade must be from 0 to less than 1 (a fraction of equity)")

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
        return {"capital": self.capital, "every": self.every, "max_gross": self.max_gross,
                "min_trade": self.min_trade}

    def apply(self, *layers: dict[str, Any] | None) -> dict[str, Any]:
        """These defaults, then each layer on top (market, strategy, run)."""
        return merge_settings(self.engine_settings(), *layers)


merge = merge_settings  # older name

# Before markets had defaults, decision time and costs were run defaults. ``migrate_run_settings``
# moves saved values of these into each market's defaults: stock costs to markets of stocks,
# futures costs to markets of futures, the decision time to both.
OLD_RUN_KEYS = ("decide_at", "half_spread_bps", "slippage_bps", "commission_per_share", "futures_commission",
                "futures_slippage_ticks")


def migrate_run_settings(saved: dict[str, Any] | None) -> dict[str, MarketDefaults]:
    """Market defaults (by market id) holding what an older version saved as run defaults.

    Only markets the old values change are returned; an empty dict means nothing to move."""
    old = {k: v for k, v in (saved or {}).items() if k in OLD_RUN_KEYS and v not in (None, "")}
    out: dict[str, MarketDefaults] = {}
    for mid, market in MARKETS.items():
        new = MarketDefaults.from_dict(old, market.defaults)
        if new != market.defaults:
            out[mid] = new
    return out
