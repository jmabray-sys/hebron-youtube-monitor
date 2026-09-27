"""Search pacing regressions for Google's Pacific Time daily quota reset."""
import unittest
from datetime import datetime, timedelta, timezone

from search_budget import PACIFIC, paced_allowance, quota_day_key


class BudgetPacingTests(unittest.TestCase):
    def at(self, h, m=0):
        return datetime(2026, 9, 28, h, m, tzinfo=PACIFIC)

    def test_first_run_does_not_spend_entire_budget(self):
        self.assertEqual(paced_allowance(self.at(0), 0), 2)
        self.assertEqual(paced_allowance(self.at(0, 20), 2), 1)

    def test_midday_spreads_spend(self):
        self.assertEqual(paced_allowance(self.at(12), 47), 0)
        self.assertEqual(paced_allowance(self.at(12), 20), 3)

    def test_last_run_can_use_whole_daily_budget(self):
        self.assertEqual(paced_allowance(self.at(23, 40), 88), 2)
        self.assertEqual(paced_allowance(self.at(23, 40), 90), 0)

    def test_pacific_midnight_key_even_during_utc_next_day(self):
        early_utc = datetime(2026, 9, 28, 2, tzinfo=timezone.utc)
        self.assertEqual(quota_day_key(early_utc), "2026-09-27")

    def test_timezone_conversion_and_disabled_budget(self):
        local = datetime(2026, 9, 28, 2,
                         tzinfo=timezone(timedelta(hours=-5)))
        self.assertEqual(paced_allowance(local, 0), 2)
        self.assertEqual(paced_allowance(self.at(12), 0, daily_limit=0), 0)

    def test_dst_fall_back_uses_25_hour_quota_day(self):
        fall = datetime(2026, 11, 1, 23, 0, tzinfo=PACIFIC)
        self.assertEqual(paced_allowance(fall, 88), 0)
        self.assertEqual(paced_allowance(fall.replace(minute=40), 88), 2)

    def test_dst_spring_forward_uses_23_hour_quota_day(self):
        spring = datetime(2027, 3, 14, 23, 40, tzinfo=PACIFIC)
        self.assertEqual(paced_allowance(spring, 88), 2)

    def test_rejects_naive_timestamp(self):
        with self.assertRaises(ValueError):
            paced_allowance(datetime(2026, 9, 28, 12), 0)
        with self.assertRaises(ValueError):
            quota_day_key(datetime(2026, 9, 28, 12))


if __name__ == "__main__":
    unittest.main()
