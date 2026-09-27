"""Prioritize inexpensive direct uploads-playlist checks for validated uploaders."""
from datetime import datetime, timedelta, timezone

def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

def select_due_channels(channels, now, candidate_interval_minutes=60, candidate_batch=6):
    """Check confirmed channels each run, rotate provisional accounts hourly."""
    confirmed = sorted((ch for ch in channels if ch.get("confidence") == "confirmed"
                        and ch.get("channel_id")), key=lambda ch: ch["channel_id"])
    candidates = [ch for ch in channels if ch.get("confidence") != "confirmed"
                  and ch.get("channel_id")]
    cutoff = now - timedelta(minutes=candidate_interval_minutes)
    due = [ch for ch in candidates if
           (parse_time(ch.get("last_checked_at")) or datetime.min.replace(
               tzinfo=timezone.utc)) <= cutoff]
    due.sort(key=lambda ch: (parse_time(ch.get("last_checked_at")) or
                             datetime.min.replace(tzinfo=timezone.utc), ch["channel_id"]))
    return confirmed + due[:candidate_batch]

def select_new_upload_ids(items, seen_ids, confirmed_ids, now, lookback_hours=336):
    """Resolve full metadata for only recent, unseen public channel uploads."""
    cutoff = now - timedelta(hours=lookback_hours)
    result = []
    for item in items:
        details = item.get("contentDetails") or {}
        video_id = details.get("videoId")
        if not video_id or video_id in seen_ids or video_id in confirmed_ids:
            continue
        published = parse_time(details.get("videoPublishedAt"))
        if published and published < cutoff:
            continue
        if video_id not in result:
            result.append(video_id)
    return result
