import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build
from search_budget import paced_allowance, quota_day_key
from candidate_rules import triage_video
from channel_watch import select_due_channels, select_new_upload_ids

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
REPORT_PATH = ROOT / "report.md"

API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "7"))
WATCH_THRESHOLD = int(os.environ.get("WATCH_THRESHOLD", "4"))
SEARCHES_PER_RUN = int(os.environ.get("SEARCHES_PER_RUN", "3"))
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "96"))
DAILY_SEARCH_BUDGET = int(os.environ.get("DAILY_SEARCH_BUDGET", "90"))
MAX_WATCH_CHANNELS = int(os.environ.get("MAX_WATCH_CHANNELS", "40"))
CHANNEL_LOOKBACK_HOURS = int(os.environ.get("CHANNEL_LOOKBACK_HOURS", "336"))
CANDIDATE_CHECK_MINUTES = int(os.environ.get("CANDIDATE_CHECK_MINUTES", "60"))

if not API_KEY:
    print("YOUTUBE_API_KEY is not set.", file=sys.stderr)
    sys.exit(2)

config = json.loads(CONFIG_PATH.read_text())
state = json.loads(STATE_PATH.read_text())
youtube = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)
now = datetime.now(timezone.utc)

def today_key():
    return quota_day_key(now)

def normalize(text):
    return (text or "").lower()

def search_budget_remaining():
    ledger = state.setdefault("daily_search_ledger", {})
    for key in list(ledger.keys()):
        if key < quota_day_key(now - timedelta(days=7)):
            del ledger[key]
    return max(0, DAILY_SEARCH_BUDGET - int(ledger.get(today_key(), 0)))

def spend_search():
    ledger = state.setdefault("daily_search_ledger", {})
    ledger[today_key()] = int(ledger.get(today_key(), 0)) + 1

def add_watch_channel(channel_id, channel_title, source_video_id, reason, confidence="candidate"):
    if not channel_id:
        return False
    channels = state.setdefault("known_channels", [])
    for ch in channels:
        if ch.get("channel_id") == channel_id:
            if confidence == "confirmed":
                ch["confidence"] = "confirmed"
            ch["last_reinforced_at"] = now.isoformat()
            return False
    if len(channels) >= MAX_WATCH_CHANNELS and confidence != "confirmed":
        return False
    channels.append({
        "channel_id": channel_id,
        "channel_title": channel_title,
        "source_video_id": source_video_id,
        "reason": reason,
        "confidence": confidence,
        "added_at": now.isoformat(),
        "last_reinforced_at": now.isoformat()
    })
    return True

def score_video(video, known_channel_ids):
    snippet = video.get("snippet", {})
    title = normalize(snippet.get("title"))
    desc = normalize(snippet.get("description"))
    tags = " ".join(normalize(x) for x in snippet.get("tags", []))
    channel_title = normalize(snippet.get("channelTitle"))
    haystack = " ".join([title, desc, tags, channel_title])
    score, reasons = 0, []
    weights = config["scoring"]
    negative_terms = config.get("negative_terms", [])
    negative_hits = [t for t in negative_terms if normalize(t) in haystack]
    if negative_hits:
        score -= min(12, 4 + 2 * len(negative_hits))
        reasons.append("negative context: " + ", ".join(negative_hits[:3]))

    if "hebron" in haystack:
        score += weights["exact_hebron"]; reasons.append("Hebron appears in metadata")
    if "somewhere in time" in haystack:
        score += weights["show_title"]; reasons.append("show title appears in metadata")

    for term in config.get("repertoire_terms", []):
        if normalize(term) in haystack:
            score += weights["repertoire_term"]; reasons.append(f"repertoire term: {term}"); break

    for term in config["leak_terms"]:
        if normalize(term) in haystack:
            score += weights["leak_term"]; reasons.append(f"leak/full-show term: {term}"); break

    band_cues = config.get("band_cues", [])
    has_band_cue = any(normalize(x) in haystack for x in band_cues)
    has_hebron = "hebron" in haystack
    has_show = "somewhere in time" in haystack
    if has_band_cue and (has_hebron or has_show or snippet.get("channelId") in known_channel_ids):
        score += weights.get("band_cue", 0); reasons.append("marching/halftime/performance cue")

    for event in config["events"]:
        candidates = [event.get("name",""), event.get("opponent","")]
        # Venue-only matches are too generic to justify event confidence.
        if any(len(normalize(x)) >= 8 and normalize(x) in haystack for x in candidates):
            score += weights["event_term"]; reasons.append(f"event fingerprint: {event['name']}"); break

    if "2026" in haystack or "26" in title:
        score += weights["year_2026"]; reasons.append("2026/year cue")
    if snippet.get("channelId") in known_channel_ids:
        score += weights["known_channel"]; reasons.append("watched relevant channel")
    return score, reasons

