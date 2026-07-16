"""
Tests for the Acibadem adapter -- covers the fourth distinct structural
pattern seen so far: prefix-dollar format ("$36.000" not "36.000 $"),
degree-level AND faculty-level carry-forward via rowspan, and same-program-
different-language continuation rows.
"""

import pytest
from pathlib import Path

from scrapers.acibadem import AcibademAdapter, _parse_prefix_dollar

FIXTURE = Path(__file__).parent / "fixtures" / "acibadem_sample.html"


def test_prefix_dollar_parsing_turkish_thousands_format():
    assert _parse_prefix_dollar("$36.000") == 36000.0
    assert _parse_prefix_dollar("$8.500") == 8500.0
    assert _parse_prefix_dollar("-") is None
    assert _parse_prefix_dollar("") is None


def test_parses_known_program_with_expected_fee():
    adapter = AcibademAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    medicine = next(f for f in fees if f.program_name == "Medicine")
    assert medicine.fee_usd == 36000.0
    assert medicine.language == "English"
    assert medicine.faculty == "SCHOOL OF MEDICINE"


def test_faculty_carried_forward_across_multiple_programs():
    adapter = AcibademAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    eng_programs = [f for f in fees if f.faculty == "FACULTY OF ENGINEERING AND NATURAL SCIENCES"]
    names = {f.program_name for f in eng_programs}
    assert names == {"Biomedical Engineering", "Computer Engineering", "Molecular Biology and Genetics"}


def test_degree_level_carried_forward():
    adapter = AcibademAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    culinary = next(f for f in fees if f.program_name == "Culinary")
    comp_prog = next(f for f in fees if f.program_name == "Computer Programming")
    assert "ASSOCIATE DEGREE" in culinary.raw_text
    assert "ASSOCIATE DEGREE" in comp_prog.raw_text


def test_same_program_different_language_continuation():
    adapter = AcibademAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    psych_rows = [f for f in fees if f.program_name == "Psychology"]
    languages = {f.language for f in psych_rows}
    assert languages == {"English", "Turkish"}
    assert all(f.fee_usd == 8500.0 for f in psych_rows)
    nursing_rows = [f for f in fees if f.program_name == "Nursing"]
    assert {f.language for f in nursing_rows} == {"English", "Turkish"}


def test_raises_loudly_if_no_tables_found_at_all():
    adapter = AcibademAdapter()
    with pytest.raises(ValueError, match="No <table>"):
        adapter.parse("<html><body><p>No tables here</p></body></html>")


def test_run_wraps_parse_failure_into_scrape_result_not_a_crash():
    adapter = AcibademAdapter()
    adapter.fetch = lambda: "<html><body>no tables</body></html>"
    result = adapter.run()
    assert result.ok is False
    assert "No <table>" in result.error
    assert result.fees == []
