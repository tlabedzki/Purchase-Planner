import datetime as dt

import pandas as pd

from purchase_planner import calendar


def test_black_friday_and_easter():
    assert calendar.black_friday(2024) == dt.date(2024, 11, 29)
    assert calendar.black_friday(2023) == dt.date(2023, 11, 24)
    assert calendar.easter_sunday(2024) == dt.date(2024, 3, 31)
    assert calendar.easter_sunday(2025) == dt.date(2025, 4, 20)


def test_first_event_wins_and_ordinary_days_are_empty():
    days = calendar.build(pd.date_range("2024-11-20", "2024-12-31"))
    event = dict(zip(days["date"].dt.strftime("%m-%d"), days["event"], strict=True))
    assert event["11-29"] == "black_friday"
    assert event["11-25"] == "black_week" and event["12-02"] == "cyber_monday" and event["12-03"] == "mikolajki"
    assert event["12-25"] == event["12-26"] == "christmas"
    assert event["11-21"] == ""
    assert days["weekday"].iloc[0] == 2  # 2024-11-20 is a Wednesday
