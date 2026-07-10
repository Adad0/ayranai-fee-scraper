"""
Tests for the Üsküdar adapter — covers the third distinct structural pattern
(one table per faculty, with the fee column HEADER TEXT differing between
undergrad ["PER YEAR"] and graduate ["FULL PROGRAM"] tables).
"""

import pytest
from pathlib import Path

from scrapers.uskudar import UskudarAdapter, _parse_dollar_amount

FIXTURE = Path(__file__).parent / "fixtures" / "uskudar_sample.html"


def test_price_parsing_turkish_thousands_format():
    assert _parse_dollar_amount("$ 24.000") == 24000.0
    assert _parse_dollar_amount("$ 4.200") == 4200.0
    assert _parse_dollar_amount("-") is None


def test_picks_per_year_column_not_payment_in_advance_or_per_term():
    """The critical column-selection bug this guards against: Medicine
    (English) has THREE dollar figures in its row ($24,000 / $21,600 /
    $12,000). Picking the wrong one silently understates the real annual
    fee by ~10-50%. Must pick PER YEAR (24000), not the discounted advance
    payment (21600) or the per-term figure (12000)."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text())
    medicine_en = next(f for f in fees if f.program_name == "Medicine (English)")
    assert medicine_en.fee_usd == 24000.0


def test_graduate_table_uses_full_program_column_not_installment():
    """Graduate tables label the same concept 'FULL PROGRAM' instead of
    'PER YEAR' — the adapter must recognize both header variants, and must
    still avoid the installment/advance-payment columns."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text())
    ce_thesis = next(f for f in fees if "Computer Engineering (English)-Thesis" in f.program_name)
    assert ce_thesis.fee_usd == 5700.0  # FULL PROGRAM, not 5130 (advance) or 2850 (installment)


def test_language_extracted_from_program_name_suffix():
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text())
    en = next(f for f in fees if f.program_name == "Software Engineering (English)")
    tr = next(f for f in fees if f.program_name == "Forensic Science (Turkish)")
    assert en.language == "English"
    assert tr.language == "Turkish"


def test_skips_tables_without_a_recognizable_fee_column():
    """The 'SOME UNRELATED INFO TABLE' has no PROGRAM/fee columns — must be
    silently skipped without crashing, and contribute zero fee records."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text())
    assert not any(f.program_name == "Insurance" for f in fees)


def test_raises_loudly_if_no_tables_at_all():
    adapter = UskudarAdapter()
    with pytest.raises(ValueError, match="No <table>"):
        adapter.parse("<html><body>nothing</body></html>")


def test_raises_loudly_if_tables_exist_but_none_are_fee_tables():
    """Distinguishes 'page has SOME tables, just not fee ones' (should raise,
    since we expected fee data and got none) from a normal successful parse."""
    adapter = UskudarAdapter()
    html = "<table><tr><th>Foo</th><th>Bar</th></tr><tr><td>1</td><td>2</td></tr></table>"
    with pytest.raises(ValueError, match="none yielded any priced rows|no tables"):
        adapter.parse(html)
