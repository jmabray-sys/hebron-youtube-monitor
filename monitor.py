import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
REPORT_PATH = ROOT / "report.md"

API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "7"))
SEARCHES_PER_RUN = int(os.environ.get("SEARCHES_PER_RUN", "3"))
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "72"))
DAILY_SEARCH_BUDGET = int(os.environ.get("DAILY_SEARCH_BUDGET", "90"))

if not API_KEY:
    print("YOUTUBE_API_KEY is not set.", file=sys.stderr)
    sys.exit(2)

config = json.loads(CONFIG_PATH.read_text())
state = json.loads(STATE_PATH.read_text())
youtube = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)
now = datetime.now(timezone.utc)


def today_key():
    return now.strftime("%Y-%m-%d")


def normalize(text):
    return (text or "").lower()


def search_budget_remaining():
    ledger = state.setdefault("daily_search_ledger", {})
    # Keep only recent ledger entries.
    for key in list(ledger.keys()):
        if key < (now - timedelta(days=7)).strftime("%Y-%m-%d"):
            del ledger[key]
    used = int(ledger.get(today_key(), 0))
    return max(0, DAILY_SEARCH_BUDGET - used)


def spend_search():
    ledger = state.setdefault("daily_search_ledger", {})
    ledger[today_key()] = int(ledger.get(today_key(), 0)) + 1


def score_video(video, known_channel_ids):
    snippet = video.get("snippet", {})
    title = normalize(snippet.get("title"))
    desc = normalize(snippet.get("description"))
    tags = " ".join(normalize(x) for x in snippet.get("tags", []))
    channel_title = normalize(snippet.get("channelTitle"))
    haystack = " ".join([title, desc, tags, channel_title])

    score = 0
    reasons = []
    weights = config["scoring"]

    if "hebron" in haystack:
        score += weights["exact_hebron"]
        reasons.append("Hebron appears in metadata")

    if normalize("Somewhere in Time") in haystack:
        score += weights["show_title"]
        reasons.append("show title appears in metadata")

    for term in ["For the Damaged Coda", "Serenada Schizophrana", "Scythian Suite", "Symphony No. 2"]:
        if normalize(term) in haystack:
            score += weights["repertoire_term"]
            reasons.append(f"repertoire term: {term}")
            break

    for term in config["leak_terms"]:
        if normalize(term) in haystack:
            score += weights["leak_term"]
            reasons.append(f"leak/full-show term: {term}")
            break

    for event in config["events"]:
        candidates = [event.get("name",""), event.get("location",""), event.get("opponent","")]
        if any(normalize(x) and normalize(x) in haystack for x in candidates):
            score += weights["event_term"]
            reasons.append(f"event fingerprint: {event['name']}")
            break

    if "2026" in haystack or "26" in title:
        score += weights["year_2026"]
        reasons.append("2026/year cue")

    if snippet.get("channelId") in known_channel_ids:
        score += weights["known_channel"]
        reasons.append("known relevant channel")

    return score, reasons


def fetch_video_details(video_ids):
    if not video_ids:
        return []
    items = []
    for i in range(0, len(video_ids), 50):
        resp = youtube.videos().list(
            part="snippet,contentDetails,status",
            id=",".join(video_ids[i:i+50])
        ).execute()
        items.extend(resp.get("items", []))
    return items


def search_youtube(query):
    published_after = (now - timedelta(hours=LOOKBACK_HOURS)).isoformat().replace("+00:00", "Z")
    resp = youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        order="date",
        maxResults=50,
        publishedAfter=published_after,
        safeSearch="none"
    ).execute()
    spend_search()
    return [x["id"]["videoId"] for x in resp.get("items", []) if x.get("id", {}).get("videoId")]


def get_uploads_playlist(channel_id):
    resp = youtube.channels().list(part="contentDetails,snippet", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def latest_channel_upload_ids(channel_id, max_results=20):
    playlist_id = get_uploads_playlist(channel_id)
    if not playlist_id:
        return []
    resp = youtube.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=playlist_id,
        maxResults=max_results
    ).execute()
    return [x["contentDetails"]["videoId"] for x in resp.get("items", [])]


