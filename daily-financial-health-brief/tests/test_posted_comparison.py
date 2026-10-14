"""Covers the Leaderboard challenge's "daily posted totals and their signed
change" requirement: comparing --target-date's Posted cash total against a
--comparison-date.

Per the Work Sim interview, the Finance and Operations Manager strictly uses
the exact dates given in each request -- never an inferred or defaulted
one -- for financial consistency and alignment with the review period. So:

- --comparison-date is a required, explicit CLI argument with no silent
  default. Missing it is a SafeFailure, exercised here end-to-end via the
  local fixture server (same pattern as tests/test_untestable_paths.py).
- A comparison date with zero Transaction Ledger rows does NOT fail the
  run -- it doesn't corrupt anything else in the report, so it's flagged
  ("no comparison data available") instead. Covered as a direct unit test
  against build_posted_comparison().
- The signed change itself (target total - comparison total) is covered
  as a direct unit test too.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

import generate_brief  # noqa: E402
from fixture_server import FixtureServer  # noqa: E402

TRANSACTIONS_CSV = (
    "transaction_id,date,account,category,description,amount,currency,"
    "status,source,source_version,amount_status\n"
    "TX-1,2026-01-02,Checking,Insurance,Target day,1000.00,USD,"
    "posted,test-fixture,v1,confirmed\n"
).encode("utf-8")

BUDGET_CSV = (
    "period,category,budget_amount,currency,owner,review_rule,source,source_version\n"
    "2026-01,Insurance,1000,USD,Jane,manual,test-fixture,v1\n"
).encode("utf-8")

REVENUE_CSV = (
    "date,source,metric,value,currency,source_version\n"
    "2026-01-02,Online,Tuition,500,USD,v1\n"
).encode("utf-8")


def run_main(extra_args: list[str]) -> tuple[int, str]:
    routes = {
        "/t/d/FIXTURE_TXN": ("text/csv", TRANSACTIONS_CSV),
        "/b/d/FIXTURE_BUD": ("text/csv", BUDGET_CSV),
        "/r/d/FIXTURE_REV": ("text/csv", REVENUE_CSV),
    }
    with FixtureServer(routes) as server, tempfile.TemporaryDirectory() as out_dir:
        argv = [
            "--transactions-url", server.url("/t/d/FIXTURE_TXN"),
            "--budget-url", server.url("/b/d/FIXTURE_BUD"),
            "--revenue-url", server.url("/r/d/FIXTURE_REV"),
            "--target-date", "2026-01-02",
            "--out-dir", out_dir,
            *extra_args,
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = generate_brief.main(argv)
        report_path = os.path.join(out_dir, "report.md")
        report = ""
        if os.path.exists(report_path):
            with open(report_path, encoding="utf-8") as handle:
                report = handle.read()
        return rc, stderr.getvalue(), report


class RequiredArgumentTest(unittest.TestCase):
    def test_missing_comparison_date_is_a_safe_failure(self):
        rc, stderr, report = run_main([])

        self.assertEqual(rc, 1, stderr)
        self.assertIn("SAFE FAILURE", stderr)
        self.assertIn("--comparison-date is required", stderr)
        self.assertEqual(report, "")

    def test_comparison_date_provided_lets_the_run_complete(self):
        rc, stderr, report = run_main(["--comparison-date", "2026-01-01"])

        self.assertEqual(rc, 0, stderr)
        self.assertIn("## Daily Posted Total Comparison", report)


class BuildPostedComparisonTest(unittest.TestCase):
    def test_comparison_date_with_zero_rows_is_flagged_not_failed(self):
        all_transactions = [
            {"transaction_id": "TX-1", "date": "2026-01-02", "status": "posted",
             "amount": "1000.00", "category": "Insurance", "amount_status": "confirmed"},
        ]
        result = generate_brief.build_posted_comparison(
            all_transactions, Decimal("1000.00"), dt.date(2026, 1, 1)
        )

        self.assertFalse(result["comparison_available"])
        self.assertIsNone(result["comparison_total"])
        self.assertIsNone(result["signed_change"])

    def test_signed_change_is_target_minus_comparison(self):
        all_transactions = [
            {"transaction_id": "TX-1", "date": "2026-01-02", "status": "posted",
             "amount": "1000.00", "category": "Insurance", "amount_status": "confirmed"},
            {"transaction_id": "TX-0", "date": "2026-01-01", "status": "posted",
             "amount": "400.00", "category": "Insurance", "amount_status": "confirmed"},
        ]
        result = generate_brief.build_posted_comparison(
            all_transactions, Decimal("1000.00"), dt.date(2026, 1, 1)
        )

        self.assertTrue(result["comparison_available"])
        self.assertEqual(result["comparison_total"], Decimal("400.00"))
        self.assertEqual(result["signed_change"], Decimal("600.00"))

    def test_negative_signed_change_when_comparison_day_was_higher(self):
        all_transactions = [
            {"transaction_id": "TX-1", "date": "2026-01-02", "status": "posted",
             "amount": "400.00", "category": "Insurance", "amount_status": "confirmed"},
            {"transaction_id": "TX-0", "date": "2026-01-01", "status": "posted",
             "amount": "1000.00", "category": "Insurance", "amount_status": "confirmed"},
        ]
        result = generate_brief.build_posted_comparison(
            all_transactions, Decimal("400.00"), dt.date(2026, 1, 1)
        )

        self.assertEqual(result["signed_change"], Decimal("-600.00"))

    def test_negative_posted_amounts_on_the_comparison_date_are_flagged_as_credits(self):
        # Mirrors how Cash Summary labels negative Posted amounts as
        # Credit/Correction on the target date -- the comparison date
        # deserves the same labeling, not just a correct total.
        all_transactions = [
            {"transaction_id": "TX-1", "date": "2026-01-02", "status": "posted",
             "amount": "1000.00", "category": "Insurance", "amount_status": "confirmed"},
            {"transaction_id": "TX-CREDIT-1", "date": "2026-01-01", "status": "posted",
             "amount": "-125.50", "category": "Facilities", "amount_status": "confirmed"},
            {"transaction_id": "TX-CREDIT-2", "date": "2026-01-01", "status": "posted",
             "amount": "-180.00", "category": "Facilities", "amount_status": "confirmed"},
            {"transaction_id": "TX-POSITIVE", "date": "2026-01-01", "status": "posted",
             "amount": "500.00", "category": "Facilities", "amount_status": "confirmed"},
        ]
        result = generate_brief.build_posted_comparison(
            all_transactions, Decimal("1000.00"), dt.date(2026, 1, 1)
        )

        self.assertEqual(result["comparison_total"], Decimal("194.50"))  # 500 - 125.50 - 180
        self.assertEqual(set(result["comparison_credit_ids"]), {"TX-CREDIT-1", "TX-CREDIT-2"})

    def test_bad_status_on_comparison_date_still_raises_safe_failure(self):
        # Consistency with build_cash_summary's own rule: an unrecognized
        # status blocks the run regardless of which date it's on.
        all_transactions = [
            {"transaction_id": "TX-0", "date": "2026-01-01", "status": "voided",
             "amount": "400.00", "category": "Insurance", "amount_status": "confirmed"},
        ]
        with self.assertRaises(generate_brief.SafeFailure):
            generate_brief.build_posted_comparison(
                all_transactions, Decimal("1000.00"), dt.date(2026, 1, 1)
            )


if __name__ == "__main__":
    unittest.main()
