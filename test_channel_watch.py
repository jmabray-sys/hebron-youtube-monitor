"""Channel-first discovery regression tests."""
import unittest
from datetime import datetime, timedelta, timezone
from channel_watch import select_due_channels, select_new_upload_ids, parse_time

NOW = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)

class ChannelWatchTests(unittest.TestCase):
    def test_confirmed_channels_checked_every_run(self):
        channels = [{"channel_id": "B", "confidence": "confirmed", "last_checked_at": NOW.isoformat()},
                    {"channel_id": "A", "confidence": "confirmed", "last_checked_at": NOW.isoformat()}]
        self.assertEqual([ch["channel_id"] for ch in select_due_channels(channels, NOW)], ["A", "B"])

    def test_candidate_checks_are_due_and_prioritized(self):
        channels = [{"channel_id": "known", "confidence": "confirmed"},
                    {"channel_id": "stale", "confidence": "candidate",
                     "last_checked_at": (NOW - timedelta(hours=2)).isoformat()},
                    {"channel_id": "fresh", "confidence": "candidate",
                     "last_checked_at": (NOW - timedelta(minutes=20)).isoformat()},
                    {"channel_id": "never", "confidence": "candidate"}]
        self.assertEqual([ch["channel_id"] for ch in select_due_channels(channels, NOW)],
                         ["known", "never", "stale"])

    def test_candidate_checks_bounded(self):
        channels = [{"channel_id": str(i), "confidence": "candidate"} for i in range(20)]
        self.assertEqual(len(select_due_channels(channels, NOW, candidate_batch=6)), 6)

    def test_only_recent_unseen_uploads_get_metadata_calls(self):
        item = lambda vid, time: {"contentDetails": {"videoId": vid, "videoPublishedAt": time}}
        recent = (NOW - timedelta(hours=2)).isoformat()
        old = (NOW - timedelta(days=30)).isoformat()
        items = [item("NEW", recent), item("SEEN", recent), item("SEED", recent),
                 item("OLD", old), item("UNKNOWN", None)]
        self.assertEqual(select_new_upload_ids(items, {"SEEN"}, {"SEED"}, NOW),
                         ["NEW", "UNKNOWN"])

    def test_invalid_date_does_not_crash(self):
        self.assertIsNone(parse_time("bad-date"))

if __name__ == "__main__":
    unittest.main()
