#!/usr/bin/env python3
"""Daily Financial Health Brief generator for Quillhaven Academy.

Freshly fetches the Transaction Ledger, Budget Targets, and Revenue Snapshot
Google Sheets (viewer-only, CSV export), normalizes them into
deliverables/normalized/*.csv, and drafts deliverables/report.md.

Standard-library only. No third-party dependencies, no credentials required
(the three sheets are shared "Anyone with the link -> Viewer").

See ../SKILL.md for full documentation and ../references/ for the
business rules this script encodes.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

try:  # optional: use certifi's CA bundle if present, for portability across
      # Python installs whose default trust store is incomplete (e.g. some
      # python.org framework builds on macOS).
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None
from collections import defaultdict
from decimal import Decimal, InvalidOperation

DEFAULT_URLS = {
    "transactions": "https://docs.google.com/spreadsheets/d/16HhjfR9uG1oUwSFNjQvAvU9Q9gVjzxL0ufBzTJe82v8",
    "budget": "https://docs.google.com/spreadsheets/d/1pnHBrxWvZBDIQItyxhmaSUZBxF8VMYqo_fyN7JtgyA4",
    "revenue": "https://docs.google.com/spreadsheets/d/1DToTpZtuwtVIdCPethZRe4T-y6mxGpWuivWSmR2XZt4",
}

TRANSACTIONS_FIELDS = [
    "transaction_id", "date", "account", "category", "description", "amount",
    "currency", "status", "source", "source_version", "amount_status",
]
BUDGET_FIELDS = [
    "period", "category", "budget_amount", "currency", "owner",
    "review_rule", "source", "source_version",
]
REVENUE_FIELDS = ["date", "source", "metric", "value", "currency", "source_version"]

CASH_STATUSES = ("posted", "pending", "disputed")
MATERIALITY_PCT = Decimal("0.10")
MATERIALITY_USD = Decimal("500")


class SafeFailure(RuntimeError):
    """Raised when the run must stop without producing/overwriting deliverables."""


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def export_csv_url(sheet_url: str) -> tuple[str, str]:
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", sheet_url)
    if not match:
        raise SafeFailure(f"Could not parse a spreadsheet ID out of URL: {sheet_url}")
    sheet_id = match.group(1)
    gid_match = re.search(r"[?&#]gid=([0-9]+)", sheet_url)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid_match:
        url += f"&gid={gid_match.group(1)}"
    return url, sheet_id


def fetch_sheet(sheet_url: str, timeout: int = 20) -> dict:
    """Freshly GET a Google Sheet as CSV and validate it is real tabular data.

    Never falls back to a cached/local copy: any failure here raises
    SafeFailure and the run stops before touching deliverables.
    """
    export_url, sheet_id = export_csv_url(sheet_url)
    request = urllib.request.Request(
        export_url, headers={"User-Agent": "quillhaven-financial-brief/1.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise SafeFailure(
            f"Live fetch failed for {sheet_url}: HTTP {exc.code}. "
            "Refusing to substitute a cached or downloaded copy."
        ) from exc
    except urllib.error.URLError as exc:
        hint = ""
        if isinstance(exc.reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc.reason):
            hint = (
                " This looks like a local trust-store problem, not a source problem: "
                "run 'pip install certifi' or, on macOS python.org builds, "
                "'/Applications/Python 3.x/Install Certificates.command'."
            )
        raise SafeFailure(
            f"Live fetch failed for {sheet_url}: {exc.reason}."
            f"{hint} Refusing to substitute a cached or downloaded copy."
        ) from exc

    if status != 200:
        raise SafeFailure(f"Live fetch failed for {sheet_url}: HTTP {status}")

    text = raw.decode("utf-8-sig")
    lowered_head = text[:500].lower()
    is_csv_content_type = "csv" in content_type.lower() or "text/plain" in content_type.lower()
    looks_like_login_or_html = "<html" in lowered_head or "accounts.google.com" in lowered_head
    if not is_csv_content_type or looks_like_login_or_html:
        raise SafeFailure(
            f"Response for {sheet_url} was not a plain CSV export "
            f"(content-type={content_type!r}). This usually means the sheet "
            "is not shared as 'Anyone with the link - Viewer', or Google "
            "returned a sign-in/error page. Refusing to proceed on unverified data."
        )

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    header = list(reader.fieldnames or [])

    return {
        "sheet_url": sheet_url,
        "spreadsheet_id": sheet_id,
        "export_url": export_url,
        "tab_identity": "default sheet (gid=0)" if "gid=" not in export_url else export_url.split("gid=")[-1],
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") + "Z",
        "row_count": len(rows),
        "header": header,
        "rows": rows,
    }


def detect_role(fetched: dict) -> str:
    """Identify a fetched sheet's role by column fingerprint, not URL order or position."""
    header = set(fetched["header"])
    if {"transaction_id", "amount", "status"}.issubset(header):
        return "transactions"
    if {"budget_amount", "period"}.issubset(header):
        return "budget"
    if {"metric", "value"}.issubset(header):
        return "revenue"
    raise SafeFailure(
        f"Could not identify the role of {fetched['sheet_url']} from its "
        f"columns {fetched['header']}. Expected a transactions, budget, or "
        "revenue schema fingerprint."
    )


