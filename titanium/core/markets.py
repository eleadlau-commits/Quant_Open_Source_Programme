"""Markets: where instruments trade, on which days and hours, in which time zone.

All timestamps in Titanium are timezone-aware and stored in UTC. A market says how
to show them (its local time zone) and when it is open. Adding a market (another
exchange, crypto, FX) means adding a ``Market``, never changing the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from .calendars import NasdaqCalendar


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
class Market:
    id: str
    name: str
    timezone: str
    currency: str
    sessions: tuple[Session, ...]
    regular: str = "regular"  # the session that counts as "the trading day"
    notes: str = ""
    calendar: Calendar | None = field(default=None, compare=False, repr=False)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def session(self, name: str | None = None) -> Session:
        name = name or self.regular
        for s in self.sessions:
            if s.name == name:
                return s
        raise KeyError(f"market {self.id!r} has no session {name!r}")

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
    calendar=NasdaqCalendar(),
)

# US index futures (NQ, MNQ) on CME Globex: nearly round the clock, 18:00 to 17:00 New York
# time with a one-hour halt. The "regular" session is the cash-market day, so daily bars
# line up with stocks. Uses the US equity holiday calendar until a CME calendar is added.
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
    notes="Uses the US equity holiday calendar for now.",
    calendar=NasdaqCalendar(),
)

MARKETS = {NASDAQ.id: NASDAQ, CME_GLOBEX.id: CME_GLOBEX}