def event_queries():
    q = []
    for event in config["events"]:
        q.append(f'Hebron {event["name"]}')
        if event.get("opponent"):
            q.append(f'Hebron {event["opponent"]} band')
    return q


def select_queries():
    pool = config["search_queries"] + event_queries()
    if not pool:
        return []
    cursor = int(state.get("query_cursor", 0)) % len(pool)
    available = min(SEARCHES_PER_RUN, search_budget_remaining())
    selected = [pool[(cursor + i) % len(pool)] for i in range(available)]
    state["query_cursor"] = (cursor + available) % len(pool)
    return selected


known_channels = {x["channel_id"]: x for x in state.get("known_channels", []) if x.get("channel_id")}
known_channel_ids = set(known_channels)
candidate_ids = set()
searches_run = []

for query in select_queries():
    try:
        ids = search_youtube(query)
        candidate_ids.update(ids)
        searches_run.append(query)
    except Exception as exc:
        print(f"Search failed for {query!r}: {exc}", file=sys.stderr)

# Channel-first checks are cheap and continue even when search budget is exhausted.
for channel_id in list(known_channel_ids):
    try:
        candidate_ids.update(latest_channel_upload_ids(channel_id))
    except Exception as exc:
        print(f"Channel check failed for {channel_id}: {exc}", file=sys.stderr)

# Always check known confirmed video IDs for status/metadata.
for item in config.get("confirmed_videos", []):
    candidate_ids.add(item["video_id"])

details = fetch_video_details(sorted(candidate_ids))
seen = set(state.get("seen_video_ids", []))
alerts = []
all_scored = []

for video in details:
    vid = video["id"]
    score, reasons = score_video(video, known_channel_ids)
    snippet = video.get("snippet", {})
    row = {
        "video_id": vid,
        "title": snippet.get("title", ""),
        "channel": snippet.get("channelTitle", ""),
        "channel_id": snippet.get("channelId", ""),
        "published_at": snippet.get("publishedAt", ""),
        "score": score,
        "reasons": reasons,
        "url": f"https://www.youtube.com/watch?v={vid}",
    }
    all_scored.append(row)

    if score >= ALERT_THRESHOLD and vid not in seen:
        alerts.append(row)
        channel_id = row["channel_id"]
        if channel_id and channel_id not in known_channel_ids:
            state.setdefault("known_channels", []).append({
                "channel_id": channel_id,
                "channel_title": row["channel"],
                "source_video_id": vid,
                "added_at": now.isoformat()
            })
            known_channel_ids.add(channel_id)

# Mark every fetched video as seen so weak candidates don't reprocess forever.
seen.update(v["id"] for v in details)
state["seen_video_ids"] = sorted(seen)
state["last_run"] = now.isoformat()
STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")

lines = [
    "# Hebron YouTube Monitor Report",
    "",
    f"- Run: {now.isoformat()}",
    f"- Search calls used today: {state['daily_search_ledger'].get(today_key(), 0)} / {DAILY_SEARCH_BUDGET}",
    f"- Searches this run: {len(searches_run)}",
    f"- Known relevant channels: {len(state.get('known_channels', []))}",
    f"- New alerts: {len(alerts)}",
    "",
]
if searches_run:
    lines += ["## Queries", ""] + [f"- `{q}`" for q in searches_run] + [""]

if alerts:
    lines += ["## New high-confidence candidates", ""]
    for a in sorted(alerts, key=lambda x: x["score"], reverse=True):
        lines += [
            f"### {a['title']}",
            "",
            f"- URL: {a['url']}",
            f"- Channel: {a['channel']}",
            f"- Published: {a['published_at']}",
            f"- Score: {a['score']}",
            f"- Reasons: {', '.join(a['reasons']) or 'none'}",
            ""
        ]
else:
    lines += ["## New high-confidence candidates", "", "None.", ""]

REPORT_PATH.write_text("\n".join(lines) + "\n")

# GitHub Actions reads these outputs from stdout/env file wrapper.
print(f"ALERT_COUNT={len(alerts)}")
print(f"REPORT_PATH={REPORT_PATH}")
