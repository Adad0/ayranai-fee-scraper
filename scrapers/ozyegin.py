"""
Ozyegin University fee scraper.

Page shape (verified by hand, 2026-07, WordPress/Elementor page builder,
robots.txt allows access): a SIXTH distinct structural pattern -- no
<table> exists at all. Faculty headers appear as short emoji-prefixed text
blocks (e.g. "Faculty of Engineering", each preceded by an emoji icon
element from the page builder), followed by a flat sequence of
"ProgramName$Amount" text blocks with NO delimiter between name and price
other than the "$" sign itself (e.g. "Computer Engineering$25,000" reads
as one concatenated string in the page's own text flow).

PARSING APPROACH: work over the page's flattened text content (not table
rows), using two regexes: one to detect a faculty-header line ("Faculty
of X" / "School of X" / "College of X"), and one to pull "Name$Amount"
pairs out of the lines that follow, up to the next detected header. Amount
uses a comma thousands separator here ("$25,000"), NOT the Turkish-style
period separator seen at Istinye/Uskudar/Yeditepe -- a different regex is
needed (comma-stripping, not period-stripping).

Almost every program is a flat $25,000 -- Professional Flight ($16,500,
explicitly scholarship-ineligible) is the one named exception. This mirrors
Sabanci's near-flat-fee pattern but WITH faculty grouping still present, so
it doesn't collapse to a single row the way Sabanci's page does.

UNCERTAINTY FLAG: the exact live DOM structure (whether program name and
price share a single text node, or are adjacent sibling elements) could
not be directly confirmed from this environment -- only markdown-extracted
text was available, which showed them concatenated with zero separator.
This fixture is a best-effort reconstruction. If the real structure
differs, the parser will raise a clear "no pattern found" error (fail
loud) rather than silently produce wrong data -- but this MUST be verified
against a real GitHub Actions run (checking Supabase for real proposals
matching known figures like Computer Engineering=$25,000) before trusting
it, same discipline as the Uskudar off-by-one incident earlier in this
project.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

_FACULTY_RE = re.compile(r"^(Faculty of|School of|College of)\s+.+$")
_PROGRAM_FEE_RE = re.compile(r"^(.+?)\$([\d,]+)\s*$")


def _parse_comma_usd(text: str) -> float | None:
    text = text.strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class OzyeginAdapter(UniversityFeeAdapter):
    university_key = "ozyegin"
    source_url = "https://admissions.ozyegin.edu.tr/en/tuition-fees-and-scholarship/"

    def fetch(self) -> str:
        resp = requests.get(self.source_url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        resp.raise_for_status()
        return resp.text

    def parse(self, raw_content: str) -> list[ScrapedFee]:
        soup = BeautifulSoup(raw_content, "html.parser")
        main = soup.find("body") or soup
        raw_lines = [ln.strip() for ln in main.get_text("\n", strip=True).split("\n") if ln.strip()]

        if not raw_lines:
            raise ValueError(
                "No text content extracted from the page at all -- the site's "
                "structure has likely changed drastically. Needs a human to re-check."
            )

        fees: list[ScrapedFee] = []
        current_faculty: str | None = None
        found_any_program_fee_line = False

        for line in raw_lines:
            header_match = re.search(r"(Faculty of .+|School of .+|College of .+)", line)
            if header_match and "$" not in line:
                current_faculty = header_match.group(1).strip()
                continue

            m = _PROGRAM_FEE_RE.match(line)
            if not m:
                continue
            found_any_program_fee_line = True
            program_name, fee_text = m.group(1).strip(), m.group(2)
            if not program_name:
                continue

            fee_value = _parse_comma_usd(fee_text)
            if fee_value is None:
                continue

            fees.append(ScrapedFee(
                university_key=self.university_key,
                program_name=program_name,
                fee_usd=fee_value,
                language=None,
                faculty=current_faculty,
                source_url=self.source_url,
                raw_text=f"{current_faculty or ''} | {line}",
            ))

        if not found_any_program_fee_line:
            raise ValueError(
                "Page text was extracted but no 'ProgramName$Amount' pattern "
                "was found anywhere -- the fee format has likely changed. "
                "Needs a human to re-check."
            )

        return fees
