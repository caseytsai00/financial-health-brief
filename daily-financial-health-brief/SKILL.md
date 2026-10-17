---
name: daily-financial-health-brief
description: Freshly fetches Quillhaven Academy's Transaction Ledger, Budget Targets, and Revenue Snapshot Google Sheets, normalizes them into CSV, and drafts the daily/MTD financial health brief (cash summary, material budget variances, unresolved items) for the Finance and Operations Manager. Activate when asked to prepare, refresh, regenerate, or reproduce Quillhaven Academy's daily financial health brief, or to normalize/reconcile its three source sheets against the monthly budget.
---

# Daily Financial Health Brief

Turns Quillhaven Academy's three live Google Sheets into normalized CSVs and a
concise Markdown management brief, in one reproducible run.

## Runtime and dependencies

- Python 3.9+ (standard library only — no third-party packages required).
  - Tested with the macOS system interpreter (`/usr/bin/python3`) and Homebrew Python.
  - If you hit `CERTIFICATE_VERIFY_FAILED` (common on python.org "framework"
    builds whose trust store isn't wired to the OS), either run that Python's
    `Install Certificates.command`, or `pip install certifi` — the script
    auto-detects and uses certifi's CA bundle when it's importable.
- Network access to `docs.google.com` (outbound HTTPS only). No credentials,
  API keys, or OAuth are needed: the three sheets are shared "Anyone with the
  link – Viewer."

## Inputs: the three Sheets and how their roles are identified

The skill fetches these three viewer-only Google Sheets on **every run** —
never a bundled, downloaded, or previously cached CSV:

| Role | Default URL |
|---|---|
| Transaction Ledger | `https://docs.google.com/spreadsheets/d/16HhjfR9uG1oUwSFNjQvAvU9Q9gVjzxL0ufBzTJe82v8` |
| Budget Targets | `https://docs.google.com/spreadsheets/d/1pnHBrxWvZBDIQItyxhmaSUZBxF8VMYqo_fyN7JtgyA4` |
| Revenue Snapshot | `https://docs.google.com/spreadsheets/d/1DToTpZtuwtVIdCPethZRe4T-y6mxGpWuivWSmR2XZt4` |

Each URL is converted to its CSV export endpoint
(`.../export?format=csv&gid=…`) and fetched fresh. The skill does **not**
trust the URL's declared role or argument position: it fingerprints each
fetched sheet's header row and assigns a role by the columns actually present
(`transaction_id`+`amount`+`status` → transactions; `budget_amount`+`period`
→ budget; `metric`+`value` → revenue). This keeps the run correct even if
column order, source names, or extra columns change, or if two URLs are
passed out of order.

If a URL omits `gid`, the skill does **not** assume `gid=0` for the
default tab — that gid doesn't exist on any of the three real sheets
(each returns HTTP 400 if explicitly requested). Instead,
`discover_default_gid()` fetches the sheet's `/htmlview` page and parses
the gid it actually marks as the default/initial tab, failing safely if
it can't be found rather than guessing. The discovered gid is reported in
both the `report.md` fetch evidence and the stderr `[fetch-evidence]`
line as `tab=gid=<n>`.

The three URLs are overridable — pass different Sheet URLs (e.g. a test
fixture, or next month's sheets) via `--transactions-url`, `--budget-url`,
`--revenue-url` without editing the script.

## Execution command

From the repository root:

```bash
python3 daily-financial-health-brief/scripts/generate_brief.py \
  --target-date 2026-08-11 \
  --comparison-date 2026-08-10
```

- `--target-date YYYY-MM-DD` (optional): the day to brief on. **Defaults to
  the previous business day relative to the run date** (weekends skipped;
  no holiday calendar is encoded — a holiday will need an explicit
  `--target-date` or a future enhancement here).
- `--comparison-date YYYY-MM-DD` (**required, no default**): the day to
  compare `--target-date`'s Posted cash total against. Per the Finance and
  Operations Manager, this is never inferred — missing it is a safe
  failure, same as a missing source sheet.
- `--transactions-url` / `--budget-url` / `--revenue-url` (optional):
  override any of the three default Sheet URLs.
- `--out-dir` (optional): defaults to `deliverables/` at the repository root.

Re-running with the same source snapshot and the same `--target-date` and
`--comparison-date` produces byte-for-byte identical `report.md` content
(all aggregation uses `Decimal` arithmetic and sorted iteration order — no
floating point, no wall-clock-dependent values baked into the numbers).
`--comparison-date` is required and affects the output (Daily Posted
Total Comparison, Collected Revenue vs. Outstanding Balance), so it has
to match too, not just `--target-date`.

## Outputs

- `deliverables/normalized/transactions.csv` — every Transaction Ledger row, columns:
  `transaction_id, date, account, category, description, amount, currency, status, source, source_version, amount_status`.
- `deliverables/normalized/budget.csv` — every Budget Targets row, columns:
  `period, category, budget_amount, currency, owner, review_rule, source, source_version`.
- `deliverables/normalized/revenue.csv` — every Revenue Snapshot row, columns:
  `date, source, metric, value, currency, source_version`.
- `deliverables/report.md` — the daily brief: Cash Summary (target-date
  only), Daily Posted Total Comparison (target vs. comparison date, signed
  change), Collected Revenue vs. Outstanding Balance (two independent
  as-of comparisons — never combined into a ratio), Material Budget
  Variances, Unbudgeted MTD Spend, Unresolved Items Queue
  (**month-to-date**, not just the target date), source fetch evidence
  (URL, spreadsheet ID, tab, fetch timestamp, source_version, row count
  per sheet), business-rule notes, and a self-checking Definition-of-Done
  gate.

Fetch evidence (URL / spreadsheet ID / tab / timestamp / source_version /
row count for each of the three sheets) is also printed to stderr *before*
any deliverable file is written, so the run log captures proof of a live
read independent of the committed report.

## Validation and safe-failure behavior

The script never silently substitutes stale, cached, or partial data. It
exits non-zero and writes **no** deliverables (existing ones are left
untouched) when:

- A sheet fetch fails (network error, non-200 status), returns something
  that isn't a plain CSV (wrong content-type, or an HTML/sign-in page —
  usually a sharing-permission problem), or its header doesn't fingerprint
  to any known role.
- A URL without an explicit gid can't have its default tab's real gid
  discovered from `/htmlview` (fetch failure, or the page doesn't mark an
  initial-sheet gid) — the script never assumes `gid=0`.
- The Transaction Ledger has zero rows dated `--target-date` ("Missing
  Source of Truth" — most often because the sheet hasn't been updated yet,
  or the default previous-business-day has no data and no override was
  given).
- Any transaction's `status` isn't one of `posted` / `pending` /
  `disputed`, for **any date in the month-to-date range** being scanned
  for the Unresolved Items Queue (the 1st of `--target-date`'s month
  through `--target-date`) — not only rows dated `--target-date` itself
  (needs manual categorization before the run can continue).
- `--comparison-date` is missing (never defaulted or inferred — see
  [`references/business-rules.md`](references/business-rules.md)).

A `--comparison-date` with **zero** Transaction Ledger rows is different:
it doesn't fail the run, since it doesn't corrupt anything else in the
report — it's flagged as "no comparison data available" in the Daily
Posted Total Comparison section instead. The same non-failing treatment
applies to `collected_revenue` / `outstanding_balance` when neither
`--target-date` nor `--comparison-date` has a Revenue Snapshot row on or
before it — except there, a missing exact-date row first tries falling
back to the most recent earlier real observation (labeled with its own
date) before being flagged unavailable; see
[`references/business-rules.md`](references/business-rules.md).

### Testing safe-failure paths

Several of the checks above are hard to exercise against the real sheets,
so `tests/` covers them either against a local HTTP fixture server
(`tests/fixture_server.py`, no real sheet access or network needed) or as
direct unit tests of the business-logic functions:

- **Bad-status row with a valid amount** (`test_untestable_paths.py`) — a
  transaction with a non-blank, parseable `amount` but a `status` outside
  `posted`/`pending`/`disputed` must raise `SafeFailure`. The amount has to
  be non-blank: a blank/unparseable amount routes the row to
  `unknown_amount` *before* the status is ever checked, so a blank-amount
  version of the same bad status is included as a sanity check that must
  **not** raise.
- **Role-mismatch header** (`test_untestable_paths.py`) — a sheet whose
  header doesn't fingerprint to any of transactions/budget/revenue must
  raise `SafeFailure`. No special row is needed; the header alone decides
  this.
- **amount_status mismatch and orphan categories**
  (`test_amount_status_and_orphan_category.py`) — a transaction whose
  `amount_status` disagrees with whether `amount` actually parses must be
  excluded from both cash and MTD budget totals; a category with posted
  spend but no Budget Targets row must appear as an orphan, not silently
  vanish.
- **Daily posted-total comparison** (`test_posted_comparison.py`) — a
  missing `--comparison-date` must raise `SafeFailure` end-to-end; a
  comparison date with zero rows must be flagged, not failed; the signed
  change must be `target − comparison` in both directions.
- **Collected revenue vs. outstanding balance** (`test_revenue_comparison.py`)
  — an exact-date row is used directly; a missing date falls back to the
  most recent earlier real observation, labeled with its own date, and the
  signed change still computes from that fallback; a date before the
  earliest Revenue Snapshot row has no fallback and is flagged unavailable,
  not failed; the two metrics are always reported independently.
- **Month-to-date Unresolved Items Queue scope**
  (`test_mtd_unresolved_scope.py`) — Cash Summary totals stay target-date
  only even when the month scope is larger; the Unresolved Items Queue
  picks up pending/disputed/unknown-amount items from earlier in the
  month; a bad status earlier in the month still raises `SafeFailure`; a
  bad status outside the scanned month (a prior month) does not, since
  `month_to_date_transactions()` never includes it in the first place.
- **Default-tab gid discovery** (`test_gid_discovery.py`) — a sheet URL
  without an explicit gid must discover the real one from `/htmlview`
  (not assume `gid=0`); discovery queries the sheet's own host, not a
  hardcoded `docs.google.com`, which is what makes this testable against
  a local fixture at all; an unregistered/unreachable sheet raises
  `SafeFailure` rather than guessing a gid.

Run from `daily-financial-health-brief/`:

```
python3 -m unittest discover -s tests -v
```

### Disclosure: paths never triggered against the real sheets

The six paths below are exercised by the test suite, but have **never
actually fired** against the real Transaction Ledger / Budget Targets /
Revenue Snapshot data this skill runs against. This is stated here
plainly rather than left for someone to discover — these are tested
*in case* the data changes, not because they've been observed:

1. **Bad status value** (`test_untestable_paths.py`) — only `posted`,
   `pending`, and `disputed` have ever appeared in the real data.
2. **Role-mismatch header** (`test_untestable_paths.py`) — all three real
   sheets fingerprint correctly by their columns every time.
3. **`amount_status` mismatch** (`test_amount_status_and_orphan_category.py`)
   — zero mismatches between `amount_status` and the parsed `amount` have
   been found in the real data.
4. **Comparison date with zero rows** (`test_posted_comparison.py`) —
   2026-08-10, the comparison date used in the committed deliverable, has
   real Transaction Ledger rows.
5. **Revenue date before the earliest observation**
   (`test_revenue_comparison.py`) — the target and comparison dates used
   so far are within the Revenue Snapshot's known range.
6. **Orphan category** (`test_amount_status_and_orphan_category.py`) —
   every real posted-spend category has had a matching Budget Targets
   row so far.

Business rules for what counts as a "material" variance, how unknown
amounts and negative values are handled, and which decisions came directly
from the Finance and Operations Manager are in
[`references/business-rules.md`](references/business-rules.md).
