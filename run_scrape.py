"""
run_scrape.py — the monthly orchestrator.

WHAT THIS DOES:
1. Runs every registered university adapter (see ADAPTERS below).
2. Compares each result against the last known values (stored in
   data/last_known_fees.json — committed to this repo, acting as a simple
   append-only-ish snapshot rather than a database, since this repo has no
   database of its own by design — see ARCHITECTURE.md).
3. Produces a human-readable review report (data/review_<date>.md) listing
   every CHANGE (old value -> new value) and every FAILURE (site down,
   structure changed) — never applies anything automatically.
4. For every detected CHANGE, also writes/refreshes a row in AyranAI's own
   Supabase `fee_change_proposals` table (status='pending'), so admins can
   review and approve/reject from the Fee Review dashboard instead of only
   reading the markdown report by hand. This is ADDITIVE — the JSON snapshot
   and markdown report are produced exactly as before regardless of whether
   the Supabase write succeeds.

WHY NOT AUTO-APPLY: a scraping bug (wrong column picked, site briefly showing
a promotional discount, a JS-rendering timeout returning a cached old page)
must never silently become "the price a student sees." Fee accuracy matters
more than scraper convenience. The Supabase row is a PROPOSAL awaiting human
approval, not a write to the live universities/university_programs data —
identical in spirit to the markdown report, just also queryable from the
admin dashboard.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from scrapers.acibadem import AcibademAdapter
from scrapers.bahcesehir import BahcesehirAdapter
from scrapers.base import ScrapedFee
from scrapers.istinye import IstinyeAdapter

# KocAdapter import commented out along with its ADAPTERS entry below — see
# the note there for why (IP-range blocking, not a code problem). The class
# itself is untouched and fully correct; uncomment both lines to re-enable.
# from scrapers.koc import KocAdapter
from scrapers.uskudar import UskudarAdapter

# Loads a local .env file if present (for local/manual runs); a no-op in CI,
# where SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are real environment
# variables set via GitHub Actions Secrets, not a .env file.
load_dotenv()

ADAPTERS = [
    IstinyeAdapter(),
    BahcesehirAdapter(),
    UskudarAdapter(),
    AcibademAdapter(),
    # KocAdapter(),  # commented out — see "Known blocked universities
    # (IP-range, not robots.txt)" in README.md. Confirmed 2026-07: both a
    # plain requests.get() (with a realistic browser User-Agent) and
    # Playwright headless Chromium get 403 Forbidden specifically from
    # GitHub Actions' runner IPs, while the identical request succeeds from
    # other networks — this is IP-range/datacenter WAF blocking, not a
    # parsing bug or a robots.txt opt-out. scrapers/koc.py and its tests are
    # untouched and fully correct; this is commented out (not deleted)
    # because a known, understood failure every month isn't useful signal.
    # Re-enable by uncommenting this line AND the import above once run
    # from a different network path (proxy, self-hosted runner, etc.).
    # Add one line here per new university. That's the entire integration
    # surface for adding #6, #7, ... #44 — write the adapter file (see
    # scrapers/istinye.py, scrapers/bahcesehir.py, scrapers/uskudar.py,
    # scrapers/acibadem.py, or scrapers/koc.py as templates for the
    # structural shapes seen so far: per-program table with embedded header
    # rows, anchor-tag cards, one-table-per-faculty, rowspan-continuation
    # (degree+faculty+program all carried forward), and rowspan-continuation
    # (single carried-forward column, plain-integer fee, no language column),
    # add its test fixture + tests, then register it here.
    #
    # ALSO add the new university_key -> canonical name mapping below in
    # UNIVERSITY_KEY_TO_CANONICAL_NAME, or its Supabase fee proposals will be
    # written under the raw slug instead of the real Turkish name.
    #
    # KNOWN BLOCKED (robots.txt disallows automated access, verified 2026-07):
    # Altınbaş (international.altinbas.edu.tr), Biruni (int.biruni.edu.tr).
    # Do not build adapters for these without a different, permission-based
    # approach (e.g. reaching out to request API/data access) — respecting
    # robots.txt is a hard rule for this project, not a suggestion.
]

# This repo's adapters use simple ASCII slugs (ScrapedFee.university_key);
# AyranAI's own schema (UNIVERSITY_META / Supabase university_programs /
# fee_change_proposals) is keyed by the full canonical Turkish name. This is
# the one explicit translation point between the two conventions — update it
# whenever a new adapter is registered above.
UNIVERSITY_KEY_TO_CANONICAL_NAME = {
    "istinye": "İstinye Üniversitesi",
    "bahcesehir": "Bahçeşehir Üniversitesi",
    "uskudar": "Üsküdar Üniversitesi",
    "acibadem": "Acıbadem Mehmet Ali Aydınlar Üniversitesi",
    "koc": "Koç Üniversitesi",
}

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOT_PATH = DATA_DIR / "last_known_fees.json"


def _safe_print(message: str) -> None:
    """print() that can never raise — university names/raw scraped text
    contain Turkish characters (İ, ş, ğ, ç, ö, ü) that some console codepages
    (seen locally: Windows cp1256) can't encode, which would otherwise crash
    the run from inside a FAILURE log line — exactly the opposite of what
    that log line exists for. Falls back to a '?'-substituted ASCII-safe
    version instead of raising."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(message.encode(encoding, errors="replace").decode(encoding))


def _load_last_known() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text())


def _save_snapshot(snapshot: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True))


