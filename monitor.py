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
WATCH_THRESHOLD = int(os.environ.get("WATCH_THRESHOLD", "4"))
SEARCHES_PER_RUN = int(os.environ.get("SEARCHES_PER_RUN", "3"))
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "96"))
DAILY_SEARCH_BUDGET = int(os.environ.get("DAILY_SEARCH_BUDGET", "90"))
MAX_WATCH_CHANNELS = int(os.environ.get("MAX_WATCH_CHANNELS", "40"))

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
    for key in list(ledger.keys()):
        if key < (now - timedelta(days=7)).strftime("%Y-%m-%d"):
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
        candidates = [event.get("name",""), event.get("location",""), event.get("opponent","")]
        if any(normalize(x) and normalize(x) in haystack for x in candidates):
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
    ).execute()
    spend_search()
    return [x["id"]["videoId"] for x in resp.get("items", []) if x.get("id", {}).get("videoId")]

def get_uploads_playlist(channel_id):
    resp = youtube.channels().list(part="contentDetails,snippet", id=channel_id).execute()
    items = resp.get("items", [])
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"] if items else None

def latest_channel_upload_ids(channel_id, max_results=30):
    playlist_id = get_uploads_playlist(channel_id)
    if not playlist_id: return []
    resp = youtube.playlistItems().list(
        part="contentDetails,snippet", playlistId=playlist_id, maxResults=max_results
    ).execute()
    return [x["contentDetails"]["videoId"] for x in resp.get("items", [])]

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

def priority_queries():
    # Compact OR searches buy broader discovery per search.list call.
    return config.get("priority_queries", [])

def select_queries():
    priority = priority_queries()
    rotating = config["search_queries"] + event_queries()
    available = min(SEARCHES_PER_RUN, search_budget_remaining())
    if available <= 0: return []
    selected = []
    # Every fourth run spend one slot on a relevance-ranked query to catch older/index-late uploads.
    run_count = int(state.get("run_count", 0))
    if priority:
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

# Improvement 1: learn uploader channels from every confirmed seed before discovery.
seed_ids = [x["video_id"] for x in config.get("confirmed_videos", [])]
seed_details = fetch_video_details(seed_ids)
for video in seed_details:
    s = video.get("snippet", {})
    add_watch_channel(s.get("channelId"), s.get("channelTitle",""), video["id"],
                      "uploader of confirmed Hebron video", "confirmed")

known_channels = {x["channel_id"]: x for x in state.get("known_channels", []) if x.get("channel_id")}
known_channel_ids = set(known_channels)
candidate_ids = set(seed_ids)
searches_run = []

# Improvement 2: adaptive discovery: broad OR queries + event/opponent-side searches +
# periodic relevance-ranked searches for uploads that were indexed late.
for query, order, hours in select_queries():
    try:
        candidate_ids.update(search_youtube(query, order=order, lookback_hours=hours))
        searches_run.append(f"{query} [{order}]")
    except Exception as exc:
        print(f"Search failed for {query!r}: {exc}", file=sys.stderr)

# Improvement 3: channel graph. Confirmed AND medium-confidence discovery channels are
# monitored through uploads playlists, bypassing search-index delay on future uploads.
for channel_id in list(known_channel_ids):
    try:
        candidate_ids.update(latest_channel_upload_ids(channel_id))
    except Exception as exc:
        print(f"Channel check failed for {channel_id}: {exc}", file=sys.stderr)

details = fetch_video_details(sorted(candidate_ids))
seen = set(state.get("seen_video_ids", []))
alerts, watch_additions, all_scored = [], [], []

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

    # Learn channels earlier than the alert threshold. A moderately relevant result can
    # reveal a spectator/uploader whose NEXT upload is the vaguely titled one we need.
    # Only learn a new channel when the evidence is Hebron-specific. Generic marching
    # videos found through opponent/venue searches must never create a channel explosion.
    metadata = normalize(" ".join([row["title"], s.get("description",""), " ".join(s.get("tags", []))]))
    strong_band_context = any(normalize(t) in metadata for t in config.get("strong_band_terms", []))
    school_context = any(normalize(t) in metadata for t in config.get("school_identity_terms", []))
    negative_context = any(normalize(t) in metadata for t in config.get("negative_terms", []))
    repertoire_context = any(normalize(t) in metadata for t in config.get("repertoire_terms", []))
    hebron_specific = (
        "somewhere in time" in metadata or repertoire_context or
        (("hebron" in metadata) and strong_band_context and school_context)
    ) and not negative_context
    if score >= WATCH_THRESHOLD and (vid in confirmed_ids or hebron_specific):
        confidence = "confirmed" if vid in confirmed_ids else "candidate"
        if add_watch_channel(row["channel_id"], row["channel"], vid,
                             f"video scored {score}: {', '.join(reasons)}", confidence):
            watch_additions.append(row)
            known_channel_ids.add(row["channel_id"])

    # Alerts require Hebron-specific evidence, or a watched channel plus another
    # corroborating signal. This keeps broad discovery broad without making it noisy.
    corroborated_watched = (row["channel_id"] in known_channel_ids and
                            score >= ALERT_THRESHOLD + 2 and strong_band_context and not negative_context)
    if score >= ALERT_THRESHOLD and vid not in seen and (hebron_specific or corroborated_watched):
        alerts.append(row)

seen.update(v["id"] for v in details)
state["seen_video_ids"] = sorted(seen)
state["last_run"] = now.isoformat()
state["run_count"] = int(state.get("run_count", 0)) + 1
STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")

lines = [
    "# Hebron YouTube Monitor Report","",
    f"- Run: {now.isoformat()}",
    f"- Search calls used today: {state['daily_search_ledger'].get(today_key(), 0)} / {DAILY_SEARCH_BUDGET}",
    f"- Searches this run: {len(searches_run)}",
    f"- Watched relevant channels: {len(state.get('known_channels', []))}",
    f"- New watch channels learned: {len(watch_additions)}",
    f"- New alerts: {len(alerts)}",
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
                  f"- Reasons: {', '.join(a['reasons']) or 'none'}",""]
else:
    lines += ["## New high-confidence candidates","","None.",""]

REPORT_PATH.write_text("\n".join(lines) + "\n")
print(f"ALERT_COUNT={len(alerts)}")
print(f"WATCH_ADDITIONS={len(watch_additions)}")
print(f"REPORT_PATH={REPORT_PATH}")
