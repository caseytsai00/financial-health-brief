# Quillhaven Academy — Daily Financial Health Briefing
**Target Date:** 2026-08-11 | **Draft for:** Finance and Operations Manager

## Cash Summary (target-date transactions)
- **Posted:** $2,750.35 — TX-1008, TX-1009, TX-1065, TX-1066, TX-1067, TX-1068 (Credit/Correction: TX-1066)
- **Pending:** $2,650.00 — TX-1010, TX-1011, TX-1069
- **Disputed:** $1,150.00 — TX-1012, TX-1070
- **Amount Unknown (excluded from totals, escalate):** TX-1025 (pending, amount blank)

## Daily Posted Total Comparison
- **2026-08-11 Posted:** $2,750.35
- **2026-08-10 Posted:** $7,894.50
- **Signed Change:** -$5,144.15

## Collected Revenue vs. Outstanding Balance (as-of comparison)
Each metric below is compared target-date vs. comparison-date independently -- never combined into a single relationship or ratio between collected revenue and outstanding balance.

**Collected Revenue**
- **Collected Revenue (2026-08-11):** $25,100.00
- **Collected Revenue (2026-08-10):** $24,600.00
- **Signed Change:** +$500.00

**Outstanding Balance**
- **Outstanding Balance (2026-08-11):** $4,300.00
- **Outstanding Balance (2026-08-10):** $4,700.00
- **Signed Change:** -$400.00

## Material Budget Variances (MTD posted spend vs. monthly budget)
| Department | Budget | MTD Posted | Variance | % |
|---|---|---|---|---|
| Facilities | $4,200.00 | $5,085.00 | +$885.00 | 21.07% |
| Professional-Services | $2,500.00 | $3,330.00 | +$830.00 | 33.20% |
| Software | $2,600.00 | $3,161.00 | +$561.00 | 21.58% |
| Supplies | $4,500.00 | $6,130.75 | +$1,630.75 | 36.24% |
| Training | $1,500.00 | $0.00 | -$1,500.00 | 100.00% |

Source: Budget Targets rows for period 2026-08; Transaction Ledger posted-status rows by category, 2026-08-01 through 2026-08-11.

Not material (below one or both thresholds): Insurance +$500.00 (16.67%), Marketing +$600.00 (10.00%), Refunds -$500.00 (38.46%), Staffing +$2,070.00 (9.86%), Utilities +$220.55 (12.25%).

## Unbudgeted MTD Spend (no matching Budget Targets line)
None — every category with posted spend this month has a matching budget line.

## Unresolved Items Queue (month-to-date, 2026-08)
- Pending (Operations owner): TX-1010 (2026-08-11, $1,250.00), TX-1011 (2026-08-11, $900.00), TX-1017 (2026-08-06, $620.00), TX-1023 (2026-08-10, $275.00), TX-1030 (2026-08-03, $400.00), TX-1040 (2026-08-05, $320.00), TX-1050 (2026-08-07, $275.00), TX-1058 (2026-08-09, $475.00), TX-1064 (2026-08-10, $410.00), TX-1069 (2026-08-11, $500.00)
- Disputed (Operations owner): TX-1012 (2026-08-11, $700.00), TX-1018 (2026-08-06, $350.00), TX-1034 (2026-08-04, $240.00), TX-1054 (2026-08-08, $85.00), TX-1063 (2026-08-10, $600.00), TX-1070 (2026-08-11, $450.00)
- Amount Unknown (Operations owner) — escalate: TX-1025 (2026-08-11, facilities, pending, amount blank), TX-1045 (2026-08-06, facilities, pending, amount blank)

---

## Source Fetch Evidence
Report generated: 2026-10-13T22:46:48+00:00Z

- **Transactions** — `https://docs.google.com/spreadsheets/d/16HhjfR9uG1oUwSFNjQvAvU9Q9gVjzxL0ufBzTJe82v8` (spreadsheet id `16HhjfR9uG1oUwSFNjQvAvU9Q9gVjzxL0ufBzTJe82v8`, default sheet (gid=0)); fetched 2026-10-13T22:46:46+00:00Z; 70 rows; source_version(s): ledger-2026-08-11-v2
- **Budget** — `https://docs.google.com/spreadsheets/d/1pnHBrxWvZBDIQItyxhmaSUZBxF8VMYqo_fyN7JtgyA4` (spreadsheet id `1pnHBrxWvZBDIQItyxhmaSUZBxF8VMYqo_fyN7JtgyA4`, default sheet (gid=0)); fetched 2026-10-13T22:46:47+00:00Z; 10 rows; source_version(s): budget-2026-08-v3
- **Revenue** — `https://docs.google.com/spreadsheets/d/1DToTpZtuwtVIdCPethZRe4T-y6mxGpWuivWSmR2XZt4` (spreadsheet id `1DToTpZtuwtVIdCPethZRe4T-y6mxGpWuivWSmR2XZt4`, default sheet (gid=0)); fetched 2026-10-13T22:46:48+00:00Z; 25 rows; source_version(s): revenue-2026-08-03-v1, revenue-2026-08-05-v1, revenue-2026-08-07-v1, revenue-2026-08-10-v1, revenue-2026-08-11-v2

## Business-Rule Notes (from stakeholder interview)
- Starting/closing cash balance reconciliation is intentionally not part of this brief: the Finance and Operations Manager does not net Posted/Pending/Disputed into one cash total, so no starting/closing balance check is performed or expected.
- Month-to-date budget comparison uses **posted-status Transaction Ledger rows by category**, not the Revenue Snapshot. Revenue Snapshot is normalized to `deliverables/normalized/revenue.csv` for dated revenue/outstanding-balance tracking, but is not an input to the budget-variance calculation.
- Unknown/blank transaction amounts are never assumed to be zero: they keep their status for review but are excluded from every numeric total (cash and MTD budget).

## Definition of Done — Self-Checking Gate
1. **Separate Cash Totals:** Did calculate three distinct totals without netting. *Evidence: Posted $2,750.35, Pending $2,650.00, Disputed $1,150.00 — computed independently from Transaction Ledger rows dated 2026-08-11.*
2. **Negative Numbers Preserved:** Did preserve negative values as Credits/Corrections rather than converting to absolute value. *Evidence: TX-1066.*
3. **Materiality Threshold Strictness:** Did limit "Material Variance" strictly to cases >10% AND >$500. *Evidence: Included — Facilities 21.07%/$885.00; Professional-Services 33.20%/$830.00; Software 21.58%/$561.00; Supplies 36.24%/$1,630.75; Training 100.00%/-$1,500.00. Excluded for failing the strict thresholds — Insurance 16.67%/$500.00; Marketing 10.00%/$600.00; Refunds 38.46%/-$500.00; Staffing 9.86%/$2,070.00; Utilities 12.25%/$220.55.*
4. **No Assumed Figures:** Did use only exact figures from the freshly fetched sources, zero estimates or placeholders. *Evidence: normalized row counts — transactions 70, budget 10, revenue 25.*
5. **Unknown Amounts Excluded:** Did keep unknown-amount transactions in their status category while excluding them from all numeric sums. *Evidence: TX-1025, TX-1045.*
