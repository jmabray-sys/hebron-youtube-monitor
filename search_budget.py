"""Spread YouTube search calls across the UTC day instead of exhausting quota early."""
from datetime import timezone
from math import ceil


def paced_allowance(now, spent_today, daily_limit=90, max_per_run=3, run_interval_minutes=20):
    """Return searches allowed now, banking unused calls for later runs.

    Quota accrues approximately evenly throughout the UTC day. Looking ahead one
    scheduled run interval lets the final run before midnight use the full budget.
    This is a local rate limit; YouTube's actual API quota may differ.
    """
    if now.tzinfo is None:
        raise ValueError("now must have timezone information")
    if daily_limit <= 0 or max_per_run <= 0:
        return 0
    utc_now = now.astimezone(timezone.utc)
    seconds_elapsed = utc_now.hour * 3600 + utc_now.minute * 60 + utc_now.second
    accrued = ceil(daily_limit * min(86400, seconds_elapsed + run_interval_minutes * 60) / 86400)
    return max(0, min(max_per_run, daily_limit - spent_today, accrued - spent_today))
