"""
Koc University fee scraper.

Page shape (verified by hand, 2026-07, WordPress site, robots.txt allows
access): a single table with columns "College Name | Program Name |
Tuition Fee in USD | Tuition Fee in TL". College name uses the same
carry-forward pattern seen elsewhere.

KEY DIFFERENCES: USD figures are PLAIN integers with no thousands
separator ("59000"). The TL column exists but is deliberately ignored.
No language column -- all programs are English-taught. Program names
retain the school's own code suffix as scraped (e.g. "MD Medicine (MEDI)").
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


class KocAdapter(UniversityFeeAdapter):
    university_key = "koc"
    source_url = "https://international.ku.edu.tr/undergraduate-programs/tuition-and-scholarships/"

    def fetch(self) -> str:
        resp = requests.get(self.source_url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AyranAI-FeeScraper/1.0; +https://ayranai.com)"
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
            header_cells = [th.get_text(strip=True).upper() for th in table.find_all("th")]
            if not any("PROGRAM" in h for h in header_cells) or not any("USD" in h for h in header_cells):
                continue

            current_college: str | None = None

            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                cell_text = [c.get_text(strip=True) for c in cells]

                if cell_text and "COLLEGE NAME" in cell_text[0].upper():
                    continue

                if len(cell_text) >= 4:
                    current_college = cell_text[0]
                    cell_text = cell_text[1:]

                if len(cell_text) < 3:
                    continue

                program_name, usd_text = cell_text[0], cell_text[1]
                if not program_name:
                    continue

                fee_value = _parse_plain_usd(usd_text)
                if fee_value is None:
                    continue

                fees.append(ScrapedFee(
                    university_key=self.university_key,
                    program_name=program_name,
                    fee_usd=fee_value,
                    language=None,
                    faculty=current_college,
                    source_url=self.source_url,
                    raw_text=f"{current_college or ''} | {program_name} | {usd_text}",
                ))

        if not fees:
            raise ValueError(
                "Table(s) found but no priced rows extracted -- the fee format "
                "has likely changed. Needs a human to re-check."
            )

        return fees
