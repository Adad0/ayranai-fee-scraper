"""
Tests for the Üsküdar adapter — covers the third distinct structural pattern
(one table per faculty, with the fee column HEADER TEXT differing between
undergrad ["PER YEAR"] and graduate ["FULL PROGRAM"] tables).
"""

import pytest
from pathlib import Path

from scrapers.uskudar import UskudarAdapter, _parse_dollar_amount

# Fixture is UTF-8 and contains Turkish characters (Üsküdar, TÖMER, etc.) —
# every read_text() call below passes encoding="utf-8" explicitly, since
# Path.read_text() otherwise falls back to the platform's locale-preferred
# codec (seen locally: Windows cp1256), silently mangling non-ASCII text.
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
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    medicine_en = next(f for f in fees if f.program_name == "Medicine (English)")
    assert medicine_en.fee_usd == 24000.0


def test_graduate_table_uses_full_program_column_not_installment():
    """Graduate tables label the same concept 'FULL PROGRAM' instead of
    'PER YEAR' — the adapter must recognize both header variants, and must
    still avoid the installment/advance-payment columns."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    ce_thesis = next(f for f in fees if "Computer Engineering (English)-Thesis" in f.program_name)
    assert ce_thesis.fee_usd == 5700.0  # FULL PROGRAM, not 5130 (advance) or 2850 (installment)


def test_language_extracted_from_program_name_suffix():
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    en = next(f for f in fees if f.program_name == "Software Engineering (English)")
    tr = next(f for f in fees if f.program_name == "Forensic Science (Turkish)")
    assert en.language == "English"
    assert tr.language == "Turkish"


def test_faculty_captured_from_first_row_single_cell():
    """The live page has NO <caption> element anywhere — the faculty/institute
    name is instead the sole cell of each table's first <tr> (a single
    <th colSpan="N">...</th>), followed by a second <tr> with the real column
    headers. That text must be attached as `faculty` to every row parsed from
    that table."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))

    medicine_en = next(f for f in fees if f.program_name == "Medicine (English)")
    assert medicine_en.faculty == "FACULTY OF MEDICINE"

    ce_en = next(f for f in fees if f.program_name == "Computer Engineering (English)")
    assert ce_en.faculty == "FACULTY OF ENGINEERING AND NATURAL SCIENCES"

    ce_thesis = next(f for f in fees if "Computer Engineering (English)-Thesis" in f.program_name)
    assert ce_thesis.faculty == "INSTITUTE OF SCIENCES"


def test_column_index_not_shifted_by_faculty_title_cell():
    """Regression guard: an earlier version computed the fee-column index
    from every <th> in the whole table (including the faculty-title cell),
    which shifted every column index off by one and silently picked PAYMENT
    IN ADVANCE instead of TUITION FEE / PER YEAR. The header row must be
    read in isolation from the faculty-title row."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    medicine_en = next(f for f in fees if f.program_name == "Medicine (English)")
    assert medicine_en.fee_usd == 24000.0  # not 21600 (payment in advance)


def test_br_separated_header_still_matches_full_program_column():
    """Some graduate tables use <br/> instead of '/' between 'TUITION FEE'
    and 'FULL PROGRAM'; get_text(' ', strip=True) turns that into a single
    space, not a slash, which must still be recognized as the fee column
    (an earlier version silently dropped this table entirely)."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    applied_psych = next(f for f in fees if "Applied Psychology" in f.program_name)
    assert applied_psych.fee_usd == 7000.0  # FULL PROGRAM, not 6300 (advance)
    assert applied_psych.faculty == "INSTITUTE OF SOCIAL SCIENCES"


def test_three_column_table_still_parses():
    """Smaller tables (English Preparatory School, TÖMER) only have 3
    columns (PROGRAM | Duration | TUITION FEE / FULL PROGRAM) — an earlier
    version's column-index math broke on these and silently dropped the
    whole table."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    prep = next(f for f in fees if f.program_name == "English Preparatory Class")
    assert prep.fee_usd == 4400.0
    assert prep.faculty == "ENGLISH PREPARATORY SCHOOL"


def test_skips_tables_without_a_recognizable_fee_column():
    """The 'SOME UNRELATED INFO TABLE' has no PROGRAM/fee columns — must be
    silently skipped without crashing, and contribute zero fee records."""
    adapter = UskudarAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
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
