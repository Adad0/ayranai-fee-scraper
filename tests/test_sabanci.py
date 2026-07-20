"""
Tests for the Sabanci adapter -- the simplest structure seen so far: a
single flat rate for ALL undergraduate programs, no per-department
breakdown exists on the source page at all.
"""

import pytest
from pathlib import Path

from scrapers.sabanci import SabanciAdapter, _parse_plain_usd

FIXTURE = Path(__file__).parent / "fixtures" / "sabanci_sample.html"


def test_plain_usd_parsing():
    assert _parse_plain_usd("36500") == 36500.0
    assert _parse_plain_usd("") is None


def test_parses_single_flat_fee():
    adapter = SabanciAdapter()
    fees = adapter.parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(fees) == 1
    assert fees[0].program_name == "All Undergraduate Programs"
    assert fees[0].fee_usd == 36500.0
    assert fees[0].language is None
    assert fees[0].faculty is None


def test_raises_loudly_if_no_tables_found_at_all():
    adapter = SabanciAdapter()
    with pytest.raises(ValueError, match="No <table>"):
        adapter.parse("<html><body><p>No tables here</p></body></html>")


def test_run_wraps_parse_failure_into_scrape_result_not_a_crash():
    adapter = SabanciAdapter()
    adapter.fetch = lambda: "<html><body>no tables</body></html>"
    result = adapter.run()
    assert result.ok is False
    assert "No <table>" in result.error
    assert result.fees == []
