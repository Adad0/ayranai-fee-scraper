"""
Tests for the Ozyegin adapter -- covers a SIXTH distinct structural pattern:
no <table> exists at all, program name and fee are on SEPARATE consecutive
text blocks ("Computer Engineering" then "$25,000" as its own line, never
concatenated), comma-thousands USD format (not the Turkish period-thousands
format used elsewhere), and faculty headers detected by substring match
rather than table structure.

Also covers a real trap on the live page: a "Scholarship Rate" preamble
appears BEFORE the first faculty header, with its own bare "$X,XXX" lines
that must NOT be captured as programs -- confirmed against a real fetch of
the live page, not assumed. See scrapers/ozyegin.py's module docstring for
the full story (an earlier version of this fixture wrongly assumed name
and fee were concatenated into one string).
"""

import pytest
from pathlib import Path

from scrapers.ozyegin import OzyeginAdapter, _parse_comma_usd

FIXTURE = Path(__file__).parent / "fixtures" / "ozyegin_sample.html"


def test_comma_usd_parsing():
    assert _parse_comma_usd("25,000") == 25000.0
    assert _parse_comma_usd("16,500") == 16500.0
    assert _parse_comma_usd("") is None


def test_parses_known_program_with_expected_fee():
    adapter = OzyeginAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    ce = next(f for f in fees if f.program_name == "Computer Engineering")
    assert ce.fee_usd == 25000.0
    assert ce.faculty == "Faculty of Engineering"


def test_named_exception_professional_flight_different_fee():
    adapter = OzyeginAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    flight = next(f for f in fees if f.program_name == "Professional Flight")
    assert flight.fee_usd == 16500.0
    assert flight.faculty == "Faculty of Aviation and Space Sciences"


def test_faculty_carried_forward_across_multiple_programs():
    adapter = OzyeginAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    business_programs = [f for f in fees if f.faculty == "Faculty of Business"]
    names = {f.program_name for f in business_programs}
    assert names == {"Business Administration", "Management Information Systems", "Economics"}


def test_preamble_scholarship_tiers_not_captured_as_programs():
    """The 'Scholarship Rate' preamble (before any faculty header) has its
    own bare '$X,XXX' lines ('40% scholarship' / '$15,000', an
    accommodation-fee sentence / '$2,000') -- these must NOT show up as
    programs. Program/fee pairing only applies once inside a real faculty
    section (current_faculty is set)."""
    adapter = OzyeginAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    names = {f.program_name for f in fees}
    assert "40% scholarship" not in names
    assert not any(f.fee_usd == 15000.0 and f.faculty is None for f in fees)
    assert not any(f.fee_usd == 2000.0 for f in fees)


def test_trailing_prose_after_last_program_not_captured():
    """After 'Aviation Management'/'$25,000', the page has three lines of
    prose (scholarship-ineligibility note, a Euro-denominated flight-school
    fee) before the next faculty header -- none of these are bare
    '$X,XXX' USD lines, so none should produce a spurious ScrapedFee."""
    adapter = OzyeginAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    names = {f.program_name for f in fees}
    assert not any("Ayjet" in n or "Scholarships are not applicable" in n for n in names)


def test_raises_loudly_if_no_program_fee_pattern_found():
    adapter = OzyeginAdapter()
    with pytest.raises(ValueError, match="no program-name-line-followed-by-bare-fee-line pattern"):
        adapter.parse("<html><body><p>Nothing relevant here</p></body></html>")


def test_run_wraps_parse_failure_into_scrape_result_not_a_crash():
    adapter = OzyeginAdapter()
    adapter.fetch = lambda: "<html><body><p>no matches</p></body></html>"
    result = adapter.run()
    assert result.ok is False
    assert result.fees == []