def _get_supabase_client():
    """Create the Supabase service-role client, or return None (with a clear
    log line) if credentials are missing or the client can't be constructed.

    Deliberately lazy (imported and called only when actually needed, not at
    module import time) and deliberately never raises — a missing/bad
    SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY, or a broken network, must not
    prevent the local JSON snapshot + markdown report from being written.
    Same "fail loud but isolated" philosophy as scrapers/base.py's per-
    adapter error handling, applied to this new failure mode.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        _safe_print(
            "SUPABASE SYNC SKIPPED: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY "
            "not set. Local JSON snapshot + markdown report are still written normally."
        )
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:  # noqa: BLE001 — client construction must never crash the run
        _safe_print(f"SUPABASE SYNC FAILED (client init): {e}. Continuing without Supabase sync.")
        return None


def _sync_fee_proposal(supabase, university_name: str, fee: ScrapedFee, old_fee_usd: float | None) -> None:
    """Insert a new fee_change_proposals row for this detected change, or —
    if an identical PENDING proposal for the same (university_name,
    program_name, language) already exists — refresh its new_fee_usd/
    source_url/raw_text/scraped_at in place instead of inserting a duplicate.

    This only matters if the scraper runs more than once before an admin
    reviews the queue; the identity fields (university_name, program_name,
    language, old_fee_usd, status) are left untouched on refresh — only the
    freshly-scraped values move forward.

    Never raises — one proposal's sync failure must not stop the batch or
    crash the run, mirroring the per-adapter isolation in scrapers/base.py.
    """
    try:
        query = (
            supabase.table("fee_change_proposals")
            .select("id")
            .eq("university_name", university_name)
            .eq("program_name", fee.program_name)
            .eq("status", "pending")
        )
        query = query.is_("language", "null") if fee.language is None else query.eq("language", fee.language)
        existing = query.execute().data

        if existing:
            supabase.table("fee_change_proposals").update({
                "new_fee_usd": fee.fee_usd,
                "source_url": fee.source_url,
                "raw_text": fee.raw_text,
                "scraped_at": fee.scraped_at,
                "faculty": fee.faculty,
            }).eq("id", existing[0]["id"]).execute()
        else:
            supabase.table("fee_change_proposals").insert({
                "university_name": university_name,
                "program_name": fee.program_name,
                "language": fee.language,
                "old_fee_usd": old_fee_usd,
                "new_fee_usd": fee.fee_usd,
                "source_url": fee.source_url,
                "raw_text": fee.raw_text,
                "status": "pending",
                "scraped_at": fee.scraped_at,
                "faculty": fee.faculty,
            }).execute()
    except Exception as e:  # noqa: BLE001 — a single proposal sync failure must not crash the run
        _safe_print(
            f"SUPABASE SYNC FAILED for {university_name} :: {fee.program_name} "
            f"({fee.language or 'any'}): {e}"
        )


def main() -> int:
    last_known = _load_last_known()
    new_snapshot: dict = {}
    changes: list[str] = []
    failures: list[str] = []

    supabase = _get_supabase_client()

    for adapter in ADAPTERS:
        result = adapter.run()

        if not result.ok:
            failures.append(f"❌ **{adapter.university_key}** — {result.error} (source: {adapter.source_url})")
            # CRITICAL: on failure, carry forward the OLD snapshot data for this
            # university unchanged, rather than dropping it. A failed scrape
            # must never look like "this university now has zero fee data."
            for key, val in last_known.items():
                if key.startswith(f"{adapter.university_key}::"):
                    new_snapshot[key] = val
            continue

        for fee in result.fees:
            key = f"{fee.university_key}::{fee.program_name}::{fee.language or 'any'}"
            old = last_known.get(key)
            new_snapshot[key] = {
                "fee_usd": fee.fee_usd,
                "source_url": fee.source_url,
                "raw_text": fee.raw_text,
                "scraped_at": fee.scraped_at,
            }

            is_new = old is None
            is_changed = old is not None and old["fee_usd"] != fee.fee_usd

            if is_new:
                changes.append(f"🆕 **{key}** — new: ${fee.fee_usd:,.0f} (never seen before)")
            elif is_changed:
                changes.append(f"🔄 **{key}** — ${old['fee_usd']:,.0f} → **${fee.fee_usd:,.0f}**")

            if (is_new or is_changed) and supabase is not None:
                canonical_name = UNIVERSITY_KEY_TO_CANONICAL_NAME.get(fee.university_key)
                if canonical_name is None:
                    _safe_print(
                        f"WARNING: no canonical name mapping for university_key={fee.university_key!r} "
                        f"in UNIVERSITY_KEY_TO_CANONICAL_NAME — writing the Supabase proposal "
                        f"with the raw key instead. Add the mapping so it matches "
                        f"university_programs.university_name."
                    )
                    canonical_name = fee.university_key
                old_fee_usd = old["fee_usd"] if old is not None else None
                _sync_fee_proposal(supabase, canonical_name, fee, old_fee_usd)

    _save_snapshot(new_snapshot)

    report_path = DATA_DIR / f"review_{date.today().isoformat()}.md"
    report_lines = [
        f"# Fee scrape review — {date.today().isoformat()}",
        "",
        "**Nothing in this report has been applied to production. Review and "
        "manually update AyranAI's data for anything confirmed real.**",
        "",
        f"## Changes requiring review ({len(changes)})",
        "",
        *(changes or ["_No fee changes detected this run._"]),
        "",
        f"## Scrape failures ({len(failures)})",
        "",
        *(failures or ["_All adapters ran successfully._"]),
        "",
    ]
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print(f"Report written to {report_path}")
    print(f"{len(changes)} change(s), {len(failures)} failure(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
