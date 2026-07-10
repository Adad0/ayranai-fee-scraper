"""
Üsküdar University fee scraper.

STRUCTURAL SHAPE — a THIRD distinct pattern from İstinye and Bahçeşehir:
The page (a Next.js site, allowed by robots.txt — verified 2026-07) renders
one separate HTML <table> PER FACULTY/INSTITUTE, each with its own caption
(e.g. "FACULTY OF MEDICINE", "INSTITUTE OF SCIENCES"). Unlike İstinye (one
big table with embedded bold header-rows) or Bahçeşehir (anchor-tag cards),
Üsküdar cleanly separates faculties into distinct <table> elements, each
with columns: PROGRAM | Duration | TUITION FEE/PER YEAR | PAYMENT IN ADVANCE
| TUITION FEE/PER TERM (undergrad tables), or PROGRAM | Duration | TUITION
FEE/FULL PROGRAM | PAYMENT IN ADVANCE | TUITION FEE/INSTALLMENT (graduate
tables — different column labels for the same "fee up front" concept).

We take "TUITION FEE/PER YEAR" (undergrad) or "TUITION FEE/FULL PROGRAM"
(graduate) as the canonical annual_fee_usd, NOT "PAYMENT IN ADVANCE" (a
discounted early-payment rate) or "PER TERM"/"INSTALLMENT" (a fractional
figure) — these would silently understate the real annual cost if picked
by the wrong column.

Same Turkish-thousands-format bug applies here too ("$ 24.000" = $24,000,
not $24.00) — reuses the same parsing guard as the İstinye adapter.

Program names in the (English) / (Turkish) suffix format match AyranAI's
internal department naming closely — e.g. "Computer Engineering (English)",
"Management Information Systems (Turkish)" — making this one of the more
directly reusable sources.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")

# Column header text that identifies the "real annual/full fee" column,
# checked in this priority order (first match wins) — deliberately NOT
# "payment in advance" or "per term"/"installment", which understate the cost.
_TARGET_COLUMN_HEADERS = ("tuition fee / per year", "tuition fee / full program", "tuition fee     full program")


def _parse_dollar_amount(text: str) -> float | None:
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


class UskudarAdapter(UniversityFeeAdapter):
    university_key = "uskudar"
    source_url = "https://international.uskudar.edu.tr/en/tuition-fee"

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
                "No <table> elements found — the site's structure has likely "
                "changed (e.g. moved the PDF-only route). Needs a human check."
            )

        fees: list[ScrapedFee] = []
        for table in tables:
            header_cells = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not header_cells or "program" not in header_cells:
                continue  # not a fee table (e.g. an unrelated table elsewhere on the page)

            # Find which column index holds the annual/full fee (varies between
            # undergrad and graduate tables — see module docstring).
            fee_col_idx = None
            for i, h in enumerate(header_cells):
                if any(target in h for target in _TARGET_COLUMN_HEADERS):
                    fee_col_idx = i
                    break
            if fee_col_idx is None:
                continue  # a table without a recognizable fee column — skip, don't guess

            caption = table.find("caption")
            faculty = caption.get_text(strip=True) if caption else None

            rows = table.find_all("tr")[1:]  # skip header row
            for row in rows:
                cells = row.find_all("td")
                if len(cells) <= fee_col_idx:
                    continue
                cell_text = [c.get_text(strip=True) for c in cells]
                program_name = cell_text[0]
                if not program_name:
                    continue

                fee_value = _parse_dollar_amount(cell_text[fee_col_idx])
                if fee_value is None:
                    continue  # genuinely unpriced row — skip, don't fabricate

                language = None
                if "(english)" in program_name.lower():
                    language = "English"
                elif "(turkish)" in program_name.lower():
                    language = "Turkish"

                fees.append(ScrapedFee(
                    university_key=self.university_key,
                    program_name=program_name,
                    fee_usd=fee_value,
                    language=language,
                    faculty=faculty,
                    source_url=self.source_url,
                    raw_text=" | ".join(cell_text),
                ))

        if not fees:
            raise ValueError(
                "Tables were found but none yielded any priced rows — the fee "
                "format has likely changed. Needs a human to re-check."
            )

        return fees
