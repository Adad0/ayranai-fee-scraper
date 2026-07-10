"""
İstinye University fee scraper.

Page shape (verified by hand, 2026-07): a Drupal-rendered page with a series
of HTML <table> elements. The undergraduate table has columns:
  Name of Program | Duration | Quota | Medium of Instruction |
  Installment Payment (Annual) | Full Payment (Annual) | Campus
Faculty section headers appear as bold rows spanning the table width — but
NOT consistently as a single colspan'd <td> (verified by direct fetch,
2026-07). The live page mixes two markup styles: "Faculty of Humanities and
Social Sciences" and five others use <td colspan="7"><strong>...</strong></td>
(one real <td>), while "Faculty of Medicine", "Faculty of Dentistry", and
"Faculty of Pharmacy" instead use SEVEN separate <td> cells — one with the
name in <strong>, the other six just a blank space — to hit the same visual
width. A cell-count check alone (len(cells) == 1) only catches the first
style; the second style used to fall through to normal-row parsing, find no
price in any of its seven empty-ish cells, and get silently skipped without
ever updating current_faculty — leaving Medicine/Dentistry/Pharmacy programs
with faculty=None. Detect both styles by checking whether every cell after
the first is blank, not by counting cells.

We take "Full Payment (Annual)" as the canonical annual_fee_usd when present
(it's the discounted lump-sum figure, and it's what the existing AyranAI
UNIVERSITY_META data already stores — confirmed by cross-checking: this
scraper's İstinye Medicine (English) result matches the system's existing
$27,550 exactly). When a row has no Full Payment figure (some programs only
publish one price), we fall back to Installment Payment.

Numbers are formatted Turkish-style ("27.550 $" = 27,550, period as
thousands separator) — do NOT parse with a naive float() or you'll silently
divide the real value by 1000.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

_PRICE_RE = re.compile(r"([\d.]+)\s*\$")


def _parse_try_lira_style_usd(text: str) -> float | None:
    """Parses '27.550 $' -> 27550.0. Returns None if no price found in the cell."""
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


class IstinyeAdapter(UniversityFeeAdapter):
    university_key = "istinye"
    source_url = "https://international.istinye.edu.tr/en/quotas-and-tuition-fees"

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
                "No <table> elements found on the page at all — the site's structure "
                "has likely changed (e.g. moved to a JS-rendered widget). This needs "
                "a human to re-check the page, not a silent skip."
            )

        fees: list[ScrapedFee] = []
        for table in tables:
            header_cells = [th.get_text(strip=True) for th in table.find_all("th")]
            # Only process tables that look like the program-fee tables (skip
            # unrelated tables, e.g. "Maximum Course and Graduation Durations").
            if not any("Program" in h or "Name of Program" in h for h in header_cells):
                continue

            rows = table.find_all("tr")
            current_faculty: str | None = None
            for row in rows:
                cells = row.find_all("td")
                if not cells:
                    continue  # a <th>-only row (the real column-header row)

                cell_text = [c.get_text(strip=True) for c in cells]
                program_name = cell_text[0]

                # A faculty-header row (either markup style — see module
                # docstring) has real text only in its first cell; every cell
                # after it is blank. A genuine program row always has real
                # values in at least one of its other columns (duration,
                # quota, campus, ...), so this can't false-positive on those.
                if program_name and not any(cell_text[1:]):
                    current_faculty = program_name
                    continue

                if not program_name or program_name.startswith("**"):
                    continue  # bold faculty-header row leaking through as a single real cell

                # Column positions vary slightly (undergrad table has 7 cols,
                # postgrad table has fewer) — find prices by content, not fixed index.
                prices = [(_parse_try_lira_style_usd(c), c) for c in cell_text]
                priced = [(v, raw) for v, raw in prices if v is not None]
                if not priced:
                    continue  # a real row but with no listed price yet ("-") — skip, don't fabricate

                # Prefer the LAST priced column as "full/whole program payment"
                # (matches the table's own left-to-right convention of listing
                # installment before full payment), matching our cross-check
                # against the existing $27,550 İstinye Medicine (English) value.
                fee_value, raw_price_text = priced[-1]

                language = next((c for c in cell_text if c in ("English", "Turkish")), None)

                fees.append(ScrapedFee(
                    university_key=self.university_key,
                    program_name=program_name,
                    fee_usd=fee_value,
                    language=language,
                    faculty=current_faculty,
                    source_url=self.source_url,
                    raw_text=" | ".join(cell_text),
                ))

        return fees
