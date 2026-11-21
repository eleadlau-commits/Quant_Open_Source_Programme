"""The decision clock: when a strategy decides, from its settings and the exchange calendar.

Settings (all optional):

* ``decide_at``: exchange local time, ``"15:50"`` (default), or a list for several
  decisions a day (``["09:45", "15:50"]``).
* ``every``: ``"day"`` (default), ``"week"`` (first trading day of each week) or
  ``"month"`` (first trading day of each month).
* ``start`` / ``end``: ``"YYYY-MM-DD"`` limits, inside the data's own span.

On an early-close day a decision time inside the regular session but after the
early close keeps its distance to the close (15:50 becomes 12:50), so a
"just before the close" strategy still trades that day.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterator

from ..markets import Market

UTC = timezone.utc


def parse_time(text: str | time) -> time:
    if isinstance(text, time):
        return text
    try:
        h, m = (int(x) for x in str(text).strip().split(":"))
        return time(h, m)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"decide_at must look like 15:50, got {text!r}") from e


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class DecisionClock:
    """Implements :class:`titanium.core.engine.Clock`."""

    def __init__(self, market: Market, first_day: date, last_day: date, settings: dict[str, Any] | None = None):
        settings = dict(settings or {})
        self.settings = settings
        self._span = (first_day, last_day)
        if market.calendar is None:
            raise ValueError(f"market {market.id!r} has no calendar")
        self.market = market
        at = settings.get("decide_at", "15:50")
        self.decide_at = sorted(parse_time(t) for t in (at if isinstance(at, (list, tuple)) else [at]))
        self.every = str(settings.get("every", "day"))
        if self.every not in ("day", "week", "month"):
            raise ValueError(f"every must be day, week or month, got {self.every!r}")
        tf = settings.get("time_frame") or {}
        start = _date(settings.get("start") or tf.get("start"))
        end = _date(settings.get("end") or tf.get("end"))
        self.first_day = max(first_day, start) if start else first_day
        self.last_day = min(last_day, end) if end else last_day

    def days(self) -> list[date]:
        cal = self.market.calendar
        days = cal.trading_days(self.first_day, self.last_day) if self.first_day <= self.last_day else []
        if self.every == "week":
            days = [d for i, d in enumerate(days) if i == 0 or d.isocalendar()[:2] != days[i - 1].isocalendar()[:2]]
        elif self.every == "month":
            days = [d for i, d in enumerate(days) if i == 0 or (d.year, d.month) != (days[i - 1].year, days[i - 1].month)]
        return days

    def _local(self, day: date, at: time) -> datetime:
        cal, reg = self.market.calendar, self.market.session()
        early = cal.early_close(day)
        if early is not None and early <= at < reg.end:
            shift = datetime.combine(day, reg.end) - datetime.combine(day, early)
            return datetime.combine(day, at, self.market.tz) - shift
        return datetime.combine(day, at, self.market.tz)

    def times(self) -> Iterator[datetime]:
        for d in self.days():
            for at in self.decide_at:
                yield self._local(d, at).astimezone(UTC)

    def decision_times(self, settings: dict[str, Any] | None = None) -> list[datetime]:
        """Decision times with ``settings`` laid over this clock's own (what
        ``GraphStrategy.decision_times(clock)`` calls with the graph's settings)."""
        if not settings:
            return list(self.times())
        return list(DecisionClock(self.market, *self._span, {**self.settings, **settings}).times())

    def end_time(self) -> datetime:
        """Midnight (exchange time) after the last day: pending orders are worked until then."""
        return datetime.combine(self.last_day + timedelta(days=1), time(0, 0), self.market.tz).astimezone(UTC)
