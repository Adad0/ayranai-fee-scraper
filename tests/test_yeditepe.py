"""
Tests for the Yeditepe adapter -- covers a rich per-program table with
suffix-dollar pricing (matching Istinye's format), a coarser "Faculty of X"
blanket-rate row appearing alongside individual program rows, and multiple
tables on the same page (undergraduate, associate degree, preparatory).
"""

import pytest
from pathlib import Path

from scrapers.yeditepe import YeditepeAdapter, _parse_suffix_dollar

FIXTURE = Path(__file__).parent / "fixtures" / "yeditepe_sample.html"


def test_suffix_dollar_parsing_turkish_thousands_format():
    assert _parse_suffix_dollar("18.000$") == 18000.0
    assert _parse_suffix_dollar("73.000$") == 73000.0
    assert _parse_suffix_dollar("-") is None


def test_parses_known_program_with_expected_fee():
    adapter = YeditepeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    medicine = next(f for f in fees if f.program_name == "Medicine (Bachelor)")
    assert medicine.fee_usd == 40000.0
    dentistry_faculty = next(f for f in fees if f.program_name == "Faculty of Dentistry")
    assert dentistry_faculty.fee_usd == 73000.0


def test_faculty_blanket_row_captured_alongside_individual_programs():
    adapter = YeditepeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    names = {f.program_name for f in fees}
    assert "Faculty of Communication" in names
    assert "Advertising Design and Communication (Bachelor)" in names


def test_dual_degree_program_name_preserved_verbatim():
    adapter = YeditepeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    ddup = next(f for f in fees if "DDUP" in f.program_name)
    assert ddup.fee_usd == 18000.0
    assert "University of North Carolina Wilmington" in ddup.program_name


def test_multiple_tables_on_page_all_parsed():
    adapter = YeditepeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    names = {f.program_name for f in fees}
    assert "Automative Technology (Associated Degree)" in names
    assert "English Preparatory Program" in names


def test_discount_columns_ignored_only_base_fee_used():
    adapter = YeditepeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    dentistry = next(f for f in fees if f.program_name == "Faculty of Dentistry")
    assert dentistry.fee_usd == 73000.0


def test_raises_loudly_if_no_tables_found_at_all():
    adapter = YeditepeAdapter()
    with pytest.raises(ValueError, match="No <table>"):
        adapter.parse("<html><body><p>No tables here</p></body></html>")


def test_run_wraps_parse_failure_into_scrape_result_not_a_crash():
    adapter = YeditepeAdapter()
    adapter.fetch = lambda: "<html><body>no tables</body></html>"
    result = adapter.run()
    assert result.ok is False
    assert "No <table>" in result.error
    assert result.fees == []
