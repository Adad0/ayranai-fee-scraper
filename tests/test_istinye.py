"""
Tests for the İstinye adapter's PARSE logic, run against a saved HTML fixture
(no live network call — see fixtures/istinye_sample.html's header comment for
why). This validates the parsing algorithm; a separate live smoke-test job in
CI (scheduled, not on every push) hits the real URL to catch upstream
structure changes.
"""

import pytest
from pathlib import Path

from scrapers.istinye import IstinyeAdapter, _parse_try_lira_style_usd

# Fixture is UTF-8 and contains Turkish characters (İstanbul, etc.) — every
# read_text() call below passes encoding="utf-8" explicitly, since
# Path.read_text() otherwise falls back to the platform's locale-preferred
# codec (seen locally: Windows cp1256), silently mangling non-ASCII text.
FIXTURE = Path(__file__).parent / "fixtures" / "istinye_sample.html"


def test_price_parsing_turkish_thousands_format():
    """The classic bug this guards against: naively parsing '27.550 $' as
    float('27.550') = 27.55 instead of 27550.0 — the period is a thousands
    separator here, not a decimal point."""
    assert _parse_try_lira_style_usd("27.550 $") == 27550.0
    assert _parse_try_lira_style_usd("8.000 $") == 8000.0
    assert _parse_try_lira_style_usd("-") is None
    assert _parse_try_lira_style_usd("") is None


def test_parses_known_program_with_expected_fee():
    """Cross-checked against the existing production value: İstinye Medicine
    (English) is $27,550 in AyranAI's current UNIVERSITY_META data. If this
    test's expected value ever needs to change, it should be because the
    fixture was deliberately updated to reflect a real fee change — not
    because someone "fixed" the parser to make a wrong number look right."""
    adapter = IstinyeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))

    medicine_en = next(f for f in fees if f.program_name == "Medicine" and f.language == "English")
    assert medicine_en.fee_usd == 27550.0


def test_skips_faculty_header_rows():
    """'Faculty of Medicine' etc. must never appear as a program name — these
    are section headers, not real programs."""
    adapter = IstinyeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    program_names = {f.program_name for f in fees}
    assert "Faculty of Medicine" not in program_names
    assert "Faculty of Engineering and Natural Sciences" not in program_names


def test_faculty_header_text_is_carried_forward_onto_program_rows():
    """The bold header row's text isn't just skipped — it's tracked as the
    current faculty and attached to every program row underneath it, until
    the next header row changes it."""
    adapter = IstinyeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))

    medicine_en = next(f for f in fees if f.program_name == "Medicine" and f.language == "English")
    assert medicine_en.faculty == "Faculty of Medicine"

    dentistry_en = next(f for f in fees if f.program_name == "Dentistry" and f.language == "English")
    assert dentistry_en.faculty == "Faculty of Dentistry"

    se_en = next(f for f in fees if f.program_name == "Software Engineering" and f.language == "English")
    assert se_en.faculty == "Faculty of Engineering and Natural Sciences"

    business = next(f for f in fees if f.program_name == "Business Administration")
    assert business.faculty == "Faculty of Economics and Administrative Sciences"


def test_skips_rows_with_no_price_listed():
    """Architecture (Turkish) has '-' for its fee in the fixture — a genuinely
    unpriced row (quota not yet open). Must be skipped, not recorded as $0
    (which would be worse than missing data — it would look like a real free
    program to whatever consumes this)."""
    adapter = IstinyeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    architecture_rows = [f for f in fees if f.program_name == "Architecture"]
    assert architecture_rows == []


def test_falls_back_to_installment_price_when_no_full_payment_listed():
    """Software Engineering rows in the fixture have an installment price but
    no full-payment figure (empty cell) — the parser must use the installment
    price rather than silently dropping the row."""
    adapter = IstinyeAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    se_en = next(f for f in fees if f.program_name == "Software Engineering" and f.language == "English")
    assert se_en.fee_usd == 8000.0


def test_raises_loudly_if_no_tables_found_at_all():
    """If the site's structure changes entirely (e.g. moved to a JS widget),
    the parser must raise — not silently return an empty list, which would
    be indistinguishable from 'this university has zero programs' (never true)."""
    adapter = IstinyeAdapter()
    with pytest.raises(ValueError, match="No <table>"):
        adapter.parse("<html><body><p>No tables here</p></body></html>")


def test_run_wraps_parse_failure_into_scrape_result_not_a_crash():
    """The .run() orchestrator (base.py) must catch parse() exceptions and
    turn them into a failed ScrapeResult, so one university's site-change
    doesn't crash the whole batch job."""
    adapter = IstinyeAdapter()
    adapter.fetch = lambda: "<html><body>no tables</body></html>"  # type: ignore
    result = adapter.run()
    assert result.ok is False
    assert "No <table>" in result.error
    assert result.fees == []
