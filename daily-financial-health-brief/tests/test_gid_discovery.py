"""Covers discover_default_gid() and its use in fetch_sheet(): when a
sheet URL omits gid, the script used to hardcode the fetch evidence's tab
identity as "default sheet (gid=0)" -- but gid=0 doesn't exist on any of
the three real sheets (all return HTTP 400 if requested), and the real
default-tab gids are 386574278, 1184198158, and 653526310 respectively,
discoverable from each sheet's /htmlview page. Instead of asserting the
wrong default, the script now fetches /htmlview and parses the real gid.

Uses the local HTTP fixture server so no real sheet access is needed --
and specifically verifies discover_default_gid() queries the *same host*
as the sheet URL (not a hardcoded docs.google.com), which is what makes
this testable at all without hitting real Google Sheets.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

import generate_brief  # noqa: E402
from fixture_server import FixtureServer  # noqa: E402

TRANSACTIONS_CSV = (
    "transaction_id,date,account,category,description,amount,currency,"
    "status,source,source_version,amount_status\n"
    "TX-1,2026-01-02,Checking,Insurance,Row,100.00,USD,posted,test,v1,confirmed\n"
).encode("utf-8")


class DiscoverDefaultGidTest(unittest.TestCase):
    def test_discovers_the_real_gid_from_htmlview(self):
        routes = {"/d/FIXTURE_ID": ("text/csv", TRANSACTIONS_CSV)}
        with FixtureServer(routes) as server:
            base = server.url("/d/FIXTURE_ID")
            gid = generate_brief.discover_default_gid(base, "FIXTURE_ID")

        self.assertEqual(gid, "0")  # fixture_server.py's fixed fake gid

    def test_queries_the_sheet_s_own_host_not_a_hardcoded_one(self):
        # If this ever regresses to a hardcoded docs.google.com URL, this
        # call would try to hit the real internet for a fake sheet id and
        # fail outright rather than resolve against the fixture server.
        routes = {"/d/FIXTURE_ID": ("text/csv", TRANSACTIONS_CSV)}
        with FixtureServer(routes) as server:
            base = server.url("/d/FIXTURE_ID")
            gid = generate_brief.discover_default_gid(base, "FIXTURE_ID")
        self.assertEqual(gid, "0")

    def test_unregistered_sheet_raises_safe_failure_not_a_guessed_gid(self):
        routes = {"/d/OTHER_ID": ("text/csv", TRANSACTIONS_CSV)}
        with FixtureServer(routes) as server:
            base = server.url("/d/NOT_REGISTERED")
            with self.assertRaises(generate_brief.SafeFailure):
                generate_brief.discover_default_gid(base, "NOT_REGISTERED")


class FetchSheetGidIntegrationTest(unittest.TestCase):
    def test_fetch_sheet_without_a_gid_discovers_and_reports_one(self):
        routes = {"/d/FIXTURE_ID": ("text/csv", TRANSACTIONS_CSV)}
        with FixtureServer(routes) as server:
            sheet_url = server.url("/d/FIXTURE_ID")
            fetched = generate_brief.fetch_sheet(sheet_url)

        self.assertEqual(fetched["tab_identity"], "gid=0")
        self.assertIn("gid=0", fetched["export_url"])
        self.assertEqual(fetched["row_count"], 1)

    def test_fetch_sheet_with_an_explicit_gid_does_not_discover(self):
        routes = {"/d/FIXTURE_ID": ("text/csv", TRANSACTIONS_CSV)}
        with FixtureServer(routes) as server:
            sheet_url = server.url("/d/FIXTURE_ID") + "?gid=42"
            fetched = generate_brief.fetch_sheet(sheet_url)

        self.assertEqual(fetched["tab_identity"], "gid=42")


if __name__ == "__main__":
    unittest.main()
