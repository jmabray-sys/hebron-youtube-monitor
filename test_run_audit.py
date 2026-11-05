import unittest
from datetime import datetime, timezone
from run_audit import audit

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
        self.registry = {"channel_accounts": [{"channel_id": "A", "last_checked_at": None,
            "last_channel_error": "Uploads playlist HTTP 404"}],
            "video_references": [{"video_id": "known"}],
            "uploader_relationships": [], "processed_gmail_message_ids": ["mail1"]}
        self.state = {"known_channels": [{"channel_id": "A", "last_checked_at": None}]}

    def test_unresolved_channel_is_not_failure_or_success(self):
        result = audit(self.registry, self.state, self.now)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["counts"]["state_channels_successfully_checked_last_2h"], 0)

    def test_invalid_timestamp_fails(self):
        self.registry["channel_accounts"][0]["last_checked_at"] = "not-a-time"
        self.assertEqual(audit(self.registry, self.state, self.now)["status"], "fail")

    def test_successful_recent_check_counted(self):
        self.state["known_channels"][0]["last_checked_at"] = "2026-11-05T15:30:00Z"
        self.assertEqual(audit(self.registry, self.state, self.now)["counts"]
                         ["state_channels_successfully_checked_last_2h"], 1)

    def test_future_check_not_counted(self):
        self.state["known_channels"][0]["last_checked_at"] = "2026-11-05T17:30:00Z"
        self.assertEqual(audit(self.registry, self.state, self.now)["counts"]
                         ["state_channels_successfully_checked_last_2h"], 0)

if __name__ == "__main__":
    unittest.main()
