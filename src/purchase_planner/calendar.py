"""
The retail calendar of a Polish online shop: weekdays, months and the trading days that move demand (Black Friday,
Christmas, Easter and so on). These are public dates, not data from the shop; the forecast learns how much each of
them moves demand from the sales history.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

# Name -> how to find its days in a year. The first match wins when days overlap (Black Friday before Black Week).
EVENTS = ["black_friday", "cyber_monday", "black_week", "singles_day", "mikolajki", "christmas_eve", "christmas",
          "new_years_eve", "new_year", "easter_sunday", "easter_monday", "valentines_week", "mothers_day_week",
          "childrens_day_week"]
FIXED = {
    "singles_day": ("11-11", "11-11"),
    "mikolajki": ("12-01", "12-05"),
    "christmas_eve": ("12-24", "12-24"),
    "christmas": ("12-25", "12-26"),
    "new_years_eve": ("12-31", "12-31"),
    "new_year": ("01-01", "01-01"),
    "valentines_week": ("02-07", "02-13"),
    "mothers_day_week": ("05-19", "05-25"),
    "childrens_day_week": ("05-26", "05-31"),
}


def easter_sunday(year: int) -> dt.date:
    """Easter Sunday of a year (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return dt.date(year, month, day)


def black_friday(year: int) -> dt.date:
    """The Friday after the fourth Thursday of November."""
    first = dt.date(year, 11, 1)
    thursday = first + dt.timedelta(days=(3 - first.weekday()) % 7 + 21)
    return thursday + dt.timedelta(days=1)


def event_days(year: int) -> dict[str, list[dt.date]]:
    """Days of every event in one year."""
    friday = black_friday(year)
    easter = easter_sunday(year)
    days = {
        "black_friday": [friday],
        "cyber_monday": [friday + dt.timedelta(days=3)],
        "black_week": [friday - dt.timedelta(days=k) for k in range(4, 0, -1)],
        "easter_sunday": [easter],
        "easter_monday": [easter + dt.timedelta(days=1)],
    }
    for name, (start, end) in FIXED.items():
        first = dt.date.fromisoformat(f"{year}-{start}")
        last = dt.date.fromisoformat(f"{year}-{end}")
        days[name] = [first + dt.timedelta(days=k) for k in range((last - first).days + 1)]
    return days


def build(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per day: date, month (1-12), weekday (0 = Monday) and event (empty string on an ordinary day)."""
    dates = pd.DatetimeIndex(dates)
    event = np.full(len(dates), "", dtype=object)
    position = {day.date(): i for i, day in enumerate(dates)}
    for year in sorted(set(dates.year)):
        days = event_days(year)
        for name in reversed(EVENTS):  # earlier names win: they are written last
            for day in days[name]:
                if day in position:
                    event[position[day]] = name
    return pd.DataFrame({"date": dates, "month": dates.month, "weekday": dates.weekday, "event": event})
