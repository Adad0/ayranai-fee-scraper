"""
Tests for the Koc adapter -- plain integer USD (no thousands separator),
TL column deliberately ignored, no language column, college-name
carry-forward via cell-count (not casing, since college names are
title-case here, not all-caps like Acibadem's faculty headers).
"""

import pytest
from pathlib import Path

from scrapers.koc import KocAdapter, _parse_plain_usd

FIXTURE = Path(__file__).parent / "fixtures" / "koc_sample.html"


def test_plain_usd_parsing_no_thousands_separator():
    assert _parse_plain_usd("59000") == 59000.0
    assert _parse_plain_usd("38000") == 38000.0
    assert _parse_plain_usd("") is None
    assert _parse_plain_usd("N/A") is None


def test_parses_known_program_with_expected_fee():
    adapter = KocAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    medicine = next(f for f in fees if "Medicine" in f.program_name)
    assert medicine.fee_usd == 59000.0
    assert medicine.faculty == "School of Medicine (SOM)"


def test_college_name_carried_forward_via_cell_count_not_casing():
    adapter = KocAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    cssh_programs = [f for f in fees if f.faculty == "College of Social Sciences and Humanities (CSSH)"]
    names = {f.program_name for f in cssh_programs}
    assert names == {
        "BA Archaeology and History of Art (ARHA)",
        "BA Philosophy (PHIL)",
        "BA Psychology (PSYC)",
    }


def test_case_college_name_all_caps_acronym_still_works():
    adapter = KocAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    case_programs = [f for f in fees if f.faculty == "CASE"]
    assert len(case_programs) == 2


def test_tl_column_is_not_used_for_fee_usd():
    adapter = KocAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    law = next(f for f in fees if "Law" in f.program_name)
    assert law.fee_usd == 38000.0


def test_language_is_none_not_guessed():
    adapter = KocAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    assert all(f.language is None for f in fees)


def test_raises_loudly_if_no_tables_found_at_all():
    adapter = KocAdapter()
    with pytest.raises(ValueError, match="No <table>"):
        adapter.parse("<html><body><p>No tables here</p></body></html>")


def test_run_wraps_parse_failure_into_scrape_result_not_a_crash():
    adapter = KocAdapter()
    adapter.fetch = lambda: "<html><body>no tables</body></html>"
    result = adapter.run()
    assert result.ok is False
    assert "No <table>" in result.error
    assert result.fees == []
