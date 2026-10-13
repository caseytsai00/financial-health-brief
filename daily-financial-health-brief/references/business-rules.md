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
  category before the brief can be trusted). This validation applies to
  **every** Transaction Ledger row in the month-to-date range being
  scanned for the Unresolved Items Queue (see below) — not only rows
  dated `--target-date` — so a bad status earlier in the month halts the
  run just as it would on the target date itself.

## Unresolved Items Queue scope

- The Unresolved Items Queue (Pending, Disputed, Amount Unknown) is scoped
  to **month-to-date** — the 1st of `--target-date`'s month through
  `--target-date` itself — reusing the same MTD scoping as the
  Month-to-date budget comparison below, so an item doesn't drop off the
  queue just because it isn't dated the target date.
- The Cash Summary section's dollar totals (Posted/Pending/Disputed)
  remain scoped to `--target-date` only. These are two different scopes
  by design: Cash Summary answers "what moved on this specific day,"
  while the Unresolved Items Queue answers "what in this month still
  needs a human."
- Per the manager, the **Operations owner** is the accountable
  decision-maker for all three unresolved item types (Pending, Disputed,
  Amount Unknown) — there is no per-category or per-transaction owner
  for these (unlike Budget Targets, which does carry an `owner` per
  category). The report labels all three accordingly.

## Daily posted-total comparison

- `--comparison-date` is a **required, explicit** argument — never
  defaulted or inferred from `--target-date` (e.g. "the prior business
  day"). The manager strictly uses the exact dates specified in each
  request, for financial consistency and alignment with the intended
  review period. A missing `--comparison-date` blocks the run the same
  way a missing source sheet does.
- The comparison itself is the **signed change** in the Posted total only
  (`target-date Posted − comparison-date Posted`) — Pending and Disputed
  are not part of this comparison, consistent with Posted being the only
  status that represents settled cash (see Month-to-date budget
  comparison, below).
- A comparison date with **zero** Transaction Ledger rows does not block
  the run: it doesn't corrupt any other figure in the report, so it is
  flagged ("no comparison data available") rather than failing safely.
  This is deliberately different from `--target-date` having zero rows,
  which is a "Missing Source of Truth" failure because the whole brief is
  about that date.

## Collected revenue vs. outstanding balance

- "Collected revenue against outstanding balances" means two **independent**
  as-of comparisons — `collected_revenue` target-date vs. comparison-date,
  and separately `outstanding_balance` target-date vs. comparison-date —
  the same two-date, signed-change structure as the Daily Posted Total
  Comparison above, just applied to these two Revenue Snapshot metrics.
  They are explicitly **not** combined into any single relationship or
  ratio between the two metrics (e.g. no "collection rate").
- The Revenue Snapshot does not get a row for every calendar day by
  design — unlike the Transaction Ledger, it updates sparsely (in the
  August 2026 data, 5 of 9 days in the observed window have a row at all).
  A missing same-day entry for `--target-date` or `--comparison-date` is
  therefore an **expected** characteristic of this sheet, not an error.
- When the exact date has no row, the script falls back to the most
  recent **real** observation on or before that date, and labels the
  output with that observation's own date. This is explicitly **not** the
  same as the "never assume zero for an unknown amount" rule below: one is
  a real, if slightly stale, number; the other has no factual basis at
  all. Falling back to a labeled real value is safe; inventing a number
  (including zero) is not.
- If there is no observation at all on or before the requested date (it
  predates the Revenue Snapshot's first row), that date's value — and the
  signed change that depends on it — is flagged as unavailable rather than
  failing the run, consistent with how a zero-row `--comparison-date`
  is handled for Posted cash.

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
