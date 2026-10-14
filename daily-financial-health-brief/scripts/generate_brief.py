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
    match = re.search(r".*?/d/([a-zA-Z0-9_-]+)", sheet_url)
    if not match:
        raise SafeFailure(f"Could not parse a spreadsheet ID out of URL: {sheet_url}")
    base, sheet_id = match.group(0), match.group(1)
    gid_match = re.search(r"[?&#]gid=([0-9]+)", sheet_url)
    url = f"{base}/export?format=csv"
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


def has_amount_status_mismatch(txn: dict) -> bool:
    """True when the source's own `amount_status` column disagrees with
    whether `amount` actually parses (e.g. the sheet says "unknown" but the
    amount parses fine, or vice versa). Either signal alone could be the
    wrong one, so a disagreement is never resolved by silently trusting
    one side -- it's treated as unknown, same as a blank amount."""
    parsed = parse_amount(txn.get("amount"))
    declared_unknown = (txn.get("amount_status") or "").strip().lower() == "unknown"
    return (parsed is None) != declared_unknown


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


def month_to_date_transactions(all_transactions: list[dict], target_date: dt.date) -> list[dict]:
    """Transaction Ledger rows from the 1st of target_date's month through
    target_date itself (inclusive) -- the same MTD scoping used for budget
    variances, reused here for the Unresolved Items Queue and for
    extending status validation beyond just the single target date."""
    month_prefix = target_date.strftime("%Y-%m")
    target_str = target_date.isoformat()
    return [t for t in all_transactions if t["date"].startswith(month_prefix) and t["date"] <= target_str]


def _bucket_and_validate(txns: list[dict]) -> tuple[dict, list]:
    buckets = {status: [] for status in CASH_STATUSES}
    unknown_amount = []

    for txn in txns:
        status = (txn["status"] or "").strip().lower()
        amount = parse_amount(txn["amount"])
        mismatch = has_amount_status_mismatch(txn)
        if amount is None or mismatch:
            reason = "amount_status mismatch" if mismatch else "amount blank"
            unknown_amount.append((txn, reason))
            continue
        if status not in CASH_STATUSES:
            raise SafeFailure(
                f"Transaction {txn['transaction_id']} on {txn['date']} has an "
                f"unrecognized status '{txn['status']}' (expected posted/pending/"
                "disputed). Escalate for manual categorization before rerunning."
            )
        buckets[status].append((txn, amount))

    return buckets, unknown_amount


def build_cash_summary(day_transactions: list[dict], month_transactions: list[dict]) -> dict:
    """Cash totals (Posted/Pending/Disputed $, shown in the Cash Summary
    section) are scoped strictly to day_transactions -- the target date.
    Status validation is scoped to the whole month being scanned
    (month_transactions, a superset that includes day_transactions): a
    transaction anywhere in that range with an unrecognized status halts
    the run, not just one dated --target-date. The month-scoped buckets
    and unknown-amount list feed the Unresolved Items Queue instead of
    the day-scoped ones, which stay target-date only."""
    month_buckets, month_unknown_amount = _bucket_and_validate(month_transactions)
    day_buckets, day_unknown_amount = _bucket_and_validate(day_transactions)

    day_totals = {
        status: sum((amt for _, amt in items), Decimal("0")) for status, items in day_buckets.items()
    }

    return {
        "buckets": day_buckets,
        "totals": day_totals,
        "unknown_amount": day_unknown_amount,
        "month_buckets": month_buckets,
        "month_unknown_amount": month_unknown_amount,
    }


def build_posted_comparison(
    all_transactions: list[dict],
    target_posted_total: Decimal,
    comparison_date: dt.date,
) -> dict:
    """Signed change in Posted cash between --target-date and the required,
    explicit --comparison-date (see build_cash_summary for why an
    unrecognized status on either date still blocks the run). A comparison
    date with zero Transaction Ledger rows doesn't corrupt anything else in
    the report, so it's flagged rather than failing the run."""
    comparison_str = comparison_date.isoformat()
    comparison_day_transactions = [t for t in all_transactions if t["date"] == comparison_str]

    comparison_available = bool(comparison_day_transactions)
    comparison_total = None
    signed_change = None
    comparison_credit_ids = []
    if comparison_available:
        comparison_summary = build_cash_summary(comparison_day_transactions, comparison_day_transactions)
        comparison_total = comparison_summary["totals"]["posted"]
        signed_change = target_posted_total - comparison_total
        comparison_credit_ids = [
            t["transaction_id"] for t, amt in comparison_summary["buckets"]["posted"] if amt < 0
        ]

    return {
        "comparison_date": comparison_date,
        "comparison_available": comparison_available,
        "comparison_total": comparison_total,
        "signed_change": signed_change,
        "comparison_credit_ids": comparison_credit_ids,
    }


