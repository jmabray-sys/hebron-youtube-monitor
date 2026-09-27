"""Regression tests for distributing YouTube API searches across the day."""
import unittest
from datetime import datetime, timedelta, timezone

from search_budget import paced_allowance


class BudgetPacingTests(unittest.TestCase):
    def at(self, h, m=0):
        return datetime(2026, 9, 28, h, m, tzinfo=timezone.utc)

    def test_first_run_does_not_spend_entire_budget(self):
        self.assertEqual(paced_allowance(self.at(0), 0), 2)
        self.assertEqual(paced_allowance(self.at(0, 20), 2), 1)

    def test_midday_spreads_spend(self):
        self.assertEqual(paced_allowance(self.at(12), 47), 0)
        self.assertEqual(paced_allowance(self.at(12), 20), 3)

    def test_last_run_can_use_whole_daily_budget(self):
        self.assertEqual(paced_allowance(self.at(23, 40), 88), 2)
        self.assertEqual(paced_allowance(self.at(23, 40), 90), 0)

    def test_utc_time_and_disabled_budget(self):
        local = datetime(2026, 9, 27, 19, 0, tzinfo=timezone(timedelta(hours=-5)))
        self.assertEqual(paced_allowance(local, 0), 2)
        self.assertEqual(paced_allowance(self.at(12), 0, daily_limit=0), 0)

    def test_rejects_naive_timestamp(self):
        with self.assertRaises(ValueError):
            paced_allowance(datetime(2026, 9, 28, 12), 0)


if __name__ == "__main__":
    unittest.main()
