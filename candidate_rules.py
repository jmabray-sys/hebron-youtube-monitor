"""Explainable, conservative triage for Hebron 2026 YouTube candidates.

Only explicit Hebron performance evidence earns an automatic alert. Uploads from
verified sources with vague titles remain review candidates, never auto-confirmed.
"""
import re


def has_phrase(text, phrase):
    phrase = (phrase or "").strip()
    if not phrase:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])",
                     text or "", re.IGNORECASE) is not None


BAND_SIGNALS = (
    "marching band", "marching", "halftime", "drum major", "color guard",
    "colorguard", "band", "full show", "full run", "field show",
    "run through", "run-through", "parent preview",
)
DIRECT_IDENTITY = (
    "hebron band", "hebron marching", "hebron hs marching",
    "hebron high school marching", "hebron hs band",
    "hebron high school band",
)


def triage_video(snippet, config, score, confirmed_channel_ids,
                 recent_event_terms=(), alert_threshold=7, watch_threshold=4):
    title = snippet.get("title", "") or ""
    description = snippet.get("description", "") or ""
    tags = " ".join(snippet.get("tags") or [])
    metadata = " ".join([title, description, tags])
    channel_id = snippet.get("channelId", "")
    confirmed_uploader = channel_id in confirmed_channel_ids
    reasons = []

    if any(has_phrase(metadata, term) for term in config.get("negative_terms", [])):
        return "ignore", ["unrelated subject / excluded topic"]
    if any(has_phrase(title, term) for term in config.get("other_school_terms", [])) and not has_phrase(title, "hebron"):
        return "ignore", ["different school explicitly named in title"]

    hebron_title = has_phrase(title, "hebron")
    title_band = any(has_phrase(title, term) for term in BAND_SIGNALS)
    body_hebron_band = any(has_phrase(description, term) for term in DIRECT_IDENTITY)
    show_title = has_phrase(metadata, "somewhere in time")
    explicit_identity = any(has_phrase(metadata, term) for term in DIRECT_IDENTITY)
    # A football game or stream containing Hebron's name is not itself band footage.
    football_only = has_phrase(title, "football") and not title_band
    event_match = any(has_phrase(metadata, term) for term in recent_event_terms)
    body_band = any(has_phrase(metadata, term) for term in BAND_SIGNALS)

    if football_only:
        return "ignore", ["football-only title; no explicit band footage"]

    if (hebron_title and title_band) or body_hebron_band or (
            hebron_title and show_title):
        reasons.append("explicit Hebron performance identity")
        if score >= alert_threshold:
            return "alert", reasons
        return "review", reasons + ["requires higher corroboration score"]

    if confirmed_uploader and (event_match or body_band or hebron_title):
        return "review", ["previously confirmed uploader; video content unverified"]

    if show_title and body_band:
        return "review", ["show title and band context without Hebron confirmation"]

    if score >= watch_threshold and (
            (has_phrase(metadata, "hebron") and body_band) or
            (event_match and body_band)):
        return "review", ["plausible performance, insufficient Hebron evidence"]

    if explicit_identity and score >= watch_threshold:
        return "review", ["Hebron identity requires performance verification"]

    return "ignore", ["insufficient Hebron performance evidence"]
