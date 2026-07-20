"""
Sabanci University fee scraper.

Page shape (verified by hand, 2026-07, Drupal site, robots.txt allows
access): the simplest structure seen so far -- a single table with ONE row:
"Annual Tuition Fee | 36500 USD". This applies university-wide to ALL
undergraduate programs; Sabanci does not publish per-department or
per-faculty tuition variation on this page (confirmed: the source page's
own text says the fee applies to "all different bachelor's majors").

DESIGN DECISION: since there is no real per-program breakdown to scrape,
program_name is set to the literal descriptive string "All Undergraduate
Programs" -- matching what the source actually communicates, rather than
fabricating a per-department list that doesn't exist on this page. faculty
and language are left None (not specified on this page).

USD figure is a plain integer, no thousands separator ("36500"), same
convention as Koc's page.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

_USD_RE = re.compile(r"^\d{3,7}$")


def _parse_plain_usd(text: str) -> float | None:
    text = text.strip()
    if not text or not _USD_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


class SabanciAdapter(UniversityFeeAdapter):
    university_key = "sabanci"
    source_url = "https://iro.sabanciuniv.edu/en/tuition-fee"

    def fetch(self) -> str:
        resp = requests.get(self.source_url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        resp.raise_for_status()
        return resp.text

    def parse(self, raw_content: str) -> list[ScrapedFee]:
        soup = BeautifulSoup(raw_content, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            raise ValueError(
                "No <table> elements found on the page -- the site's structure "
                "has likely changed. Needs a human to re-check the page."
            )

        fees: list[ScrapedFee] = []
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                cell_text = [c.get_text(" ", strip=True) for c in cells]
                if len(cell_text) < 2:
                    continue
                label, value_text = cell_text[0], cell_text[1]
                if "TUITION" not in label.upper():
                    continue

                digits_match = re.search(r"\d{3,7}", value_text)
                if not digits_match:
                    continue
                fee_value = _parse_plain_usd(digits_match.group(0))
                if fee_value is None:
                    continue

                fees.append(ScrapedFee(
                    university_key=self.university_key,
                    program_name="All Undergraduate Programs",
                    fee_usd=fee_value,
                    language=None,
                    faculty=None,
                    source_url=self.source_url,
                    raw_text=f"{label} | {value_text}",
                ))

        if not fees:
            raise ValueError(
                "Table(s) found but no priced rows extracted -- the fee format "
                "has likely changed. Needs a human to re-check."
            )

        return fees
