# YouTube Data API search quota extension — application draft

**Official instructions:** https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits

**Requested allocation:** 300 `search.list` calls per Pacific Time quota day for this project's existing YouTube Data API access (standard allocation: 100/day). Request no change to `videos.insert` (unused) or the separate bucket for `playlistItems.list`, `channels.list`, and `videos.list`.

**Important:** Google must review and approve the request. The monitor remains capped at 90 searches per Pacific day until approval is confirmed in the project's actual quota dashboard. After approval of 300, set the `DAILY_SEARCH_BUDGET` GitHub Actions repository variable to **285** to retain a safety margin; keep `SEARCHES_PER_RUN=3`.

## Project purpose

A private, noncommercial, volunteer-operated monitoring utility for Hebron High School Band's 2026 “Somewhere in Time” marching program. It searches publicly available YouTube performance-related metadata to identify videos for human review by band representatives, such as when a posting may involve protected show-design material. The utility does not upload videos, bypass access controls, scrape private accounts, make automated legal claims, submit takedowns, or determine that a video is infringing.

Repository: https://github.com/jmabray-sys/hebron-youtube-monitor

## Why 300 search.list calls/day

The monitor checks verified uploader upload playlists on a nominal ten-minute schedule using lower-cost, separately budgeted `channels.list` and `playlistItems.list` calls. Broader `search.list` queries remain necessary to discover **new** public uploaders who haven't appeared in the project's confirmed channels, especially near competitions. With up to 144 scheduled runs per day, approximately two discovery searches per run (288/day) provide broad coverage of event/venue names, alternate captions and regional band terms throughout the day. A 300/day allocation enables this pace and a small burst margin; the code independently paces and caps searches so it does not consume the daily allowance early.

## Steps taken to minimize API calls

- Once a confirmed video's public uploader channel is known, monitor its uploads playlist directly rather than re-running expensive general searches for that account.
- Cache each channel's uploads playlist ID; query only the newest 20 entries and retrieve details only for unseen recent uploads.
- Poll confirmed uploader channels on each run; rotate lower-confidence discovered channels less frequently.
- Track seen video IDs and avoid duplicate review alerts. Separate strong matches from ambiguous clips needing a human check.
- Back off unavailable upload playlists for 24 hours rather than repeatedly retrying unsuccessful calls.
- Keep a software limit below the project's actual approved allocation; no additional Cloud projects or keys to bypass quotas.

## Access and compliance

Only metadata and links for publicly available videos are processed: video/channel IDs, public titles/descriptions, publication timestamps and URLs. The tool stores a bounded working set of watched channels and deduplication identifiers in the GitHub repository. Humans decide whether a candidate is relevant and whether any separate rights action is appropriate. Complete Google's actual compliance questionnaire accurately; do not claim a passed audit or an existing 300-call allowance before approval.

## Owner-supplied information required to submit

- Exact Google Cloud project ID **and project number** with the existing `YOUTUBE_API_KEY` configured in GitHub; never paste the API key into the form or repository.
- Google account authorized to request quota for that project and the applicant's contact details.
- Actual quota and usage shown in Google Cloud Console under APIs & Services → YouTube Data API v3 → Quotas.
- Answers to any current form-specific questions, screenshots, policies, and requested usage examples.

The available GitHub connection can prepare this request and update code, but it does **not** grant Google Cloud form-submission access. The project owner must review and submit Google's official audit/quota form.