"""Pure, side-effect-free Gmail submission and notification decisions.

Network access and credentials belong in separate adapters. A website submission
is never automatically independently verified show footage.
"""
import re
from urllib.parse import urlparse, parse_qs

RECIPIENTS = ("jmabray@gmail.com", "communications@hebronband.org", "Admin@hebronband.org")
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
TIKTOK_ID = re.compile(r"^\\d{15,22}$")
IG_ID = re.compile(r"^[A-Za-z0-9_-]{8,20}$")

def canonical_video(url):
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
        parts = [p for p in parsed.path.split("/") if p]
        if parsed.scheme not in ("https", "http"):
            return None
        if host in ("youtube.com", "music.youtube.com") and parts:
            ident = parse_qs(parsed.query).get("v", [""])[0] if parts[0] == "watch" else (parts[1] if parts[0] in ("shorts", "live") and len(parts)>1 else "")
            return "youtube:" + ident if YOUTUBE_ID.fullmatch(ident) else None
        if host == "youtu.be" and parts and YOUTUBE_ID.fullmatch(parts[0]):
            return "youtube:" + parts[0]
        if host == "tiktok.com" and len(parts) >= 3 and parts[1] == "video" and TIKTOK_ID.fullmatch(parts[2]):
            return "tiktok:" + parts[2]
        if host == "instagram.com" and len(parts) >= 2 and parts[0] in ("p", "reel", "tv") and IG_ID.fullmatch(parts[1]):
            return "instagram:" + parts[1]
    except (ValueError, TypeError, AttributeError):
        return None
    return None

def intake_decision(message_id, url, processed_ids, existing_keys):
    """Return a decision. Only a successful remote Gmail mutation may finalize processing."""
    if message_id in processed_ids:
        return {"action": "already_processed", "message_id": message_id}
    key = canonical_video(url)
    if not key:
        return {"action": "unresolved_link", "message_id": message_id, "canonical_id": None}
    return {"action": "duplicate" if key in existing_keys else "new_submission",
            "message_id": message_id, "canonical_id": key,
            "independently_verified": False}

def eligible_recipients(canonical_id, independently_verified, outbox, sent_search):
    """Fail closed: uncertain sent status must be reconciled before sending.

    outbox maps (canonical_id, recipient.lower()) to delivery status.
    sent_search maps (canonical_id, recipient.lower()) to True/False/None.
    """
    if not independently_verified or not canonical_id:
        return []
    result = []
    for recipient in RECIPIENTS:
        key = (canonical_id, recipient.lower())
        status = outbox.get(key)
        if status in ("sent", "sending", "uncertain"):
            continue
        if sent_search.get(key) is not False:
            continue
        result.append(recipient)
    return result

def finalize_submission(decision, remote_labels_verified):
    """Never record processed Gmail IDs before READ/LABEL/ARCHIVE verification."""
    return bool(remote_labels_verified and decision["action"] in ("duplicate", "new_submission"))
