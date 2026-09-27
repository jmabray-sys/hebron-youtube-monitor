"""Pace YouTube search.list calls across YouTube's Pacific Time quota day."""
from datetime import datetime, time, timedelta, timezone
from math import ceil
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def quota_day_key(now):
    """Google resets the YouTube Data API's daily buckets at midnight PT."""
    if now.tzinfo is None:
        raise ValueError("now must have timezone information")
    return now.astimezone(PACIFIC).date().isoformat()


def paced_allowance(now, spent_today, daily_limit=90, max_per_run=3,
                    run_interval_minutes=20):
    """Accrue permitted searches evenly within the current Pacific quota day.

    Uses actual UTC duration between successive Pacific midnights (23, 24 or
    25 hours depending on daylight saving) and banks unused calls. Google
    currently has a separate default search.list bucket of 100 calls/day;
    our 90-call software cap leaves headroom.
    """
    if now.tzinfo is None:
        raise ValueError("now must have timezone information")
    if daily_limit <= 0 or max_per_run <= 0:
        return 0
    pacific_now = now.astimezone(PACIFIC)
    start = datetime.combine(pacific_now.date(), time.min, tzinfo=PACIFIC)
    end = datetime.combine(pacific_now.date() + timedelta(days=1),
                           time.min, tzinfo=PACIFIC)
    elapsed = (now.astimezone(timezone.utc) -
               start.astimezone(timezone.utc)).total_seconds()
    duration = (end.astimezone(timezone.utc) -
                start.astimezone(timezone.utc)).total_seconds()
    accrued = ceil(daily_limit * min(duration, elapsed +
                                    run_interval_minutes * 60) / duration)
    return max(0, min(max_per_run, daily_limit - spent_today,
                      accrued - spent_today))
