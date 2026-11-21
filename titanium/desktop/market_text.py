"""How markets read in the app: their sessions, defaults and holidays as plain text.

Shared by the pages that mention a market (Data, Settings, the Run view), so a market
reads the same everywhere. No widgets here.
"""
from __future__ import annotations

from datetime import date

from ..core.markets import Market

SESSION_NAMES = {"pre": "Pre-market", "post": "After hours", "regular": "Regular", "overnight": "Overnight",
                 "close": "Close"}


def tz_name(tz) -> str:
    """``America/New_York`` reads as ``New York``."""
    return str(tz).split("/")[-1].replace("_", " ")


def session_name(name: str) -> str:
    return SESSION_NAMES.get(name, name.replace("_", " ").capitalize())


def sessions_text(m: Market) -> str:
    """"Pre-market 04:00–09:30, Regular 09:30–16:00, After hours 16:00–20:00"."""
    return ", ".join(f"{session_name(s.name)} {s.start:%H:%M}–{s.end:%H:%M}" for s in m.sessions)


def market_text(m: Market) -> str:
    """The name, then sessions in local time, time zone and currency (two lines)."""
    return f"{m.name}\n{sessions_text(m)} ({tz_name(m.tz)} time) · {m.currency}"


def hours_text(m: Market, extended: bool | None = None) -> str:
    """Which hours a run trades: "regular hours" or "all sessions"."""
    extended = m.defaults.extended_hours if extended is None else extended
    if not extended:
        reg = m.session()
        return f"regular hours ({reg.start:%H:%M}–{reg.end:%H:%M})"
    return "all sessions"


def holidays_text(m: Market, year: int | None = None) -> str:
    """One line per holiday this year: "1 Jan  New Year's Day"."""
    year = year or date.today().year
    days = m.holidays(year)
    if not days:
        return "None listed"
    return "\n".join(f"{d.day} {d:%b}  {why}" for d, why in sorted(days.items()))
