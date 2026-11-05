"""Read-only, machine-readable audit of the existing Hebron monitor.

This does not claim to crawl Gmail or social networks. It checks that existing
monitor outputs are structurally valid and exposes gaps for the rebuild.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "Hebron_Uploader_Registry_2026.json"
STATE = ROOT / "state.json"
OUTPUT = ROOT / "audit-results.json"

def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def audit(registry, state, now):
    accounts = registry.get("channel_accounts", [])
    videos = registry.get("video_references", [])
    relationships = registry.get("public_account_relationships", [])
    processed = registry.get("processed_gmail_message_ids", [])
    issues = []
    for key, records in (("channel_accounts", accounts), ("video_references", videos),
                         ("public_account_relationships", relationships)):
        if not isinstance(records, list):
            issues.append(f"{key} must be an array")
    for account in accounts if isinstance(accounts, list) else []:
        if not isinstance(account, dict):
            issues.append("Non-object channel account")
            continue
        if account.get("last_checked_at") and not parse_time(account["last_checked_at"]):
            issues.append(f"Invalid last_checked_at: {account.get('channel_id', 'unknown')}")
        if account.get("last_channel_error") and account.get("last_checked_at") is None:
            # Unresolved does not mean inactive.
            pass
    state_channels = state.get("known_channels", [])
    recent_success = 0
    for channel in state_channels if isinstance(state_channels, list) else []:
        checked = parse_time(channel.get("last_checked_at")) if isinstance(channel, dict) else None
        if checked and 0 <= (now - checked).total_seconds() <= 7200:
            recent_success += 1
    return {
        "generated_at": now.isoformat(),
        "status": "pass" if not issues else "fail",
        "scope": "read_only_repository_integrity_and_check_freshness",
        "not_checked": ["gmail", "tiktok", "instagram", "facebook", "x", "reddit",
                        "txbands", "hornrank", "email_delivery", "live_youtube_api"],
        "counts": {"registry_videos": len(videos) if isinstance(videos, list) else None,
                   "registry_accounts": len(accounts) if isinstance(accounts, list) else None,
                   "registry_relationships": len(relationships) if isinstance(relationships, list) else None,
                   "processed_gmail_ids": len(processed) if isinstance(processed, list) else None,
                   "state_channels_successfully_checked_last_2h": recent_success},
        "issues": issues
    }

def main():
    now = datetime.now(timezone.utc)
    result = audit(json.loads(REGISTRY.read_text(encoding="utf-8")),
                   json.loads(STATE.read_text(encoding="utf-8")), now)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
