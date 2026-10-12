"""Covers the "collected revenue against outstanding balances" requirement:
two independent as-of comparisons -- collected_revenue and
outstanding_balance -- target-date vs. comparison-date, structured exactly
like build_posted_comparison() but for the Revenue Snapshot, and never
combined into a single relationship or ratio between the two metrics.

Per the user's explicit reasoning:

- The Revenue Snapshot updates sparsely by design (not every day, unlike
  the Transaction Ledger), so a missing same-day entry is expected, not an
  error.
- Falling back to the most recent real observation -- clearly labeled with
  its own date -- is NOT the same as assuming zero for an unknown amount:
  one is a real (if stale) number, the other has no factual basis. So this
  fallback is allowed here even though assuming zero never is elsewhere.
- If there's no observation at all on or before the requested date, that's
  flagged as unavailable, not a failure (consistent with
  build_posted_comparison()'s zero-row handling).
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from generate_brief import build_revenue_comparison, most_recent_revenue_observation  # noqa: E402


def revenue_row(date: str, metric: str, value: str) -> dict:
    return {"date": date, "source": "tuition-system", "metric": metric, "value": value,
            "currency": "USD", "source_version": "v1"}


REVENUE_ROWS = [
    revenue_row("2026-08-03", "collected_revenue", "21000"),
    revenue_row("2026-08-03", "outstanding_balance", "6000"),
    revenue_row("2026-08-05", "collected_revenue", "22000"),
    revenue_row("2026-08-05", "outstanding_balance", "5650"),
    revenue_row("2026-08-07", "collected_revenue", "23100"),
    revenue_row("2026-08-07", "outstanding_balance", "5200"),
    revenue_row("2026-08-10", "collected_revenue", "24600"),
    revenue_row("2026-08-10", "outstanding_balance", "4700"),
    revenue_row("2026-08-11", "collected_revenue", "25100"),
    revenue_row("2026-08-11", "outstanding_balance", "4300"),
]


class MostRecentRevenueObservationTest(unittest.TestCase):
    def test_exact_date_match_is_used_directly(self):
        result = most_recent_revenue_observation(REVENUE_ROWS, "collected_revenue", dt.date(2026, 8, 11))
        self.assertEqual(result, (dt.date(2026, 8, 11), Decimal("25100")))

    def test_missing_date_falls_back_to_most_recent_prior_observation(self):
        # 2026-08-09 has no Revenue Snapshot row; the most recent real one is 08-07.
        result = most_recent_revenue_observation(REVENUE_ROWS, "collected_revenue", dt.date(2026, 8, 9))
        self.assertEqual(result, (dt.date(2026, 8, 7), Decimal("23100")))

    def test_date_before_the_earliest_observation_is_unavailable(self):
        result = most_recent_revenue_observation(REVENUE_ROWS, "collected_revenue", dt.date(2026, 8, 1))
        self.assertIsNone(result)

    def test_blank_value_on_a_date_is_skipped_like_a_missing_row(self):
        rows = REVENUE_ROWS + [revenue_row("2026-08-12", "collected_revenue", "")]
        result = most_recent_revenue_observation(rows, "collected_revenue", dt.date(2026, 8, 12))
        self.assertEqual(result, (dt.date(2026, 8, 11), Decimal("25100")))


class BuildRevenueComparisonTest(unittest.TestCase):
    def test_exact_dates_are_two_independent_comparisons(self):
        result = build_revenue_comparison(REVENUE_ROWS, dt.date(2026, 8, 11), dt.date(2026, 8, 10))

        self.assertEqual(set(result), {"collected_revenue", "outstanding_balance"})

        collected = result["collected_revenue"]
        self.assertEqual(collected["target_as_of"], dt.date(2026, 8, 11))
        self.assertEqual(collected["target_value"], Decimal("25100"))
        self.assertEqual(collected["comparison_as_of"], dt.date(2026, 8, 10))
        self.assertEqual(collected["comparison_value"], Decimal("24600"))
        self.assertEqual(collected["signed_change"], Decimal("500"))

        outstanding = result["outstanding_balance"]
        self.assertEqual(outstanding["target_value"], Decimal("4300"))
        self.assertEqual(outstanding["comparison_value"], Decimal("4700"))
        self.assertEqual(outstanding["signed_change"], Decimal("-400"))

    def test_dates_without_an_entry_use_labeled_fallback_and_still_compute_change(self):
        # 2026-08-09 -> falls back to 08-07; 2026-08-06 -> falls back to 08-05.
        result = build_revenue_comparison(REVENUE_ROWS, dt.date(2026, 8, 9), dt.date(2026, 8, 6))

        collected = result["collected_revenue"]
        self.assertEqual(collected["target_as_of"], dt.date(2026, 8, 7))
        self.assertEqual(collected["comparison_as_of"], dt.date(2026, 8, 5))
        self.assertEqual(collected["signed_change"], Decimal("1100"))  # 23100 - 22000

    def test_unavailable_date_yields_no_signed_change_not_a_failure(self):
        result = build_revenue_comparison(REVENUE_ROWS, dt.date(2026, 8, 11), dt.date(2026, 8, 1))

        collected = result["collected_revenue"]
        self.assertIsNone(collected["comparison_as_of"])
        self.assertIsNone(collected["comparison_value"])
        self.assertIsNone(collected["signed_change"])
        # The other metric and the target side are unaffected.
        self.assertEqual(collected["target_value"], Decimal("25100"))


if __name__ == "__main__":
    unittest.main()
