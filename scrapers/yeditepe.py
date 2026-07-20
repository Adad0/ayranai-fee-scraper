"""
Yeditepe University fee scraper.

Page shape (verified by hand, 2026-07, Drupal site, robots.txt allows
access): a rich per-program HTML table headed "Program | Fee | %25 | %50"
(discount columns vary by row -- some programs only ever show a 50%
discount tier, others only 25%; both are ignored here, we only take the
base Fee column). Also includes coarser "Faculty of X" blanket-rate rows
interleaved alphabetically among individual program rows (e.g. "Faculty of
Communication | 18.000$" sits as its own row separate from "Advertising
Design and Communication (Bachelor) | 18.000$" underneath it) -- these are
captured too (same pattern as Bahcesehir's school-level rows), the review
step can decide how to use the coarser entries.

Price format is suffix-dollar with Turkish thousands separator ("18.000$"),
matching Istinye's convention exactly -- same parsing regex reused here.

The page also has separate tables for Preparatory, Associate Degree, and
Graduate programs, each with the same "Program | Fee | ..." shape -- the
parser handles all tables on the page uniformly, not just the first one.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

_PRICE_RE = re.compile(r"([\d.]+)\s*\$")


def _parse_suffix_dollar(text: str) -> float | None:
    text = text.strip()
    if not text or text == "-":
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    digits = m.group(1).replace(".", "")
    try:
        return float(digits)
    except ValueError:
        return None


class YeditepeAdapter(UniversityFeeAdapter):
    university_key = "yeditepe"
    source_url = "https://yeditepe.edu.tr/en/prospective-students/fees"

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
            header_cells = [th.get_text(strip=True).upper() for th in table.find_all("th")]
            if not any("PROGRAM" in h for h in header_cells) or not any("FEE" in h for h in header_cells):
                continue

            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                cell_text = [c.get_text(" ", strip=True) for c in cells]
                program_name, fee_text = cell_text[0], cell_text[1]
                if not program_name:
                    continue

                fee_value = _parse_suffix_dollar(fee_text)
                if fee_value is None:
                    continue

                fees.append(ScrapedFee(
                    university_key=self.university_key,
                    program_name=program_name,
                    fee_usd=fee_value,
                    language=None,
                    faculty=None,
                    source_url=self.source_url,
                    raw_text=f"{program_name} | {fee_text}",
                ))

        if not fees:
            raise ValueError(
                "Table(s) found but no priced rows extracted -- the fee format "
                "has likely changed. Needs a human to re-check."
            )

        return fees