def fetch_video_details(video_ids):
    items = []
    for i in range(0, len(video_ids), 50):
        ids = video_ids[i:i+50]
        if not ids: continue
        resp = youtube.videos().list(
            part="snippet,contentDetails,status,recordingDetails,liveStreamingDetails",
            id=",".join(ids)
        ).execute()
        items.extend(resp.get("items", []))
    return items

def search_youtube(query, order="date", lookback_hours=None):
    hours = lookback_hours or LOOKBACK_HOURS
    published_after = (now - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    resp = youtube.search().list(
        part="snippet", q=query, type="video", order=order, maxResults=50,
        publishedAfter=published_after, safeSearch="none", regionCode="US",
        relevanceLanguage="en"
    )
    # Even unsuccessful API requests may consume quota: count each attempted call.
    spend_search()
    resp = resp.execute()
    return [x["id"]["videoId"] for x in resp.get("items", []) if x.get("id", {}).get("videoId")]

def get_uploads_playlist(channel):
    # Cache the uploads playlist ID so subsequent checks need only one API call.
    if channel.get("uploads_playlist_id"):
        return channel["uploads_playlist_id"]
    resp = youtube.channels().list(
        part="contentDetails", id=channel["channel_id"]).execute()
    items = resp.get("items", [])
    if not items:
        return None
    playlist_id = items[0].get("contentDetails", {}).get(
        "relatedPlaylists", {}).get("uploads")
    if playlist_id:
        channel["uploads_playlist_id"] = playlist_id
    return playlist_id

def latest_channel_upload_ids(channel, seen, seeds, max_results=20):
    playlist_id = get_uploads_playlist(channel)
    if not playlist_id:
        return []
    resp = youtube.playlistItems().list(
        part="contentDetails", playlistId=playlist_id, maxResults=max_results
    ).execute()
    ids = select_new_upload_ids(resp.get("items", []), seen, seeds, now,
                                CHANNEL_LOOKBACK_HOURS)
    channel["last_checked_at"] = now.isoformat()
    return ids

def event_queries():
    q = []
    # These deliberately omit "Hebron" in some cases to catch opponent-side and vague uploads.
    for event in config["events"]:
        opponent = event.get("opponent")
        location = event.get("location")
        name = event.get("name")
        q.append(f'Hebron {name}')
        if opponent:
            q.extend([
                f'Hebron {opponent} band',
                f'{opponent} halftime marching band 2026',
                f'{opponent} vs Hebron halftime',
            ])
        if location:
            q.append(f'"{location}" marching band 2026')
    return q

def recent_event_queries():
    """Give recent performances dedicated search slots instead of waiting for the long rotation."""
    queries = []
    for event in reversed(config["events"]):
        try:
            event_date = datetime.fromisoformat(event["date"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if not timedelta(0) <= now - event_date <= timedelta(days=5):
            continue
        for query in event.get("discovery_queries", []):
            if query not in queries:
                queries.append(query)
    return queries

def priority_queries():
    # Compact OR searches buy broader discovery per search.list call.
    return config.get("priority_queries", [])

def select_queries():
    priority = priority_queries()
    rotating = recent_event_queries() + config["search_queries"] + event_queries()
    # Protect late-afternoon/evening discovery by pacing the daily API allowance.
    remaining = search_budget_remaining()
    spent = int(state.get("daily_search_ledger", {}).get(today_key(), 0))
    available = min(remaining, paced_allowance(now, spent, DAILY_SEARCH_BUDGET, SEARCHES_PER_RUN))
    if available <= 0: return []
    selected = []
    # Every fourth run spend one slot on a relevance-ranked query to catch older/index-late uploads.
    run_count = int(state.get("run_count", 0))
    recent = recent_event_queries()
    # Reserve one search per run for the most recent event while it is fresh.
    # Even when the paced allowance is just one call, periodically check
    # relevance-ranked results over two weeks to catch late-indexed uploads.
    if priority and run_count % 8 == 7:
        selected.append((priority[(run_count // 8) % len(priority)], "relevance", 24 * 14))
    elif recent and run_count % 3 != 0:
        selected.append((recent[run_count % len(recent)], "date", LOOKBACK_HOURS))
    elif priority:
        selected.append((priority[run_count % len(priority)], "date", LOOKBACK_HOURS))
    cursor = int(state.get("query_cursor", 0)) % max(1, len(rotating))
    while len(selected) < available and rotating:
        q = rotating[cursor % len(rotating)]
        order = "relevance" if run_count % 4 == 3 and len(selected) == available - 1 else "date"
        hours = 24 * 14 if order == "relevance" else LOOKBACK_HOURS
        selected.append((q, order, hours))
        cursor += 1
    state["query_cursor"] = cursor % max(1, len(rotating))
    return selected

# Migration: prune four historical channels learned from false-positive football
# and competing-band results. Confirmed uploaders are always retained, and new
# candidate channels must now pass the stricter triage below.
if not state.get("channel_cleanup_v1"):
    state["known_channels"] = [ch for ch in state.get("known_channels", [])
                                if ch.get("confidence") == "confirmed"]
    state["channel_cleanup_v1"] = True

# Prefer saved verified uploader IDs. Only look up seed video metadata when
# the channel ID is not already known; don't spend an API call each run.
seed_refs = [ref for ref in config.get("confirmed_videos", [])
             if ref.get("video_id") and ref.get("platform", "YouTube").lower() == "youtube"]
seed_ids = [ref["video_id"] for ref in seed_refs]
unresolved_seed_ids = []
for ref in seed_refs:
    channel_id = ref.get("channel_id")
    channel_title = ref.get("channel_title", "")
    if not channel_id:
        known_seed = next((ch for ch in state.get("known_channels", [])
                           if ch.get("source_video_id") == ref["video_id"]
                           and ch.get("confidence") == "confirmed"), None)
        if known_seed:
            channel_id, channel_title = known_seed["channel_id"], known_seed.get("channel_title", "")
    if channel_id:
        add_watch_channel(channel_id, channel_title, ref["video_id"],
                          "uploader of confirmed Hebron video", "confirmed")
    else:
        unresolved_seed_ids.append(ref["video_id"])
for video in fetch_video_details(unresolved_seed_ids):
    metadata = video.get("snippet", {})
    add_watch_channel(metadata.get("channelId"), metadata.get("channelTitle", ""),
                      video["id"], "uploader of confirmed Hebron video", "confirmed")

seen = set(state.get("seen_video_ids", []))
known_channels = {ch["channel_id"]: ch for ch in state.get("known_channels", [])
                  if ch.get("channel_id")}
known_channel_ids = set(known_channels)
confirmed_channel_ids = {x["channel_id"] for x in known_channels.values()
                         if x.get("confidence") == "confirmed"}
recent_review_terms = []
for event in config["events"]:
    try:
        event_date = datetime.fromisoformat(event["date"]).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        continue
    if timedelta(0) <= now - event_date <= timedelta(days=5):
        recent_review_terms.extend(event.get("review_terms", []))
        recent_review_terms.append(event.get("name", ""))
candidate_ids = set()
searches_run = []
checked_channels, unseen_channel_ids, channel_errors = [], 0, []

# Keyword searches discover accounts; low-cost uploads-playlist checks
# prioritize known uploaders on every scheduled run, regardless of search quota.
for query, order, hours in select_queries():
    try:
        candidate_ids.update(search_youtube(query, order=order, lookback_hours=hours))
        searches_run.append(f"{query} [{order}]")
    except Exception as exc:
        print(f"Search failed for {query!r}: {exc}", file=sys.stderr)

for channel in select_due_channels(state.get("known_channels", []), now,
                                   CANDIDATE_CHECK_MINUTES):
    try:
        new_ids = latest_channel_upload_ids(channel, seen, set(seed_ids))
        candidate_ids.update(new_ids)
        unseen_channel_ids += len(new_ids)
        checked_channels.append(channel.get("channel_title") or channel["channel_id"])
    except Exception as exc:
        channel_errors.append(channel.get("channel_id"))
        print(f"Channel check failed for {channel.get('channel_id')}: {exc}",
              file=sys.stderr)

# Skip repeat full-metadata calls for older search matches or playlist entries.
candidate_ids.difference_update(seen)
candidate_ids.difference_update(seed_ids)
details = fetch_video_details(sorted(candidate_ids))
alerts, review_candidates, watch_additions, all_scored = [], [], [], []
uploader_reviews = []

confirmed_ids = set(seed_ids)
for video in details:
    vid = video["id"]
    score, reasons = score_video(video, known_channel_ids)
    s = video.get("snippet", {})
    row = {
        "video_id": vid, "title": s.get("title",""), "channel": s.get("channelTitle",""),
        "channel_id": s.get("channelId",""), "published_at": s.get("publishedAt",""),
        "score": score, "reasons": reasons,
        "url": f"https://www.youtube.com/watch?v={vid}"
    }
    all_scored.append(row)

    # Labels are based on title/description evidence, not the numeric score alone.
    # Generic event captions from confirmed uploaders become review candidates.
    category, triage_reasons = triage_video(
        s, config, score, confirmed_channel_ids, recent_review_terms,
        ALERT_THRESHOLD, WATCH_THRESHOLD)
    row["triage_reasons"] = triage_reasons

    # Only explicit Hebron performance uploads create candidate channel watches.
    if category == "alert" and score >= WATCH_THRESHOLD and vid not in confirmed_ids:
        if add_watch_channel(row["channel_id"], row["channel"], vid,
                             "explicit Hebron band evidence; " + ", ".join(triage_reasons)):
            watch_additions.append(row)
            known_channel_ids.add(row["channel_id"])

    # User-submitted seeds are already known and must not generate repeat alerts.
    if vid not in seen and vid not in confirmed_ids:
        if category == "alert":
            alerts.append(row)
        elif category == "review":
            review_candidates.append(row)
            if row["channel_id"] in confirmed_channel_ids:
                uploader_reviews.append(row)

seen.update(v["id"] for v in details)
state["seen_video_ids"] = sorted(seen)
state["last_run"] = now.isoformat()
state["run_count"] = int(state.get("run_count", 0)) + 1
STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")

lines = [
    "# Hebron YouTube Monitor Report","",
    f"- Run: {now.isoformat()}",
    f"- Search calls used in current Pacific quota day: {state['daily_search_ledger'].get(today_key(), 0)} / {DAILY_SEARCH_BUDGET}",
    f"- Searches this run: {len(searches_run)}",
    f"- Watched relevant channels: {len(state.get('known_channels', []))}",
    f"- Upload channels checked this run: {len(checked_channels)}",
    f"- New IDs from direct playlist checks: {unseen_channel_ids}",
    f"- Channel check errors: {len(channel_errors)}",
    f"- New watch channels learned: {len(watch_additions)}",
    f"- New high-confidence candidates: {len(alerts)}",
    f"- New needs-review candidates: {len(review_candidates)}",
    f"- New verified-uploader clips needing review: {len(uploader_reviews)}",
    f"- Report displays at most 25 alerts and 20 learned channels","",
]
if searches_run:
    lines += ["## Queries",""] + [f"- `{q}`" for q in searches_run] + [""]
if watch_additions:
    lines += ["## Newly learned channels",""]
    for a in watch_additions[:20]:
        lines += [f"- **{a['channel']}** from {a['title']} (score {a['score']})"]
    lines += [""]
if alerts:
    lines += ["## New high-confidence candidates",""]
    for a in sorted(alerts, key=lambda x:x["score"], reverse=True)[:25]:
        lines += [f"### {a['title']}","",f"- URL: {a['url']}",f"- Channel: {a['channel']}",
                  f"- Published: {a['published_at']}",f"- Score: {a['score']}",
                  f"- Reasons: {', '.join(a['reasons']) or 'none'}",
                  f"- Identity evidence: {', '.join(a['triage_reasons'])}",""]
else:
    lines += ["## New high-confidence candidates","","None.",""]

if uploader_reviews:
    lines += ["## New clips from confirmed uploaders needing review", ""]
    for a in uploader_reviews[:15]:
        lines += [f"- [{a['title']}]({a['url']}) — {a['channel']}; {', '.join(a['triage_reasons'])}", ""]
if review_candidates:
    lines += ["## Needs manual review (not alerted)", ""]
    for a in sorted(review_candidates, key=lambda x: x["score"], reverse=True)[:15]:
        lines += [f"- [{a['title']}]({a['url']}) — {a['channel']}; score {a['score']}; {', '.join(a['triage_reasons'])}", ""]

lines += ["## Known cross-platform references (not directly crawled)", ""]
for ref in config.get("confirmed_videos", []):
    if ref.get("platform", "YouTube").lower() != "youtube" and ref.get("url"):
        lines += [f"- {ref['platform']}: {ref['url']} ({ref.get('event', 'event unverified')})"]
lines += [""]
REPORT_PATH.write_text("\n".join(lines) + "\n")
print(f"ALERT_COUNT={len(alerts)}")
print(f"UPLOADER_REVIEW_COUNT={len(uploader_reviews)}")
print(f"WATCH_ADDITIONS={len(watch_additions)}")
print(f"REPORT_PATH={REPORT_PATH}")
