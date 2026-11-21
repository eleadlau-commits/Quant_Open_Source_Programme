"""Settings the app layer needs: defaults for every run, and where the module library lives.

The desktop app saves these in its settings store and hands them to the workspace
(``Workspace.run_defaults``, ``Workspace.library_folder``); the engine reads them
from there. No Qt here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any

TIMEFRAMES = {"1d": "Daily", "1min": "Minute"}  # the Frequency values


@dataclass(frozen=True)
class RunDefaults:
    """What a new run starts with unless the strategy or the run says otherwise.

    ``capital``: notional starting cash, in the market's currency.
    ``commission_bps`` and ``slippage_bps``: costs per trade, in basis points of the
    traded value. ``timeframe``: how often the strategy decides, a Frequency value
    (``"1d"`` or ``"1min"``).
    """

    capital: float = 100_000.0
    commission_bps: float = 1.0
    slippage_bps: float = 2.0
    timeframe: str = "1d"

    def __post_init__(self) -> None:
        if not self.capital > 0:
            raise ValueError("capital must be more than zero")
        if self.commission_bps < 0 or self.slippage_bps < 0:
            raise ValueError("costs can't be negative")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {', '.join(TIMEFRAMES)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RunDefaults":
        """Read saved values; anything missing or broken falls back to its default."""
        out = cls()
        for f in fields(cls):
            if not data or data.get(f.name) in (None, ""):
                continue
            try:
                value = type(getattr(out, f.name))(data[f.name])
                out = replace(out, **{f.name: value})
            except (TypeError, ValueError):
                continue
        return out

    def apply(self, settings: dict[str, Any] | None) -> dict[str, Any]:
        """A run's settings: these defaults, overridden by what the strategy or run sets."""
        return {**self.to_dict(), **(settings or {})}
