"""Opening-hours arithmetic. No Discord in here, so it can be tested offline."""

import datetime as dt
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Schedule:
    """A daily window that opens at `open_at` local time in `tz` and lasts
    `duration`. Everything is done in a real zone (not a fixed UTC offset),
    which is what keeps the opening hour fixed in local time across DST."""

    tz: ZoneInfo
    open_at: dt.time
    duration: dt.timedelta

    def __post_init__(self) -> None:
        if not dt.timedelta(0) < self.duration < dt.timedelta(days=1):
            raise ValueError("duration must be between 1 minute and 1 day")

    @property
    def close_at(self) -> dt.time:
        return (dt.datetime.combine(dt.date.min, self.open_at) + self.duration).time()

    @property
    def boundaries(self) -> list[dt.time]:
        """Zone-aware open and close times, for a scheduler that fires daily."""
        return [self.open_at.replace(tzinfo=self.tz), self.close_at.replace(tzinfo=self.tz)]

    def opening_on(self, day: dt.date) -> dt.datetime:
        return dt.datetime.combine(day, self.open_at, tzinfo=self.tz)

    def current_window(self, now: dt.datetime) -> Optional[dt.datetime]:
        """Start of the window containing `now`, or None if closed. Checks
        yesterday's window too, for windows that run past midnight."""
        local = now.astimezone(self.tz)
        for offset in (0, -1):
            start = self.opening_on(local.date() + dt.timedelta(days=offset))
            if start <= local < start + self.duration:
                return start
        return None

    def next_opening(self, now: dt.datetime) -> dt.datetime:
        local = now.astimezone(self.tz)
        for offset in (0, 1):
            start = self.opening_on(local.date() + dt.timedelta(days=offset))
            if start > local:
                return start
        raise RuntimeError("unreachable")
