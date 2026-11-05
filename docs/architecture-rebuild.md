# Hebron monitor architecture rebuild

## Safety and rollout
This branch is additive and does not modify `state.json`, the curated uploader registry, existing classifications, or production monitoring workflow. Merge only after tests and workflow review. The scheduled audit will become active on the default branch after merge.

## Existing production engine
`.github/workflows/monitor.yml` runs every ten minutes, uses the official YouTube Data API, persists `state.json`, and syncs successful channel checks to the curated registry. GitHub Actions cron is best effort and may be delayed. The existing monitor does **not** crawl TikTok, Instagram, Gmail, or other networks.

## Source of truth
The GitHub curated registry is authoritative for user classifications, uploader relationships, and processed submission IDs. `state.json` is operational YouTube state, not a replacement for curated evidence. Library copies are backups, not simultaneous writers.

## Phase 1: verified
The independent audit validates repository structure and distinguishes recently recorded channel successes from missing checks. It produces an artifact without changing any evidence. It does not independently verify that an API call succeeded.

## Phase 2: implementation needed
- Add structured per-channel API receipts to the YouTube monitor, with actual HTTP success/error, attempted_at, completed_at, and channel ID. Never advance successful timestamps on 404s.
- Implement Gmail intake as a separately credentialed worker, with per-message idempotency and verified label/read/archive results.
- Implement a notification outbox keyed by canonical video ID and recipient, with delivery attempt and provider message ID. A sent-email search is a secondary check, not the sole idempotency mechanism.
- Add adapters for other platforms only where reliable permitted access exists. Report inaccessible feeds as coverage gaps.
- Add a watchdog that detects delayed or missed runs and retries without overlapping execution.
- Test interrupted writes, partial Gmail processing, duplicate clips, and per-recipient delivery failures before enabling outbound mail.

## Acceptance gates
No lost curated evidence; all existing regression tests pass; failed channels remain unresolved; every workstream emits a machine-readable status; repeated runs do not duplicate notifications; simulated partial failures recover; no claims of exhaustive social coverage without actual inventory receipts.
