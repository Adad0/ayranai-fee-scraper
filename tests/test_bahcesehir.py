"""
Tests for the Bahçeşehir (BAU) adapter — deliberately covers the
school/faculty-level granularity issue, since that's the main way this
adapter differs from İstinye's per-program one.
"""

import pytest
from pathlib import Path

from scrapers.bahcesehir import BahcesehirAdapter

# Fixture is UTF-8 and contains non-ASCII (€, Turkish characters) — every
# read_text() call below passes encoding="utf-8" explicitly. Without it,
# Path.read_text() falls back to the platform's locale-preferred codec (seen
# locally: Windows cp1256), which mangles the € in the Pilotage fixture entry
# into unmatched bytes and silently drops that row from parse() results —
# a test-environment artifact, not a real scrapers/bahcesehir.py bug (verified
# against the live page: the real HTTP response declares charset=UTF-8, which
# requests.get().text honors correctly).
FIXTURE = Path(__file__).parent / "fixtures" / "bahcesehir_sample.html"


def test_parses_school_level_and_named_program_entries():
    adapter = BahcesehirAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    names = {f.program_name for f in fees}
    assert "School of Medicine" in names
    assert "Artificial Intelligence Engineering" in names  # named exception, not a school
    assert "School of Engineering & Natural Sciences" in names


def test_school_level_fee_flagged_as_not_per_department():
    """This is the important one: BAU's 'School of Engineering & Natural
    Sciences' fee applies to many internal departments (Computer Engineering,
    Industrial Engineering, etc.) at once. The adapter must NOT pretend this
    is a specific department's fee — the raw_text must carry a visible note
    so the review step doesn't silently apply it 1:1 like İstinye's data."""
    adapter = BahcesehirAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    school_fee = next(f for f in fees if f.program_name == "School of Engineering & Natural Sciences")
    assert school_fee.fee_usd == 9000.0
    assert "school/faculty-level rate, not per-department" in school_fee.raw_text


def test_whole_program_vs_per_year_basis_both_parse():
    adapter = BahcesehirAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    mba = next(f for f in fees if "Executive MBA" in f.program_name)
    medicine = next(f for f in fees if f.program_name == "School of Medicine")
    assert mba.fee_usd == 18000.0       # whole-program figure
    assert medicine.fee_usd == 28000.0  # per-year figure
    # both parse to a plain float — the "whole program" vs "per year" distinction
    # is preserved only in raw_text (basis=...) for the review step to interpret,
    # NOT silently normalized here (annualizing a whole-program fee requires
    # knowing the program length, which is a review-step judgment call).


def test_pilotage_euro_component_tolerated_but_flagged_in_raw_text():
    """Pilotage has a mixed-currency fee ('$9,000 + €22,000 per year') — we
    don't attempt to parse/convert the Euro portion (no live FX rate source
    in this scraper), but we must not crash on it, and the raw_text must
    retain the full original string so a human reviewing it sees the Euro
    component wasn't silently dropped."""
    adapter = BahcesehirAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    pilotage = next(f for f in fees if f.program_name == "Pilotage")
    assert pilotage.fee_usd == 9000.0  # USD portion only — the € part is not represented as a number anywhere
    assert "€22,000" in pilotage.raw_text  # but it's visible in the raw text for a human to notice


def test_school_level_entries_use_program_name_as_faculty():
    """For school-level rows, the program_name IS the school/faculty — e.g.
    'School of Engineering & Natural Sciences' applies to every department
    under it, so faculty should just echo the program_name."""
    adapter = BahcesehirAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))

    ens = next(f for f in fees if f.program_name == "School of Engineering & Natural Sciences")
    assert ens.faculty == "School of Engineering & Natural Sciences"

    medicine = next(f for f in fees if f.program_name == "School of Medicine")
    assert medicine.faculty == "School of Medicine"


def test_named_exceptions_leave_faculty_null():
    """Artificial Intelligence Engineering and Pilotage are individually-
    priced programs, not school-level rows — we don't know which faculty
    administratively owns them, so faculty must stay null rather than
    guessing."""
    adapter = BahcesehirAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))

    ai_eng = next(f for f in fees if f.program_name == "Artificial Intelligence Engineering")
    assert ai_eng.faculty is None

    pilotage = next(f for f in fees if f.program_name == "Pilotage")
    assert pilotage.faculty is None


def test_non_fee_nav_link_is_skipped_not_misparsed():
    """'View All Programs' also links to /programs/ but isn't a fee card —
    must not appear in results or crash the parser."""
    adapter = BahcesehirAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    names = {f.program_name for f in fees}
    assert not any("View All" in n for n in names)


def test_raises_loudly_if_no_program_links_found():
    adapter = BahcesehirAdapter()
    with pytest.raises(ValueError, match="No links pointing to /programs/"):
        adapter.parse("<html><body>nothing here</body></html>")


def test_raises_loudly_if_links_exist_but_none_match_fee_pattern():
    """Distinguishes 'site restructured entirely' (no /programs/ links) from
    'the fee-text format itself changed' (links exist, but text no longer
    matches name+duration+price) — both are real failures, but this test
    ensures the SECOND kind is also caught, not just the first."""
    adapter = BahcesehirAdapter()
    html = '<a href="/programs/?keyword=x">Some Program With No Price Shown</a>'
    with pytest.raises(ValueError, match="none matched the expected fee-text pattern"):
        adapter.parse(html)
