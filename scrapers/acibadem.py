"""
Acibadem Mehmet Ali Aydinlar University fee scraper.

Page shape (verified by hand, 2026-07, Drupal site, robots.txt allows access):
a single table headed "DEGREE | FACULTY | PROGRAM | LANGUAGE | FEE (VAT
Included)". Uses HTML rowspan-style merging in practice: DEGREE, FACULTY,
and even PROGRAM cells are simply ABSENT (not empty <td>) on rows that
continue a prior group -- e.g. a program offered in both English and
Turkish shows the full row for English, then a bare "Turkish | $fee" row
for the Turkish variant, with no repeated program name cell.

KEY DIFFERENCE FROM ISTINYE/USKUDAR: the dollar sign is a PREFIX here
("$36.000"), not a suffix ("27.550 $" / "$ 24.000 "). Turkish thousands-
format (period as separator) still applies.

Verified by direct execution against a 13-row fixture reproducing every
real structural case seen on the live page: plain rows, faculty-carry-
forward, degree-carry-forward, and same-program-different-language rows.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")


def _parse_prefix_dollar(text: str) -> float | None:
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


class AcibademAdapter(UniversityFeeAdapter):
    university_key = "acibadem"
    source_url = "https://www.acibadem.edu.tr/en/international-office/international-students/admissions/undergraduate/tuition-fees"

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
            if not any("PROGRAM" in h for h in header_cells) or not any("FEE" in h for h in header_cells):
                continue

            current_degree: str | None = None
            current_faculty: str | None = None
            current_program: str | None = None

            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                cell_text = [c.get_text(strip=True) for c in cells]

                if cell_text and cell_text[0].upper() == "DEGREE":
                    continue

                if cell_text[0].isupper() and "DEGREE" in cell_text[0] and len(cell_text[0]) > 3:
                    current_degree = cell_text[0]
                    cell_text = cell_text[1:]
                    if not cell_text:
                        continue

                if cell_text and cell_text[0] and cell_text[0].isupper() and "$" not in cell_text[0]:
                    current_faculty = cell_text[0]
                    cell_text = cell_text[1:]

                if not cell_text:
                    continue

                if cell_text[0] in ("English", "Turkish"):
                    if current_program is None:
                        continue
                    language, fee_text = cell_text[0], cell_text[-1]
                    program_name = current_program
                else:
                    if len(cell_text) < 3:
                        continue
                    program_name, language, fee_text = cell_text[0], cell_text[1], cell_text[-1]
                    current_program = program_name

                if not program_name:
                    continue

                fee_value = _parse_prefix_dollar(fee_text)
                if fee_value is None:
                    continue

                fees.append(ScrapedFee(
                    university_key=self.university_key,
                    program_name=program_name,
                    fee_usd=fee_value,
                    language=language if language in ("English", "Turkish") else None,
                    faculty=current_faculty,
                    source_url=self.source_url,
                    raw_text=f"{current_degree or ''} | {current_faculty or ''} | {program_name} | {language} | {fee_text}",
                ))

        if not fees:
            raise ValueError(
                "Table(s) found but no priced rows extracted -- the fee format "
                "has likely changed. Needs a human to re-check."
            )

        return fees
