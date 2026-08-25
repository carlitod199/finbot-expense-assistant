# -*- coding: utf-8 -*-
"""Date and timezone helpers.

Every date the bot works with ("today", the current month, the current week)
is anchored to a single timezone, configurable through the FINBOT_TZ
environment variable. It defaults to UTC.
"""

from __future__ import annotations

import calendar
import os
from datetime import date, datetime, timedelta

# IANA timezone name, e.g. "Europe/Lisbon" or "America/New_York".
TZ_NAME = os.environ.get("FINBOT_TZ", "UTC")

try:
    from zoneinfo import ZoneInfo  # Python 3.9+

    TZ = ZoneInfo(TZ_NAME)
except Exception:  # pragma: no cover - fallback when tzdata or the name is missing
    TZ = None


def today() -> date:
    """Today's date in the configured timezone."""
    now = datetime.now(TZ) if TZ else datetime.now()
    return now.date()


def current_month() -> str:
    """The current month in "YYYY-MM" format."""
    return today().strftime("%Y-%m")


def month_of(d: date) -> str:
    """The month of a given date in "YYYY-MM" format."""
    return d.strftime("%Y-%m")


def days_in_month(d: date | None = None) -> int:
    """Number of days in the month containing `d` (default: today)."""
    d = d or today()
    return calendar.monthrange(d.year, d.month)[1]


def current_week(d: date | None = None) -> tuple[date, date]:
    """The (Monday, Sunday) range of the week containing `d`."""
    d = d or today()
    monday = d - timedelta(days=d.weekday())  # weekday(): Monday == 0
    sunday = monday + timedelta(days=6)
    return monday, sunday


def parse_iso(text: str) -> date | None:
    """Parse "YYYY-MM-DD" into a date; return None if invalid."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
