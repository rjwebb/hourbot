import datetime as dt
from collections import Counter
from zoneinfo import ZoneInfo

import pytest

from hours import Schedule

LONDON = ZoneInfo("Europe/London")
UTC = dt.timezone.utc

EVENING = Schedule(LONDON, dt.time(21, 0), dt.timedelta(minutes=60))
LATE = Schedule(LONDON, dt.time(23, 0), dt.timedelta(minutes=120))  # crosses midnight

# 2026 in Europe/London: clocks go forward 29 March, back 25 October.
SPRING_FORWARD = dt.date(2026, 3, 29)
FALL_BACK = dt.date(2026, 10, 25)


def every_minute_of(year: int):
    """Every real minute of the year, as a London-local aware datetime.
    Stepping in UTC (not local time) is what makes DST nights come out right."""
    start = dt.datetime(year, 1, 1, tzinfo=UTC)
    end = dt.datetime(year + 1, 1, 1, tzinfo=UTC)
    minutes = int((end - start).total_seconds() // 60)
    return ((start + dt.timedelta(minutes=i)).astimezone(LONDON) for i in range(minutes))


def test_evening_window_matches_wall_clock_all_year():
    for now in every_minute_of(2026):
        expected = dt.time(21, 0) <= now.time() < dt.time(22, 0)
        assert (EVENING.current_window(now) is not None) is expected, now


def test_late_window_matches_wall_clock_all_year():
    for now in every_minute_of(2026):
        expected = now.time() >= dt.time(23, 0) or now.time() < dt.time(1, 0)
        assert (LATE.current_window(now) is not None) is expected, now


def test_evening_window_is_sixty_minutes_every_day_including_dst_days():
    open_minutes = Counter(
        now.date() for now in every_minute_of(2026) if EVENING.current_window(now)
    )
    assert len(open_minutes) == 365
    assert set(open_minutes.values()) == {60}
    assert open_minutes[SPRING_FORWARD] == 60
    assert open_minutes[FALL_BACK] == 60


def test_current_window_returns_the_start_of_the_window():
    now = dt.datetime(2026, 6, 1, 21, 30, tzinfo=LONDON)
    assert EVENING.current_window(now) == dt.datetime(2026, 6, 1, 21, 0, tzinfo=LONDON)

    # 00:30 belongs to the window that began yesterday at 23:00.
    now = dt.datetime(2026, 6, 2, 0, 30, tzinfo=LONDON)
    assert LATE.current_window(now) == dt.datetime(2026, 6, 1, 23, 0, tzinfo=LONDON)


def test_close_time_on_spring_forward_night_is_gmt_not_bst():
    # Window opened 23:00 on 28 March. At 00:30 on the 29th it is still open
    # and closes at 01:00, which is before the clocks change. The lobby topic
    # prints %Z, so getting the zone wrong here is visible to users.
    now = dt.datetime(2026, 3, 29, 0, 30, tzinfo=LONDON)
    window = LATE.current_window(now)
    assert window is not None
    closes = window + LATE.duration
    assert closes == dt.datetime(2026, 3, 29, 1, 0, tzinfo=LONDON)
    assert closes.utcoffset() == dt.timedelta(0)
    assert f"{closes:%H:%M %Z}" == "01:00 GMT"


def test_next_opening_is_the_next_time_the_window_opens():
    for now in every_minute_of(2026):
        if now.minute % 97:  # sample roughly every hour and a half
            continue
        nxt = EVENING.next_opening(now)
        assert nxt > now
        assert nxt.time() == dt.time(21, 0)
        assert nxt - now <= dt.timedelta(days=1, hours=1)
        assert EVENING.current_window(nxt) == nxt
        assert EVENING.current_window(nxt - dt.timedelta(minutes=1)) is None


def test_boundaries_are_zone_aware_open_and_close_times():
    assert EVENING.boundaries == [
        dt.time(21, 0, tzinfo=LONDON),
        dt.time(22, 0, tzinfo=LONDON),
    ]
    assert LATE.boundaries == [
        dt.time(23, 0, tzinfo=LONDON),
        dt.time(1, 0, tzinfo=LONDON),
    ]


def test_accepts_now_in_a_different_zone():
    # 20:30 UTC on 1 June is 21:30 BST: open.
    now = dt.datetime(2026, 6, 1, 20, 30, tzinfo=UTC)
    assert EVENING.current_window(now) == dt.datetime(2026, 6, 1, 21, 0, tzinfo=LONDON)
    # Same wall time in winter is 20:30 GMT: closed.
    now = dt.datetime(2026, 1, 1, 20, 30, tzinfo=UTC)
    assert EVENING.current_window(now) is None


@pytest.mark.parametrize("minutes", [0, -1, 24 * 60, 24 * 60 + 1])
def test_rejects_nonsensical_durations(minutes):
    with pytest.raises(ValueError):
        Schedule(LONDON, dt.time(21, 0), dt.timedelta(minutes=minutes))