REVENUE_COMPARISON_METRICS = ("collected_revenue", "outstanding_balance")


def most_recent_revenue_observation(
    revenue_rows: list[dict], metric: str, as_of_date: dt.date
) -> tuple[dt.date, Decimal] | None:
    """The most recent real Revenue Snapshot value for `metric` on or before
    as_of_date. The Revenue Snapshot updates sparsely by design -- it does
    not get a row for every day the way the Transaction Ledger does -- so
    falling back to the most recent real observation, clearly labeled with
    its own date, is not the same as assuming zero for an unknown amount:
    one is a real (if slightly stale) number, the other has no factual
    basis at all. Returns None if there's no observation at or before
    as_of_date (e.g. the date predates the Revenue Snapshot's first row)."""
    as_of_str = as_of_date.isoformat()
    candidates = [
        (row["date"], parse_amount(row["value"]))
        for row in revenue_rows
        if row["metric"] == metric and row["date"] <= as_of_str
    ]
    candidates = [(date_str, value) for date_str, value in candidates if value is not None]
    if not candidates:
        return None
    best_date_str, best_value = max(candidates, key=lambda item: item[0])
    return dt.date.fromisoformat(best_date_str), best_value


def build_revenue_comparison(
    revenue_rows: list[dict], target_date: dt.date, comparison_date: dt.date
) -> dict:
    """Two independent as-of comparisons -- collected_revenue and
    outstanding_balance -- each target-date vs. comparison-date, exactly
    like build_posted_comparison() but for the Revenue Snapshot. These are
    never combined into a single relationship or ratio between the two
    metrics; each is reported on its own."""
    result = {}
    for metric in REVENUE_COMPARISON_METRICS:
        target_obs = most_recent_revenue_observation(revenue_rows, metric, target_date)
        comparison_obs = most_recent_revenue_observation(revenue_rows, metric, comparison_date)
        signed_change = (
            target_obs[1] - comparison_obs[1] if target_obs and comparison_obs else None
        )
        result[metric] = {
            "target_as_of": target_obs[0] if target_obs else None,
            "target_value": target_obs[1] if target_obs else None,
            "comparison_as_of": comparison_obs[0] if comparison_obs else None,
            "comparison_value": comparison_obs[1] if comparison_obs else None,
            "signed_change": signed_change,
        }
    return result


def build_budget_variances(all_transactions: list[dict], budget_rows: list[dict], target_date: dt.date) -> dict:
    month_prefix = target_date.strftime("%Y-%m")

    mtd_posted = defaultdict(lambda: Decimal("0"))
    mtd_txn_ids = defaultdict(list)
    for txn in month_to_date_transactions(all_transactions, target_date):
        if (txn["status"] or "").strip().lower() != "posted":
            continue
        if has_amount_status_mismatch(txn):
            continue  # never trust a figure the source itself flags as disputed
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

    # Categories with real posted spend but no Budget Targets row for this
    # period can't produce a variance at all -- without this, they would
    # just vanish from the report instead of being flagged. The rest of
    # the variances above are unaffected and remain trustworthy.
    orphan_categories = [
        {
            "category": category,
            "mtd_posted": spend,
            "txn_ids": sorted(mtd_txn_ids[category]),
        }
        for category, spend in sorted(mtd_posted.items())
        if category not in budget_by_category
    ]

    return {"variances": variances, "orphan_categories": orphan_categories}


