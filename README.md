# Hebron YouTube Monitor

Monitors YouTube for likely public uploads of Hebron High School Band's 2026 show, **Somewhere in Time**, with emphasis on catching newly uploaded or vaguely titled videos quickly.

## What it does

- Uses the official YouTube Data API v3.
- Rotates through a configurable search matrix to stay within the post-June-2026 search quota model.
- Tracks known uploader channels and checks their upload playlists using low-cost API calls.
- Scores candidates based on Hebron/show/event/leak fingerprints and uses explicit-identity triage to separate alerts, needs-review clips, and unrelated content.
- Persists seen video IDs in `state.json` so the same video is not repeatedly reported.
- Seeds the known confirmed Parent Preview leak:
  - `VQyGH1E8Z48`
  - “Hebron 2026 Exposed Full Show leak”
  - Sept. 19, 2026 Parent Preview at Hebron HS Stadium
- Emits a Markdown report as a GitHub Actions artifact and job summary.
- Optionally opens a GitHub Issue when a strong new candidate is found.

## Setup

1. In Google Cloud, enable **YouTube Data API v3**.
2. Create an API key.
3. In this repository, go to **Settings → Secrets and variables → Actions → New repository secret**.
4. Create:
   - `YOUTUBE_API_KEY` = your API key
5. Optional repository variables:
   - `ALERT_THRESHOLD` (default `7`)
   - `SEARCHES_PER_RUN` (default `3`)
   - `LOOKBACK_HOURS` (default `72`)
   - `CREATE_ISSUES` (default `true`)
6. Run **Actions → Hebron YouTube Monitor → Run workflow** once manually.

The scheduled workflow runs every 20 minutes. Search calls are **paced across the Pacific Time quota day** instead of spending the allowance in the morning. The software cap is 90 search calls per Pacific day, below the post-June-2026 default Google search.list bucket of 100 calls/day; Google resets the bucket at midnight Pacific Time, including daylight saving. When searches are unavailable, confirmed uploader playlist checks still run. See `search_budget.py` and `test_search_budget.py` for the quota-day and daylight-saving tests.

## Why channel monitoring matters

YouTube search can lag behind actual public uploads. Once a channel is identified as relevant, its uploads playlist is checked directly. This can surface a new video even if keyword search has not indexed it yet.

## Files

- `monitor.py` — monitor logic
- `candidate_rules.py` / `test_candidate_rules.py` — confirmed-video and false-positive regression cases
- `search_budget.py` / `test_search_budget.py` — Pacific quota-day pacing and daylight-saving tests
- `config.json` — fingerprints, events, search queries, known videos/channels
- `state.json` — persistent state, seen video IDs, quota ledger
- `.github/workflows/monitor.yml` — scheduled GitHub Actions workflow
- `requirements.txt` — Python dependencies

## Notes

This project only checks publicly accessible YouTube metadata through the official API. It does not bypass privacy settings, access private/unlisted videos without a known URL, or analyze audio/video content directly.
