"""
Tests for the Ozyegin adapter -- covers a SIXTH distinct structural pattern:
no <table> exists at all, program name + fee appear concatenated in a
single text block ("Computer Engineering$25,000"), comma-thousands USD
format (not the Turkish period-thousands format used elsewhere), and
faculty headers detected by substring match rather than table structure.

UNCERTAINTY FLAG: the exact live DOM structure could not be directly
confirmed -- this fixture is a best-effort reconstruction. MUST be
verified against a real GitHub Actions run before trusting any proposals
this generates in production.
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


def test_raises_loudly_if_no_program_fee_pattern_found():
    adapter = OzyeginAdapter()
    with pytest.raises(ValueError, match="no 'ProgramName\\$Amount' pattern"):
        adapter.parse("<html><body><p>Nothing relevant here</p></body></html>")


def test_run_wraps_parse_failure_into_scrape_result_not_a_crash():
    adapter = OzyeginAdapter()
    adapter.fetch = lambda: "<html><body><p>no matches</p></body></html>"
    result = adapter.run()
    assert result.ok is False
    assert result.fees == []