def fetch_all(urls: dict) -> dict:
    fetched_by_role = {}
    for label, url in urls.items():
        fetched = fetch_sheet(url)
        role = detect_role(fetched)
        fetched["declared_label"] = label
        fetched_by_role[role] = fetched
    missing = {"transactions", "budget", "revenue"} - set(fetched_by_role)
    if missing:
        raise SafeFailure(f"Missing required source role(s) after fetch: {sorted(missing)}")
    return fetched_by_role


# --------------------------------------------------------------------------
# Normalize
# --------------------------------------------------------------------------

def parse_amount(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if cleaned == "":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def normalize_rows(rows: list[dict], fields: list[str]) -> list[dict]:
    normalized = []
    for row in rows:
        normalized.append({field: row.get(field, "") for field in fields})
    return normalized


def write_csv(path: str, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# --------------------------------------------------------------------------
# Business logic (see references/business-rules.md for the interview source)
# --------------------------------------------------------------------------

def previous_business_day(reference: dt.date) -> dt.date:
    candidate = reference - dt.timedelta(days=1)
    while candidate.weekday() >= 5:  # Saturday=5, Sunday=6
        candidate -= dt.timedelta(days=1)
    return candidate


def build_cash_summary(day_transactions: list[dict]) -> dict:
    buckets = {status: [] for status in CASH_STATUSES}
    unknown_amount = []

    for txn in day_transactions:
        status = (txn["status"] or "").strip().lower()
        amount = parse_amount(txn["amount"])
        if amount is None:
            unknown_amount.append(txn)
            continue
        if status not in CASH_STATUSES:
            raise SafeFailure(
                f"Transaction {txn['transaction_id']} on {txn['date']} has an "
                f"unrecognized status '{txn['status']}' (expected posted/pending/"
                "disputed). Escalate for manual categorization before rerunning."
            )
        buckets[status].append((txn, amount))

    totals = {status: sum((amt for _, amt in items), Decimal("0")) for status, items in buckets.items()}
    return {"buckets": buckets, "totals": totals, "unknown_amount": unknown_amount}


def build_budget_variances(all_transactions: list[dict], budget_rows: list[dict], target_date: dt.date) -> list[dict]:
    month_prefix = target_date.strftime("%Y-%m")
    target_str = target_date.isoformat()

    mtd_posted = defaultdict(lambda: Decimal("0"))
    mtd_txn_ids = defaultdict(list)
    for txn in all_transactions:
        date_str = txn["date"]
        if not date_str.startswith(month_prefix) or date_str > target_str:
            continue
        if (txn["status"] or "").strip().lower() != "posted":
            continue
        amount = parse_amount(txn["amount"])
        if amount is None:
            continue  # never assume zero for an unknown amount
        category = txn["category"]
        mtd_posted[category] += amount
        mtd_txn_ids[category].append(txn["transaction_id"])

    budget_by_category = {}
    for row in budget_rows:
        if row["period"] == month_prefix:
            budget_amount = parse_amount(row["budget_amount"])
            if budget_amount is not None:
                budget_by_category[row["category"]] = budget_amount

    variances = []
    for category in sorted(budget_by_category):
        budget_amount = budget_by_category[category]
        spend = mtd_posted.get(category, Decimal("0"))
        variance = spend - budget_amount
        pct = (abs(variance) / budget_amount * 100) if budget_amount != 0 else None
        material = (
            budget_amount != 0
            and pct is not None
            and pct > (MATERIALITY_PCT * 100)
            and abs(variance) > MATERIALITY_USD
        )
        variances.append({
            "category": category,
            "budget": budget_amount,
            "mtd_posted": spend,
            "variance": variance,
            "pct": pct,
            "material": material,
            "txn_ids": sorted(mtd_txn_ids.get(category, [])),
        })
    return variances


def build_unresolved_queue(cash_summary: dict) -> dict:
    pending = sorted((t for t, _ in cash_summary["buckets"]["pending"]), key=lambda t: t["transaction_id"])
    disputed = sorted((t for t, _ in cash_summary["buckets"]["disputed"]), key=lambda t: t["transaction_id"])
    unknown = sorted(cash_summary["unknown_amount"], key=lambda t: t["transaction_id"])
    return {"pending": pending, "disputed": disputed, "unknown_amount": unknown}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def fmt_usd(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def fmt_pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def render_report(
    target_date: dt.date,
    cash_summary: dict,
    variances: list[dict],
    unresolved: dict,
    fetch_meta: dict,
    generated_at: str,
) -> str:
    lines = []
    lines.append("# Quillhaven Academy — Daily Financial Health Briefing")
    lines.append(f"**Target Date:** {target_date.isoformat()} | **Draft for:** Finance and Operations Manager")
    lines.append("")
    lines.append("## Cash Summary (target-date transactions)")
    posted_ids = ", ".join(t["transaction_id"] for t, _ in cash_summary["buckets"]["posted"])
    pending_ids = ", ".join(t["transaction_id"] for t, _ in cash_summary["buckets"]["pending"])
    disputed_ids = ", ".join(t["transaction_id"] for t, _ in cash_summary["buckets"]["disputed"])
    credits = [
        t["transaction_id"] for t, amt in cash_summary["buckets"]["posted"] if amt < 0
    ]
    lines.append(f"- **Posted:** {fmt_usd(cash_summary['totals']['posted'])} — {posted_ids or 'none'}"
                  + (f" (Credit/Correction: {', '.join(credits)})" if credits else ""))
    lines.append(f"- **Pending:** {fmt_usd(cash_summary['totals']['pending'])} — {pending_ids or 'none'}")
    lines.append(f"- **Disputed:** {fmt_usd(cash_summary['totals']['disputed'])} — {disputed_ids or 'none'}")
    if cash_summary["unknown_amount"]:
        unk = ", ".join(f"{t['transaction_id']} ({t['status']})" for t in cash_summary["unknown_amount"])
        lines.append(f"- **Amount Unknown (excluded from totals, escalate):** {unk}")
    lines.append("")

    lines.append("## Material Budget Variances (MTD posted spend vs. monthly budget)")
    material = [v for v in variances if v["material"]]
    if material:
        lines.append("| Department | Budget | MTD Posted | Variance | % |")
        lines.append("|---|---|---|---|---|")
        for v in material:
            sign = "+" if v["variance"] >= 0 else ""
            lines.append(
                f"| {v['category'].title()} | {fmt_usd(v['budget'])} | {fmt_usd(v['mtd_posted'])} "
                f"| {sign}{fmt_usd(v['variance'])} | {fmt_pct(v['pct'])} |"
            )
        lines.append("")
        lines.append(
            "Source: Budget Targets rows for period "
            f"{target_date.strftime('%Y-%m')}; Transaction Ledger posted-status rows by "
            f"category, {target_date.strftime('%Y-%m')}-01 through {target_date.isoformat()}."
        )
    else:
        lines.append("None met the strict threshold (>10% of budget AND >$500).")
    not_material = [v for v in variances if not v["material"]]
    if not_material:
        parts = []
        for v in not_material:
            sign = "+" if v["variance"] >= 0 else ""
            parts.append(f"{v['category'].title()} {sign}{fmt_usd(v['variance'])} ({fmt_pct(v['pct'])})")
        lines.append("")
        lines.append("Not material (below one or both thresholds): " + ", ".join(parts) + ".")
    lines.append("")

    lines.append("## Unresolved Items Queue (target date)")
    if unresolved["pending"]:
        lines.append("- Pending: " + ", ".join(
            f"{t['transaction_id']} ({fmt_usd(parse_amount(t['amount']))})" for t in unresolved["pending"]
        ))
    if unresolved["disputed"]:
        lines.append("- Disputed: " + ", ".join(
            f"{t['transaction_id']} ({fmt_usd(parse_amount(t['amount']))})" for t in unresolved["disputed"]
        ))
    if unresolved["unknown_amount"]:
        lines.append("- Amount Unknown — escalate: " + ", ".join(
            f"{t['transaction_id']} ({t['category']}, {t['status']}, amount blank)" for t in unresolved["unknown_amount"]
        ))
    if not (unresolved["pending"] or unresolved["disputed"] or unresolved["unknown_amount"]):
        lines.append("None.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Source Fetch Evidence")
    lines.append(f"Report generated: {generated_at}")
    lines.append("")
    for role in ("transactions", "budget", "revenue"):
        meta = fetch_meta[role]
        lines.append(
            f"- **{role.title()}** — `{meta['sheet_url']}` (spreadsheet id `{meta['spreadsheet_id']}`, "
            f"{meta['tab_identity']}); fetched {meta['fetched_at']}; "
            f"{meta['row_count']} rows; source_version(s): {meta['source_versions']}"
        )
    lines.append("")

    lines.append("## Business-Rule Notes (from stakeholder interview)")
    lines.append(
        "- Starting/closing cash balance reconciliation is intentionally not part of this brief: "
        "the Finance and Operations Manager does not net Posted/Pending/Disputed into one cash total, "
        "so no starting/closing balance check is performed or expected."
    )
    lines.append(
        "- Month-to-date budget comparison uses **posted-status Transaction Ledger rows by category**, "
        "not the Revenue Snapshot. Revenue Snapshot is normalized to "
        "`deliverables/normalized/revenue.csv` for dated revenue/outstanding-balance tracking, "
        "but is not an input to the budget-variance calculation."
    )
    lines.append(
        "- Unknown/blank transaction amounts are never assumed to be zero: they keep their status "
        "for review but are excluded from every numeric total (cash and MTD budget)."
    )
    lines.append("")

    lines.append("## Definition of Done — Self-Checking Gate")
    lines.append(
        "1. **Separate Cash Totals:** Did calculate three distinct totals without netting. "
        f"*Evidence: Posted {fmt_usd(cash_summary['totals']['posted'])}, "
        f"Pending {fmt_usd(cash_summary['totals']['pending'])}, "
        f"Disputed {fmt_usd(cash_summary['totals']['disputed'])} — computed independently "
        f"from Transaction Ledger rows dated {target_date.isoformat()}.*"
    )
    neg_ids = [t["transaction_id"] for t, amt in cash_summary["buckets"]["posted"] if amt < 0]
    lines.append(
        "2. **Negative Numbers Preserved:** Did preserve negative values as Credits/Corrections "
        f"rather than converting to absolute value. *Evidence: {', '.join(neg_ids) if neg_ids else 'none present on target date'}.*"
    )
    mat_desc = "; ".join(
        f"{v['category'].title()} {fmt_pct(v['pct'])}/{fmt_usd(v['variance'])}" for v in material
    ) or "none"
    notmat_desc = "; ".join(
        f"{v['category'].title()} {fmt_pct(v['pct'])}/{fmt_usd(v['variance'])}" for v in not_material
    ) or "none"
    lines.append(
        "3. **Materiality Threshold Strictness:** Did limit \"Material Variance\" strictly to cases "
        f">10% AND >$500. *Evidence: Included — {mat_desc}. Excluded for failing the strict thresholds — {notmat_desc}.*"
    )
    lines.append(
        "4. **No Assumed Figures:** Did use only exact figures from the freshly fetched sources, "
        "zero estimates or placeholders. *Evidence: normalized row counts — "
        f"transactions {fetch_meta['transactions']['row_count']}, "
        f"budget {fetch_meta['budget']['row_count']}, "
        f"revenue {fetch_meta['revenue']['row_count']}.*"
    )
    unk_ids = [t["transaction_id"] for t in unresolved["unknown_amount"]]
    lines.append(
        "5. **Unknown Amounts Excluded:** Did keep unknown-amount transactions in their status "
        "category while excluding them from all numeric sums. "
        f"*Evidence: {', '.join(unk_ids) if unk_ids else 'none present on target date'}.*"
    )
    lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transactions-url", default=DEFAULT_URLS["transactions"])
    parser.add_argument("--budget-url", default=DEFAULT_URLS["budget"])
    parser.add_argument("--revenue-url", default=DEFAULT_URLS["revenue"])
    parser.add_argument(
        "--target-date",
        default=None,
        help="YYYY-MM-DD to brief on. Defaults to the previous business day "
             "relative to the run date (weekends skipped; no holiday calendar).",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Deliverables directory. Defaults to <skill-root>/../deliverables.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    skill_root = __file__.rsplit("/scripts/", 1)[0]
    out_dir = args.out_dir or f"{skill_root}/../deliverables"

    urls = {
        "transactions": args.transactions_url,
        "budget": args.budget_url,
        "revenue": args.revenue_url,
    }

    try:
        fetched = fetch_all(urls)

        for role in ("transactions", "budget", "revenue"):
            meta = fetched[role]
            versions = sorted({row.get("source_version", "") for row in meta["rows"] if row.get("source_version")})
            meta["source_versions"] = ", ".join(versions) if versions else "n/a"
            print(
                f"[fetch-evidence] role={role} url={meta['sheet_url']} "
                f"spreadsheet_id={meta['spreadsheet_id']} tab={meta['tab_identity']} "
                f"fetched_at={meta['fetched_at']} row_count={meta['row_count']} "
                f"source_version={meta['source_versions']}",
                file=sys.stderr,
            )

        transactions = normalize_rows(fetched["transactions"]["rows"], TRANSACTIONS_FIELDS)
        budget = normalize_rows(fetched["budget"]["rows"], BUDGET_FIELDS)
        revenue = normalize_rows(fetched["revenue"]["rows"], REVENUE_FIELDS)

        if args.target_date:
            target_date = dt.date.fromisoformat(args.target_date)
        else:
            target_date = previous_business_day(dt.date.today())
        target_str = target_date.isoformat()

        day_transactions = [t for t in transactions if t["date"] == target_str]
        if not day_transactions:
            raise SafeFailure(
                f"No Transaction Ledger entries found for target date {target_str}. "
                "Per the 'Missing Source of Truth' rule, refusing to fabricate a brief. "
                "Re-run with --target-date once the ledger has entries for the intended day."
            )

        cash_summary = build_cash_summary(day_transactions)
        variances = build_budget_variances(transactions, budget, target_date)
        unresolved = build_unresolved_queue(cash_summary)

        os.makedirs(f"{out_dir}/normalized", exist_ok=True)
        write_csv(f"{out_dir}/normalized/transactions.csv", TRANSACTIONS_FIELDS, transactions)
        write_csv(f"{out_dir}/normalized/budget.csv", BUDGET_FIELDS, budget)
        write_csv(f"{out_dir}/normalized/revenue.csv", REVENUE_FIELDS, revenue)

        generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") + "Z"
        report = render_report(target_date, cash_summary, variances, unresolved, fetched, generated_at)
        with open(f"{out_dir}/report.md", "w", encoding="utf-8") as handle:
            handle.write(report)

        print(f"Wrote {out_dir}/normalized/transactions.csv, budget.csv, revenue.csv, and report.md", file=sys.stderr)
        return 0

    except SafeFailure as exc:
        print(f"SAFE FAILURE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
