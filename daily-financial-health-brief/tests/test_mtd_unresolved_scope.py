"""Covers the Unresolved Items Queue's scope: it now spans the whole
month-to-date range (1st of target_date's month through target_date
itself), reusing month_to_date_transactions() -- the same MTD scoping
build_budget_variances() already used. Cash Summary's dollar totals stay
strictly target-date only. And because build_cash_summary() now validates
status across month_transactions, a bad status anywhere in that range
halts the run, not just on the target date itself.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from generate_brief import (  # noqa: E402
    SafeFailure,
    build_cash_summary,
    build_unresolved_queue,
    month_to_date_transactions,
)


def make_txn(**overrides) -> dict:
    txn = {
        "transaction_id": "TX-DEFAULT",
        "date": "2026-08-11",
        "account": "Checking",
        "category": "Insurance",
        "description": "Test row",
        "amount": "500.00",
        "currency": "USD",
        "status": "pending",
        "source": "test",
        "source_version": "v1",
        "amount_status": "confirmed",
    }
    txn.update(overrides)
    return txn


class CashSummaryScopeTest(unittest.TestCase):
    def test_totals_stay_target_date_only_even_with_a_larger_month_scope(self):
        day_txn = make_txn(transaction_id="TX-TARGET", date="2026-08-11", status="posted")
        earlier_in_month = make_txn(transaction_id="TX-EARLIER", date="2026-08-05", status="posted")
        day_transactions = [day_txn]
        month_transactions = [day_txn, earlier_in_month]

        summary = build_cash_summary(day_transactions, month_transactions)

        self.assertEqual(summary["totals"]["posted"], Decimal("500.00"))
        self.assertEqual(len(summary["buckets"]["posted"]), 1)
        self.assertEqual(summary["buckets"]["posted"][0][0]["transaction_id"], "TX-TARGET")

    def test_month_buckets_include_the_earlier_day_too(self):
        day_txn = make_txn(transaction_id="TX-TARGET", date="2026-08-11", status="pending")
        earlier_in_month = make_txn(transaction_id="TX-EARLIER", date="2026-08-05", status="pending")
        summary = build_cash_summary([day_txn], [day_txn, earlier_in_month])

        month_pending_ids = {t["transaction_id"] for t, _ in summary["month_buckets"]["pending"]}
        self.assertEqual(month_pending_ids, {"TX-TARGET", "TX-EARLIER"})

    def test_bad_status_earlier_in_the_month_still_halts_the_run(self):
        day_txn = make_txn(transaction_id="TX-TARGET", date="2026-08-11", status="posted")
        bad_status_earlier = make_txn(transaction_id="TX-BAD", date="2026-08-03", status="voided")

        with self.assertRaises(SafeFailure):
            build_cash_summary([day_txn], [day_txn, bad_status_earlier])

    def test_bad_status_outside_the_scanned_month_does_not_affect_this_run(self):
        # month_to_date_transactions() excludes prior months entirely --
        # a bad status there was never passed in, so it can't raise.
        day_txn = make_txn(transaction_id="TX-TARGET", date="2026-08-11", status="posted")
        all_transactions = [day_txn, make_txn(transaction_id="TX-JULY-BAD", date="2026-07-30", status="voided")]

        month_transactions = month_to_date_transactions(all_transactions, dt.date(2026, 8, 11))
        self.assertEqual([t["transaction_id"] for t in month_transactions], ["TX-TARGET"])

        summary = build_cash_summary([day_txn], month_transactions)
        self.assertEqual(summary["totals"]["posted"], Decimal("500.00"))


class UnresolvedQueueScopeTest(unittest.TestCase):
    def test_unresolved_queue_includes_items_from_earlier_in_the_month(self):
        day_txn = make_txn(transaction_id="TX-TODAY", date="2026-08-11", status="disputed")
        earlier = make_txn(transaction_id="TX-EARLIER", date="2026-08-02", status="disputed")

        summary = build_cash_summary([day_txn], [day_txn, earlier])
        unresolved = build_unresolved_queue(summary)

        self.assertEqual(
            {t["transaction_id"] for t in unresolved["disputed"]}, {"TX-TODAY", "TX-EARLIER"}
        )

    def test_unresolved_queue_unknown_amount_also_spans_the_month(self):
        day_txn = make_txn(transaction_id="TX-TODAY", date="2026-08-11", amount="")
        earlier = make_txn(transaction_id="TX-EARLIER", date="2026-08-02", amount="")

        summary = build_cash_summary([day_txn], [day_txn, earlier])
        unresolved = build_unresolved_queue(summary)

        ids = {t["transaction_id"] for t, _ in unresolved["unknown_amount"]}
        self.assertEqual(ids, {"TX-TODAY", "TX-EARLIER"})


if __name__ == "__main__":
    unittest.main()
