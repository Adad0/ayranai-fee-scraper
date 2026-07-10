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
4. Never touches the main AyranAI Supabase database directly. A human reads
   the review report and manually updates fees they've confirmed are real
   changes (or, later, a separate small approved-import script could apply
   ONLY the entries a human has explicitly checked off — not built yet,
   deliberately, until this has run for a few months and proven reliable).

WHY NOT AUTO-APPLY: a scraping bug (wrong column picked, site briefly showing
a promotional discount, a JS-rendering timeout returning a cached old page)
must never silently become "the price a student sees." Fee accuracy matters
more than scraper convenience.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scrapers.bahcesehir import BahcesehirAdapter
from scrapers.istinye import IstinyeAdapter
from scrapers.uskudar import UskudarAdapter

ADAPTERS = [
    IstinyeAdapter(),
    BahcesehirAdapter(),
    UskudarAdapter(),
    # Add one line here per new university. That's the entire integration
    # surface for adding #4, #5, ... #44 — write the adapter file (see
    # scrapers/istinye.py, scrapers/bahcesehir.py, or scrapers/uskudar.py as
    # templates for the three structural shapes seen so far: per-program
    # table with embedded header rows, anchor-tag cards, and one-table-per-
    # faculty), add its test fixture + tests, then register it here.
    #
    # KNOWN BLOCKED (robots.txt disallows automated access, verified 2026-07):
    # Altınbaş (international.altinbas.edu.tr), Biruni (int.biruni.edu.tr).
    # Do not build adapters for these without a different, permission-based
    # approach (e.g. reaching out to request API/data access) — respecting
    # robots.txt is a hard rule for this project, not a suggestion.
]

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOT_PATH = DATA_DIR / "last_known_fees.json"


def _load_last_known() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text())


def _save_snapshot(snapshot: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True))


def main() -> int:
    last_known = _load_last_known()
    new_snapshot: dict = {}
    changes: list[str] = []
    failures: list[str] = []

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
            if old is None:
                changes.append(f"🆕 **{key}** — new: ${fee.fee_usd:,.0f} (never seen before)")
            elif old["fee_usd"] != fee.fee_usd:
                changes.append(f"🔄 **{key}** — ${old['fee_usd']:,.0f} → **${fee.fee_usd:,.0f}**")

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
