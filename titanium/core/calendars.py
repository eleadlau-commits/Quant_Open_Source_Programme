"""Exchange calendars, worked out from rules (no network, no data needed).

A calendar is published in advance, so asking it about the future is never
look-ahead. ``NasdaqCalendar`` follows the US equity market rules used by NYSE
and Nasdaq since 1998: the ten full-day holidays (with weekend observance), Good
Friday, Juneteenth from 2022, the 13:00 early closes, and the one-off closures
(national days of mourning, storms) listed in ``SPECIAL_CLOSURES``.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

EARLY_CLOSE = time(13, 0)

# Days the market closed for reasons no rule predicts.
SPECIAL_CLOSURES: dict[date, str] = {
    date(2001, 9, 11): "September 11 attacks",
    date(2001, 9, 12): "September 11 attacks",
    date(2001, 9, 13): "September 11 attacks",
    date(2001, 9, 14): "September 11 attacks",
    date(2004, 6, 11): "Day of mourning: President Reagan",
    date(2007, 1, 2): "Day of mourning: President Ford",
    date(2012, 10, 29): "Hurricane Sandy",
    date(2012, 10, 30): "Hurricane Sandy",
    date(2018, 12, 5): "Day of mourning: President G. H. W. Bush",
    date(2025, 1, 9): "Day of mourning: President Carter",
}


def easter(year: int) -> date:
    """Western (Gregorian) Easter Sunday, by the anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th (1-based) given weekday of a month; n = -1 for the last one."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = (date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """Saturday holidays move to Friday, Sunday holidays to Monday."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=None)
def us_equity_holidays(year: int) -> dict[date, str]:
    """Full-day closures of the US equity market in ``year``."""
    MON, THU = 0, 3
    out: dict[date, str] = {}
    # New Year's Day: a Saturday New Year is *not* moved to the Friday before (a year-end rule).
    ny = date(year, 1, 1)
    if ny.weekday() != 5:
        out[_observed(ny)] = "New Year's Day"
    if year >= 1998:
        out[_nth_weekday(year, 1, MON, 3)] = "Martin Luther King Jr. Day"
    out[_nth_weekday(year, 2, MON, 3)] = "Washington's Birthday"
    out[easter(year) - timedelta(days=2)] = "Good Friday"
    out[_nth_weekday(year, 5, MON, -1)] = "Memorial Day"
    if year >= 2022:
        out[_observed(date(year, 6, 19))] = "Juneteenth"
    out[_observed(date(year, 7, 4))] = "Independence Day"
    out[_nth_weekday(year, 9, MON, 1)] = "Labor Day"
    out[_nth_weekday(year, 11, THU, 4)] = "Thanksgiving Day"
    out[_observed(date(year, 12, 25))] = "Christmas Day"
    for d, why in SPECIAL_CLOSURES.items():
        if d.year == year:
            out[d] = why
    return out


class NasdaqCalendar:
    """Trading days and hours of Nasdaq (and the US equity market generally).

    Times are local (America/New_York). ``session_open``/``session_close`` give the
    regular session in UTC, early closes included.
    """

    timezone = "America/New_York"
    open_time = time(9, 30)
    close_time = time(16, 0)

    def __init__(self) -> None:
        self.tz = ZoneInfo(self.timezone)

    # ---- the Calendar protocol --------------------------------------------
    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in us_equity_holidays(day.year)

    def trading_days(self, start: date, end: date) -> list[date]:
        out, d = [], start
        while d <= end:
            if self.is_trading_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def early_close(self, day: date) -> time | None:
        if not self.is_trading_day(day):
            return None
        thanksgiving = _nth_weekday(day.year, 11, 3, 4)
        if day == thanksgiving + timedelta(days=1):
            return EARLY_CLOSE
        if day.month == 7 and day.day == 3 and day.year >= 1996:
            return EARLY_CLOSE  # the day before Independence Day (if it is a trading day)
        if day.month == 12 and day.day == 24 and day.year >= 1999:
            return EARLY_CLOSE
        return None

    # ---- additions ------------------------------------------------------------
    def holiday(self, day: date) -> str | None:
        """Why the market is closed on a weekday, or ``None``."""
        return us_equity_holidays(day.year).get(day)

    def local_close(self, day: date) -> time:
        return self.early_close(day) or self.close_time

    def session_open(self, day: date) -> datetime:
        """Start of the regular session in UTC."""
        return datetime.combine(day, self.open_time, self.tz).astimezone(ZoneInfo("UTC"))

    def session_close(self, day: date) -> datetime:
        """End of the regular session in UTC (13:00 local on early-close days)."""
        return datetime.combine(day, self.local_close(day), self.tz).astimezone(ZoneInfo("UTC"))

    def previous_trading_day(self, day: date) -> date:
        d = day - timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def next_trading_day(self, day: date) -> date:
        d = day + timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def sessions(self, start: date, end: date) -> list[tuple[date, datetime, datetime]]:
        """(day, open UTC, close UTC) for each trading day from ``start`` to ``end``."""
        return [(d, self.session_open(d), self.session_close(d)) for d in self.trading_days(start, end)]
