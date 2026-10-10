"""Exercises two generate_brief.py failure paths that previously could not
be tested without hitting real Google Sheets:

1. A transaction row with a non-blank, parseable amount but an
   unrecognized status -> build_cash_summary() must raise SafeFailure.
   Subtlety: if the amount were blank/unparseable instead, the row would
   be routed to "unknown_amount" and the status check is never reached
   (see generate_brief.build_cash_summary) -- so the fixture row MUST
   carry a real amount, or this path silently stops being exercised.

2. A sheet whose header doesn't fingerprint as transactions/budget/
   revenue -> detect_role() must raise SafeFailure. No special row is
   needed here: the header alone determines the role, so any wrong set
   of columns reproduces it.

Uses a local HTTP fixture server (tests/fixture_server.py) so no network
access or real spreadsheet is involved, relying on export_csv_url()
preserving the request's own host/path instead of rewriting everything
to docs.google.com.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

import generate_brief  # noqa: E402
from fixture_server import FixtureServer  # noqa: E402

VALID_BUDGET_CSV = (
    "period,category,budget_amount,currency,owner,review_rule,source,source_version\n"
    "2026-01,Insurance,1000,USD,Jane,manual,test-fixture,v1\n"
).encode("utf-8")

VALID_REVENUE_CSV = (
    "date,source,metric,value,currency,source_version\n"
    "2026-01-02,Online,Tuition,500,USD,v1\n"
).encode("utf-8")


def run_main(urls: dict[str, str], target_date: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as out_dir:
        argv = [
            "--transactions-url", urls["transactions"],
            "--budget-url", urls["budget"],
            "--revenue-url", urls["revenue"],
            "--target-date", target_date,
            "--out-dir", out_dir,
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = generate_brief.main(argv)
        return rc, stderr.getvalue()


class BadStatusRowTest(unittest.TestCase):
    def test_non_blank_amount_with_unrecognized_status_is_a_safe_failure(self):
        transactions_csv = (
            "transaction_id,date,account,category,description,amount,currency,"
            "status,source,source_version,amount_status\n"
            "TXN100,2026-01-02,Checking,Insurance,Test bad status,100.00,USD,"
            "voided,test-fixture,v1,ok\n"
        ).encode("utf-8")

        routes = {
            "/t/d/FIXTURE_TXN": ("text/csv", transactions_csv),
            "/b/d/FIXTURE_BUD": ("text/csv", VALID_BUDGET_CSV),
            "/r/d/FIXTURE_REV": ("text/csv", VALID_REVENUE_CSV),
        }
        with FixtureServer(routes) as server:
            urls = {
                "transactions": server.url("/t/d/FIXTURE_TXN"),
                "budget": server.url("/b/d/FIXTURE_BUD"),
                "revenue": server.url("/r/d/FIXTURE_REV"),
            }
            rc, stderr = run_main(urls, "2026-01-02")

        self.assertEqual(rc, 1, stderr)
        self.assertIn("SAFE FAILURE", stderr)
        self.assertIn("TXN100", stderr)
        self.assertIn("unrecognized status", stderr)
        self.assertIn("voided", stderr)

    def test_blank_amount_with_unrecognized_status_does_not_trigger_the_check(self):
        # Sanity check for the subtlety noted in the module docstring: a
        # blank amount routes to unknown_amount *before* the status is
        # ever inspected, so this must NOT raise -- it proves the first
        # test's failure really comes from the status check, not from an
        # unrelated row-parsing error.
        transactions_csv = (
            "transaction_id,date,account,category,description,amount,currency,"
            "status,source,source_version,amount_status\n"
            "TXN101,2026-01-02,Checking,Insurance,Test blank amount,,USD,"
            "voided,test-fixture,v1,blank\n"
        ).encode("utf-8")

        routes = {
            "/t/d/FIXTURE_TXN": ("text/csv", transactions_csv),
            "/b/d/FIXTURE_BUD": ("text/csv", VALID_BUDGET_CSV),
            "/r/d/FIXTURE_REV": ("text/csv", VALID_REVENUE_CSV),
        }
        with FixtureServer(routes) as server:
            urls = {
                "transactions": server.url("/t/d/FIXTURE_TXN"),
                "budget": server.url("/b/d/FIXTURE_BUD"),
                "revenue": server.url("/r/d/FIXTURE_REV"),
            }
            rc, stderr = run_main(urls, "2026-01-02")

        self.assertEqual(rc, 0, stderr)


class RoleMismatchTest(unittest.TestCase):
    def test_header_that_matches_no_known_role_is_a_safe_failure(self):
        # Wrong columns entirely -- no transaction_id/amount/status,
        # budget_amount/period, or metric/value fingerprint. No special
        # row needed; the header alone decides this.
        mismatched_csv = b"name,quantity,price\nWidget,3,9.99\n"

        routes = {
            "/t/d/FIXTURE_TXN": ("text/csv", mismatched_csv),
            "/b/d/FIXTURE_BUD": ("text/csv", VALID_BUDGET_CSV),
            "/r/d/FIXTURE_REV": ("text/csv", VALID_REVENUE_CSV),
        }
        with FixtureServer(routes) as server:
            urls = {
                "transactions": server.url("/t/d/FIXTURE_TXN"),
                "budget": server.url("/b/d/FIXTURE_BUD"),
                "revenue": server.url("/r/d/FIXTURE_REV"),
            }
            rc, stderr = run_main(urls, "2026-01-02")

        self.assertEqual(rc, 1, stderr)
        self.assertIn("SAFE FAILURE", stderr)
        self.assertIn("Could not identify the role", stderr)


if __name__ == "__main__":
    unittest.main()
