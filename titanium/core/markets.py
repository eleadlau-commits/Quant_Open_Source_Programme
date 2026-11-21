"""Markets: where instruments trade, on which days and hours, in which time zone.

All timestamps in Titanium are timezone-aware and stored in UTC. A market says how
to show them (its local time zone) and when it is open. Adding a market (another
exchange, crypto, FX) means adding a ``Market``, never changing the engine.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, datetime, time
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from .calendars import CmeEquityCalendar, NasdaqCalendar


@dataclass(frozen=True)
class Session:
    """One named trading session in the market's local time, e.g. pre-market or regular."""

    name: str
    start: time
    end: time


@runtime_checkable
class Calendar(Protocol):
    """Which days a market trades. Published in advance, so using it is never look-ahead."""

    def trading_days(self, start: date, end: date) -> list[date]: ...

    def is_trading_day(self, day: date) -> bool: ...

    def early_close(self, day: date) -> time | None:
        """Local close time on a shortened day, or ``None`` on a normal day."""
        ...


@dataclass(frozen=True)
class MarketDefaults:
    """How a run trades this market unless the strategy or the run says otherwise.

    ``extended_hours``: trade outside the regular session. ``decide_at``: when the strategy
    decides, market local time. Costs, chosen by instrument kind inside the market: for stocks
    half the spread and slippage in basis points of the price plus a commission per share; for
    futures a commission per contract per side and slippage in ticks (see ``core/sim/costs.py``).
    Flat, so the app can save and edit it; :meth:`settings` gives the engine's shape.
    """

    extended_hours: bool = False
    decide_at: str = "15:50"
    half_spread_bps: float = 5.0
    slippage_bps: float = 3.0
    commission_per_share: float = 0.0
    futures_commission: float = 0.85
    futures_slippage_ticks: float = 1.0

    def __post_init__(self) -> None:
        costs = (self.half_spread_bps, self.slippage_bps, self.commission_per_share, self.futures_commission,
                 self.futures_slippage_ticks)
        if any(c < 0 for c in costs):
            raise ValueError("costs can't be negative")
        h, _, m = str(self.decide_at).partition(":")
        if not (h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60):
            raise ValueError(f"decide_at must look like 15:50, not {self.decide_at!r}")

    def settings(self) -> dict[str, Any]:
        """These defaults as the engine reads them."""
        return {
            "extended_hours": self.extended_hours, "decide_at": self.decide_at,
            "costs": {"equity": {"half_spread_bps": self.half_spread_bps, "slippage_bps": self.slippage_bps,
                                 "commission_per_share": self.commission_per_share},
                      "futures": {"commission_per_side": self.futures_commission,
                                  "slippage_ticks": self.futures_slippage_ticks}},
        }

    def to_dict(self) -> dict[str, Any]:
        """Flat, for saving."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, base: "MarketDefaults | None" = None) -> "MarketDefaults":
        """Saved values over ``base`` (or the plain defaults); anything missing or broken keeps the base value."""
        out = base or cls()
        for f in fields(cls):
            value = (data or {}).get(f.name)
            if value in (None, ""):
                continue
            try:
                if isinstance(getattr(out, f.name), bool):
                    value = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes")
                out = replace(out, **{f.name: type(getattr(out, f.name))(value)})
            except (TypeError, ValueError):
                continue
        return out


@dataclass(frozen=True)
class Market:
    id: str
    name: str
    timezone: str
    currency: str
    sessions: tuple[Session, ...]
    regular: str = "regular"  # the session that counts as "the trading day"
    notes: str = ""
    short_name: str = ""  # for tables, e.g. "Nasdaq"
    kinds: tuple[str, ...] = ()  # instrument kinds it lists (``InstrumentKind`` values); empty: any
    calendar: Calendar | None = field(default=None, compare=False, repr=False)
    defaults: MarketDefaults = field(default_factory=MarketDefaults, compare=False, repr=False)

    @property
    def short(self) -> str:
        return self.short_name or self.name

    def trades(self, kind: str) -> bool:
        """Whether instruments of ``kind`` ("stock", "future") list here."""
        return not self.kinds or kind in self.kinds

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def session(self, name: str | None = None) -> Session:
        name = name or self.regular
        for s in self.sessions:
            if s.name == name:
                return s
        raise KeyError(f"market {self.id!r} has no session {name!r}")

    def with_defaults(self, defaults: MarketDefaults) -> "Market":
        """The same market with other defaults (the app's saved edits)."""
        return replace(self, defaults=defaults)

    def holidays(self, year: int) -> dict[date, str]:
        """Weekdays the market is closed (or doesn't settle) in ``year``, with why."""
        fn = getattr(self.calendar, "holidays", None)
        return dict(fn(year)) if fn is not None else {}

    def local(self, ts: datetime) -> datetime:
        """A UTC (or any aware) timestamp shown in the market's local time."""
        if ts.tzinfo is None:
            raise ValueError("Titanium timestamps must be timezone-aware")
        return ts.astimezone(self.tz)


# The first market, with its rule-based exchange calendar.
NASDAQ = Market(
    id="xnas",
    name="Nasdaq (US)",
    timezone="America/New_York",
    currency="USD",
    sessions=(
        Session("pre", time(4, 0), time(9, 30)),
        Session("regular", time(9, 30), time(16, 0)),
        Session("post", time(16, 0), time(20, 0)),
    ),
    short_name="Nasdaq",
    kinds=("stock",),
    calendar=NasdaqCalendar(),
    defaults=MarketDefaults(extended_hours=False),  # stocks trade the regular session unless asked
)

# US index futures (NQ, MNQ) on CME Globex: nearly round the clock, 18:00 to 17:00 New York
# time with a one-hour halt. The "regular" session is the cash-market day, so daily bars
# line up with stocks. CME's own holiday rules: see ``CmeEquityCalendar``.
CME_GLOBEX = Market(
    id="cme",
    name="CME Globex (US index futures)",
    timezone="America/New_York",
    currency="USD",
    sessions=(
        Session("overnight", time(18, 0), time(9, 30)),
        Session("regular", time(9, 30), time(16, 0)),
        Session("close", time(16, 0), time(17, 0)),
    ),
    notes="On US holidays Globex closes or halts early and doesn't settle that day.",
    short_name="CME",
    kinds=("future",),
    calendar=CmeEquityCalendar(),
    defaults=MarketDefaults(extended_hours=True),  # futures trade round the clock
)

MARKETS = {NASDAQ.id: NASDAQ, CME_GLOBEX.id: CME_GLOBEX}