def build_unresolved_queue(cash_summary: dict) -> dict:
    """Scoped to the whole month being scanned (cash_summary['month_buckets']
    / ['month_unknown_amount']), not just the target date -- see
    build_cash_summary."""
    pending = sorted(
        (t for t, _ in cash_summary["month_buckets"]["pending"]), key=lambda t: t["transaction_id"]
    )
    disputed = sorted(
        (t for t, _ in cash_summary["month_buckets"]["disputed"]), key=lambda t: t["transaction_id"]
    )
    unknown = sorted(cash_summary["month_unknown_amount"], key=lambda item: item[0]["transaction_id"])
    return {"pending": pending, "disputed": disputed, "unknown_amount": unknown}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def fmt_usd(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def fmt_pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def fmt_revenue_observation(label: str, requested_date: dt.date, as_of_date: dt.date | None, value: Decimal | None) -> str:
    if as_of_date is None:
        return f"- **{label} ({requested_date.isoformat()}):** no data available on or before this date"
    if as_of_date == requested_date:
        return f"- **{label} ({requested_date.isoformat()}):** {fmt_usd(value)}"
    return (
        f"- **{label} ({requested_date.isoformat()}):** {fmt_usd(value)} "
        f"(no entry for this date; most recent real observation is as of {as_of_date.isoformat()})"
    )


def render_report(
    target_date: dt.date,
    cash_summary: dict,
    posted_comparison: dict,
    revenue_comparison: dict,
    variances: list[dict],
    orphan_categories: list[dict],
    unresolved: dict,
    fetch_meta: dict,
    generated_at: str,
) -> str:
    lines = []
    lines.append("# Quillhaven Academy — Daily Financial Health Briefing")
    lines.append(
        f"**Target Date:** {target_date.isoformat()} | **Draft for:** Finance and Operations "
        "Manager | **Prepared for:** Aug 12, 2026 Operations Meeting"
    )
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
        unk = ", ".join(
            f"{t['transaction_id']} ({t['status']}, {reason})"
            for t, reason in cash_summary["unknown_amount"]
        )
        lines.append(f"- **Amount Unknown (excluded from totals, escalate):** {unk}")
    lines.append("")

    lines.append("## Daily Posted Total Comparison")
    comparison_date = posted_comparison["comparison_date"]
    lines.append(
        f"- **{target_date.isoformat()} Posted:** {fmt_usd(cash_summary['totals']['posted'])}"
        + (f" (Credit/Correction: {', '.join(credits)})" if credits else "")
    )
    if posted_comparison["comparison_available"]:
        sign = "+" if posted_comparison["signed_change"] >= 0 else ""
        comparison_credits = posted_comparison["comparison_credit_ids"]
        lines.append(
            f"- **{comparison_date.isoformat()} Posted:** {fmt_usd(posted_comparison['comparison_total'])}"
            + (f" (Credit/Correction: {', '.join(comparison_credits)})" if comparison_credits else "")
        )
        lines.append(f"- **Signed Change:** {sign}{fmt_usd(posted_comparison['signed_change'])}")
    else:
        lines.append(
            f"- **{comparison_date.isoformat()}:** no comparison data available "
            "(zero Transaction Ledger rows for this date)"
        )
    lines.append("")

    lines.append("## Collected Revenue vs. Outstanding Balance (as-of comparison)")
    lines.append(
        "Each metric below is compared target-date vs. comparison-date "
        "independently -- never combined into a single relationship or "
        "ratio between collected revenue and outstanding balance."
    )
    lines.append("")
    for metric, title in (
        ("collected_revenue", "Collected Revenue"),
        ("outstanding_balance", "Outstanding Balance"),
    ):
        comp = revenue_comparison[metric]
        lines.append(f"**{title}**")
        lines.append(
            fmt_revenue_observation(title, target_date, comp["target_as_of"], comp["target_value"])
        )
        lines.append(
            fmt_revenue_observation(title, comparison_date, comp["comparison_as_of"], comp["comparison_value"])
        )
        if comp["signed_change"] is not None:
            sign = "+" if comp["signed_change"] >= 0 else ""
            lines.append(f"- **Signed Change:** {sign}{fmt_usd(comp['signed_change'])}")
        else:
            lines.append("- **Signed Change:** n/a (no data available for one or both dates)")
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

    lines.append("## Unbudgeted MTD Spend (no matching Budget Targets line)")
    if orphan_categories:
        lines.append("| Department | MTD Posted | Transactions |")
        lines.append("|---|---|---|")
        for o in orphan_categories:
            lines.append(
                f"| {o['category'].title()} | {fmt_usd(o['mtd_posted'])} | {', '.join(o['txn_ids'])} |"
            )
        lines.append("")
        lines.append(
            "These categories have posted spend for "
            f"{target_date.strftime('%Y-%m')} but no Budget Targets row for that "
            "period, so no variance can be calculated for them. The budget "
            "variances above are unaffected and remain accurate for the "
            "categories that do have a budget line."
        )
    else:
        lines.append("None — every category with posted spend this month has a matching budget line.")
    lines.append("")

    lines.append(f"## Unresolved Items Queue (month-to-date, {target_date.strftime('%Y-%m')})")
    if unresolved["pending"]:
        lines.append("- Pending (Operations owner): " + ", ".join(
            f"{t['transaction_id']} ({t['date']}, {fmt_usd(parse_amount(t['amount']))})"
            for t in unresolved["pending"]
        ))
    if unresolved["disputed"]:
        lines.append("- Disputed (Operations owner): " + ", ".join(
            f"{t['transaction_id']} ({t['date']}, {fmt_usd(parse_amount(t['amount']))})"
            for t in unresolved["disputed"]
        ))
    if unresolved["unknown_amount"]:
        lines.append("- Amount Unknown (Operations owner) — escalate: " + ", ".join(
            f"{t['transaction_id']} ({t['date']}, {t['category']}, {t['status']}, {reason})"
            for t, reason in unresolved["unknown_amount"]
        ))
    if not (unresolved["pending"] or unresolved["disputed"] or unresolved["unknown_amount"]):
        lines.append("None.")
    lines.append("")

    lines.append("## Unresolved Items Queue — Limitations")
    lines.append(
        "1. **Snapshot only:** This reflects this run's fetch only. Anything "
        "that changes in the Transaction Ledger afterward won't appear "
        "here until the next run."
    )
    lines.append(
        "2. **Informational, not corrective:** This queue doesn't resolve "
        "anything itself. The Operations owner has to actually act outside "
        "this skill."
    )
    lines.append(
        "3. **Current month only:** Scoped to the current calendar month. "
        "An unresolved item from an earlier month wouldn't appear here at "
        "all, even though it's still outstanding."
    )
    lines.append(
        "4. **amount_status mismatch has a blind spot:** That check only "
        "catches a disagreement between the two signals (amount and "
        "amount_status). It can't catch a case where both are simply "
        "wrong in the same consistent way."
    )
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
    unk_ids = [t["transaction_id"] for t, _ in unresolved["unknown_amount"]]
    lines.append(
        "5. **Unknown Amounts Excluded:** Did keep unknown-amount transactions in their status "
        "category while excluding them from all numeric sums. "
        f"*Evidence (month-to-date): {', '.join(unk_ids) if unk_ids else 'none present month-to-date'}.*"
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
        "--comparison-date",
        default=None,
        help="YYYY-MM-DD to compare --target-date's Posted cash total "
             "against. Required -- never defaulted or inferred (the Finance "
             "and Operations Manager uses the exact dates given in each "
             "request, for financial consistency and alignment with the "
             "intended review period).",
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
        if not args.comparison_date:
            raise SafeFailure(
                "--comparison-date is required (no default). Per the Finance "
                "and Operations Manager, comparison dates are never inferred "
                "-- each request must specify the exact date to keep "
                "financial comparisons aligned with the intended review "
                "period. Re-run with --comparison-date YYYY-MM-DD."
            )
        comparison_date = dt.date.fromisoformat(args.comparison_date)

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

        month_transactions = month_to_date_transactions(transactions, target_date)
        cash_summary = build_cash_summary(day_transactions, month_transactions)
        posted_comparison = build_posted_comparison(
            transactions, cash_summary["totals"]["posted"], comparison_date
        )
        revenue_comparison = build_revenue_comparison(revenue, target_date, comparison_date)
        budget_result = build_budget_variances(transactions, budget, target_date)
        variances = budget_result["variances"]
        orphan_categories = budget_result["orphan_categories"]
        unresolved = build_unresolved_queue(cash_summary)

        os.makedirs(f"{out_dir}/normalized", exist_ok=True)
        write_csv(f"{out_dir}/normalized/transactions.csv", TRANSACTIONS_FIELDS, transactions)
        write_csv(f"{out_dir}/normalized/budget.csv", BUDGET_FIELDS, budget)
        write_csv(f"{out_dir}/normalized/revenue.csv", REVENUE_FIELDS, revenue)

        generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") + "Z"
        report = render_report(
            target_date, cash_summary, posted_comparison, revenue_comparison, variances,
            orphan_categories, unresolved, fetched, generated_at
        )
        with open(f"{out_dir}/report.md", "w", encoding="utf-8") as handle:
            handle.write(report)

        print(f"Wrote {out_dir}/normalized/transactions.csv, budget.csv, revenue.csv, and report.md", file=sys.stderr)
        return 0

    except SafeFailure as exc:
        print(f"SAFE FAILURE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
