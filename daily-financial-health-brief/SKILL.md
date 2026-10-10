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
(`.../export?format=csv[&gid=…]`) and fetched fresh. The skill does **not**
trust the URL's declared role or argument position: it fingerprints each
fetched sheet's header row and assigns a role by the columns actually present
(`transaction_id`+`amount`+`status` → transactions; `budget_amount`+`period`
→ budget; `metric`+`value` → revenue). This keeps the run correct even if
column order, source names, or extra columns change, or if two URLs are
passed out of order.

The three URLs are overridable — pass different Sheet URLs (e.g. a test
fixture, or next month's sheets) via `--transactions-url`, `--budget-url`,
`--revenue-url` without editing the script.

## Execution command

From the repository root:

```bash
python3 daily-financial-health-brief/scripts/generate_brief.py \
  --target-date 2026-08-11
```

- `--target-date YYYY-MM-DD` (optional): the day to brief on. **Defaults to
  the previous business day relative to the run date** (weekends skipped;
  no holiday calendar is encoded — a holiday will need an explicit
  `--target-date` or a future enhancement here).
- `--transactions-url` / `--budget-url` / `--revenue-url` (optional):
  override any of the three default Sheet URLs.
- `--out-dir` (optional): defaults to `deliverables/` at the repository root.

Re-running with the same source snapshot and the same `--target-date`
produces byte-for-byte identical `report.md` content (all aggregation uses
`Decimal` arithmetic and sorted iteration order — no floating point, no
wall-clock-dependent values baked into the numbers).

## Outputs

- `deliverables/normalized/transactions.csv` — every Transaction Ledger row, columns:
  `transaction_id, date, account, category, description, amount, currency, status, source, source_version, amount_status`.
- `deliverables/normalized/budget.csv` — every Budget Targets row, columns:
  `period, category, budget_amount, currency, owner, review_rule, source, source_version`.
- `deliverables/normalized/revenue.csv` — every Revenue Snapshot row, columns:
  `date, source, metric, value, currency, source_version`.
- `deliverables/report.md` — the daily brief: Cash Summary, Material Budget
  Variances, Unresolved Items Queue, source fetch evidence (URL, spreadsheet
  ID, tab, fetch timestamp, source_version, row count per sheet),
  business-rule notes, and a self-checking Definition-of-Done gate.

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
- The Transaction Ledger has zero rows dated `--target-date` ("Missing
  Source of Truth" — most often because the sheet hasn't been updated yet,
  or the default previous-business-day has no data and no override was
  given).
- A target-date transaction's `status` isn't one of `posted` / `pending` /
  `disputed` (needs manual categorization before the run can continue).

### Testing safe-failure paths

Two of the safe-failure checks above are hard to exercise against the real
sheets, so `tests/` covers them against a local HTTP fixture server instead
(`tests/fixture_server.py`) — no real sheet access or network needed:

- **Bad-status row with a valid amount** — a transaction with a non-blank,
  parseable `amount` but a `status` outside `posted`/`pending`/`disputed`
  must raise `SafeFailure`. The amount has to be non-blank: a blank/
  unparseable amount routes the row to `unknown_amount` *before* the status
  is ever checked, so a blank-amount version of the same bad status is
  included as a sanity check that must **not** raise.
- **Role-mismatch header** — a sheet whose header doesn't fingerprint to
  any of transactions/budget/revenue must raise `SafeFailure`. No special
  row is needed; the header alone decides this.

Run from `daily-financial-health-brief/`:

```
python3 -m unittest tests.test_untestable_paths -v
```

Business rules for what counts as a "material" variance, how unknown
amounts and negative values are handled, and which decisions came directly
from the Finance and Operations Manager are in
[`references/business-rules.md`](references/business-rules.md).
