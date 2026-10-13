"""Covers two gaps identified in generate_brief.py's business logic:

1. amount_status mismatch: the Transaction Ledger carries an amount_status
   column alongside amount, but the script used to determine known/unknown
   purely by trying to parse amount, ignoring amount_status entirely. If the
   two signals ever disagreed, the parse-based result silently won. Now any
   disagreement is treated as unknown (never trusting either side alone) and
   is excluded from both cash totals and MTD budget spend.

2. Orphan category: a department with real posted spend but no matching
   Budget Targets row for the period used to vanish from the report with no
   trace. build_budget_variances() now also returns the orphaned categories
   so they can be surfaced in their own report section instead of silently
   dropped.

These are pure business-logic checks against build_cash_summary() and
build_budget_variances() directly -- no network or fixture server involved.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from generate_brief import build_budget_variances, build_cash_summary  # noqa: E402


def make_txn(**overrides) -> dict:
    txn = {
        "transaction_id": "TX-DEFAULT",
        "date": "2026-01-02",
        "account": "Checking",
        "category": "Insurance",
        "description": "Test row",
        "amount": "500.00",
        "currency": "USD",
        "status": "posted",
        "source": "test",
        "source_version": "v1",
        "amount_status": "confirmed",
    }
    txn.update(overrides)
    return txn


class AmountStatusMismatchTest(unittest.TestCase):
    def test_parseable_amount_declared_unknown_is_excluded_from_cash_totals(self):
        txn = make_txn(transaction_id="TX-A", amount="500.00", amount_status="unknown")
        summary = build_cash_summary([txn], [txn])

        self.assertEqual(summary["buckets"]["posted"], [])
        self.assertEqual(summary["totals"]["posted"], Decimal("0"))
        self.assertEqual(len(summary["unknown_amount"]), 1)
        flagged_txn, reason = summary["unknown_amount"][0]
        self.assertEqual(flagged_txn["transaction_id"], "TX-A")
        self.assertEqual(reason, "amount_status mismatch")

    def test_unparseable_amount_declared_confirmed_is_also_a_mismatch(self):
        txn = make_txn(transaction_id="TX-B", amount="not-a-number", amount_status="confirmed")
        summary = build_cash_summary([txn], [txn])

        self.assertEqual(summary["totals"]["posted"], Decimal("0"))
        flagged_txn, reason = summary["unknown_amount"][0]
        self.assertEqual(flagged_txn["transaction_id"], "TX-B")
        self.assertEqual(reason, "amount_status mismatch")

    def test_blank_amount_declared_unknown_agrees_and_is_plain_blank(self):
        # Sanity check: when the two signals agree that the amount is
        # unknown, it must be labeled "amount blank", not a mismatch --
        # proving the mismatch label above is actually conditioned on a
        # real disagreement, not applied unconditionally.
        txn = make_txn(transaction_id="TX-C", amount="", amount_status="unknown")
        summary = build_cash_summary([txn], [txn])

        flagged_txn, reason = summary["unknown_amount"][0]
        self.assertEqual(flagged_txn["transaction_id"], "TX-C")
        self.assertEqual(reason, "amount blank")

    def test_mismatch_is_also_excluded_from_mtd_budget_spend(self):
        txn = make_txn(transaction_id="TX-D", amount="500.00", amount_status="unknown",
                        category="Insurance", status="posted")
        budget_rows = [{"period": "2026-01", "category": "Insurance", "budget_amount": "1000"}]

        result = build_budget_variances([txn], budget_rows, dt.date(2026, 1, 2))

        self.assertEqual(len(result["variances"]), 1)
        self.assertEqual(result["variances"][0]["mtd_posted"], Decimal("0"))
        self.assertEqual(result["orphan_categories"], [])


class OrphanCategoryTest(unittest.TestCase):
    def test_posted_spend_with_no_budget_line_is_an_orphan_not_a_variance(self):
        txn = make_txn(transaction_id="TX-E", category="Catering", amount="750.00",
                        amount_status="confirmed", status="posted")

        result = build_budget_variances([txn], [], dt.date(2026, 1, 2))

        self.assertEqual(result["variances"], [])
        self.assertEqual(len(result["orphan_categories"]), 1)
        orphan = result["orphan_categories"][0]
        self.assertEqual(orphan["category"], "Catering")
        self.assertEqual(orphan["mtd_posted"], Decimal("750.00"))
        self.assertEqual(orphan["txn_ids"], ["TX-E"])

    def test_category_with_a_budget_line_is_not_also_reported_as_an_orphan(self):
        txn = make_txn(transaction_id="TX-F", category="Insurance", amount="500.00",
                        amount_status="confirmed", status="posted")
        budget_rows = [{"period": "2026-01", "category": "Insurance", "budget_amount": "1000"}]

        result = build_budget_variances([txn], budget_rows, dt.date(2026, 1, 2))

        self.assertEqual(result["orphan_categories"], [])
        self.assertEqual(len(result["variances"]), 1)


if __name__ == "__main__":
    unittest.main()
