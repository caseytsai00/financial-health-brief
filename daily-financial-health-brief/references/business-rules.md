# Business Rules (from the Finance and Operations Manager interview)

These rules are encoded in `../scripts/generate_brief.py`. This file exists
so an operator can audit *why* the script behaves as it does without reading
the code, and so future changes stay consistent with what was actually
requested.

## Cash categorization

- Posted, Pending, and Disputed cash are always three **separate** totals.
  Never net them into one cash figure — the manager's workflow depends on
  seeing each status independently.
- Negative amounts are preserved exactly as signed values and labeled
  "Credit/Correction" — never flipped to positive, never dropped.
- A transaction whose `status` is anything other than `posted`, `pending`,
  or `disputed` blocks the run (needs a human to assign the correct
  category before the brief can be trusted).

## Unknown or blank amounts

- A transaction with a blank/unparseable `amount` keeps its status for
  visibility but is **excluded from every numeric total** — cash totals and
  MTD budget totals alike. Never assumed to be zero, never estimated.
- It is still surfaced by transaction ID in the report's Unresolved Items
  Queue, marked "Amount Unknown," for escalation.

## Materiality threshold

- A budget variance is "material" only if it is **strictly greater than
  both** 10% of the department's monthly budget **and** USD 500 in absolute
  dollar terms. Both conditions are strict inequalities — a variance sitting
  at exactly 10% or exactly $500 does **not** qualify. (The August 2026 data
  contains real examples that land exactly on each boundary; the script's
  test run confirms both are correctly excluded.)
- Report language uses exact dollar amounts, department names, and
  percentages — never qualitative words like "large" or "unusual."

## Month-to-date budget comparison

- MTD spend per department is summed from **Transaction Ledger rows with
  `status = posted`** only, for the target date's calendar month through
  the target date, grouped by `category`. This is compared against
  `Budget Targets.budget_amount` for the matching `period`.
- The Revenue Snapshot sheet is **not** an input to this comparison. Per
  the manager: Revenue Snapshot is used for dated revenue and
  outstanding-balance comparisons, a separate concern from expense-vs-budget
  reconciliation. It is still normalized to `deliverables/normalized/revenue.csv`
  for that separate use and for traceability.

## Starting/closing cash balance reconciliation — intentionally out of scope

An earlier draft of the reporting spec called for comparing the prior day's
starting cash balance against the previous day's closing balance, and
pausing on any mismatch. The manager clarified this is **not** how the
actual daily brief works: because Posted/Pending/Disputed are never netted
into one cash total (see above), there is no single "cash balance" to
reconcile day-over-day in the first place. This script does not implement
that check, and none of the three source sheets carries a balance field —
so there is nothing to compare even if it were requested later.

## Escalation without an interactive operator

The original spec described "pause and ask the Finance and Operations
Manager" for out-of-band items (unknown amounts, uncategorized statuses).
This script runs non-interactively (e.g. on a schedule), so it implements
that intent as **fail-safe, not fail-silent**:

- Recoverable-by-listing items (unknown amounts) are still written into the
  report's Unresolved Items Queue for a human to review and resolve —
  the run completes.
- Non-recoverable items (a transaction status the script doesn't recognize,
  a sheet that won't fetch as valid CSV, no ledger rows for the target date)
  stop the run entirely with a clear message on stderr and **no** deliverable
  files are written or overwritten. A human reruns once the underlying data
  or configuration is fixed.
