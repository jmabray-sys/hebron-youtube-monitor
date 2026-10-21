"""Sync verified GitHub YouTube channel checks into the curated uploader registry.

Only state.known_channels is read. No classifications, video IDs, uploader
relationships, or non-YouTube records are created, removed, or rewritten.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"
REGISTRY = ROOT / "Hebron_Uploader_Registry_2026.json"

def parse(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def main():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    channels = {c.get("channel_id"): c for c in state.get("known_channels", [])
                if c.get("channel_id")}
    changed = 0
    for account in registry.get("channel_accounts", []):
        if account.get("platform", "").lower() != "youtube":
            continue
        source = channels.get(account.get("channel_id"))
        if not source:
            continue
        old = parse(account.get("last_checked_at"))
        new = parse(source.get("last_checked_at"))
        # The monitor sets this field only after playlistItems.list succeeds.
        if new and (not old or new > old):
            account["last_checked_at"] = source["last_checked_at"]
            changed += 1
        # Preserve unresolved playlist errors and retry metadata; never label
        # an inaccessible channel as inactive or successfully checked.
        for field in ("next_retry_at", "last_channel_error"):
            if field in source and source[field] != account.get(field):
                account[field] = source[field]
                changed += 1
            elif field not in source and field in account:
                del account[field]
                changed += 1
    if changed:
        # Avoid touching curated timestamps, classifications and source notes.
        REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    print(f"Registry fields updated: {changed}")
    print(f"Uploader accounts: {len(registry.get('channel_accounts', []))}")
    print(f"Video references: {len(registry.get('video_references', []))}")
    return changed

if __name__ == "__main__":
    main()
