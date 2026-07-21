"""
Ozyegin University fee scraper.

Page shape (verified by direct live fetch, 2026-07, WordPress/Elementor
page builder, robots.txt allows access): a SIXTH distinct structural
pattern -- no <table> exists at all. Faculty headers appear as short
emoji-prefixed text blocks (e.g. an emoji icon followed by "Faculty of
Engineering"), followed by a flat sequence of program rows where the
program name and its fee are on SEPARATE consecutive text blocks --
"Computer Engineering" then "$25,000" as its own line immediately after,
NOT concatenated into one string. (An earlier version of this adapter
assumed concatenation, based on markdown-extracted text that had collapsed
the separator between them; that assumption was wrong and was caught by
running the actual parser against a real fetch of the live page before
trusting it -- see README's "Needs live verification before trusting"
note and the Uskudar off-by-one incident it references.)

PARSING APPROACH: a small state machine over the page's flattened text
lines. A "Faculty of X" / "School of X" / "College of X" line (matched by
substring search, so the emoji prefix doesn't need special handling) sets
the current faculty and clears any pending program name. Any other line,
while inside a faculty section, becomes the current "pending" program
name candidate. A line that is JUST "$" followed by digits/commas and
nothing else immediately consumes that pending name as its program and
emits a fee -- this is how the name+fee pairing survives them being on
separate lines.

GATING ON "inside a faculty section" MATTERS: the page has a scholarship-
tier preamble BEFORE the first faculty header ("40% scholarship" / "50%
scholarship" / "60% scholarship", each followed by its own bare "$X,XXX"
line, plus an accommodation-fee sentence ending in a bare "$2,000" line).
Without gating on current_faculty being set, those would be silently
mis-captured as bogus "programs" -- confirmed by inspecting the real
extracted text, not assumed.

Amount uses a comma thousands separator here ("$25,000"), NOT the
Turkish-style period separator seen at Istinye/Uskudar/Yeditepe -- a
different regex is needed (comma-stripping, not period-stripping).

Almost every program is a flat $25,000 -- Professional Flight ($16,500,
explicitly scholarship-ineligible) is the one named exception. This mirrors
Sabanci's near-flat-fee pattern but WITH faculty grouping still present, so
it doesn't collapse to a single row the way Sabanci's page does.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

_FACULTY_RE = re.compile(r"^(Faculty of|School of|College of)\s+.+$")
_BARE_FEE_RE = re.compile(r"^\$([\d,]+)$")


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
        pending_name: str | None = None
        found_any_program_fee_line = False

        for line in raw_lines:
            header_match = re.search(r"(Faculty of .+|School of .+|College of .+)", line)
            if header_match and "$" not in line:
                current_faculty = header_match.group(1).strip()
                pending_name = None
                continue

            fee_match = _BARE_FEE_RE.match(line)
            if fee_match:
                # Only pair a bare fee line with a pending name once we're
                # inside a real faculty section -- see module docstring for
                # why (the scholarship-tier preamble before the first
                # header has its own bare "$X,XXX" lines that must NOT be
                # captured as programs).
                if current_faculty is not None and pending_name:
                    found_any_program_fee_line = True
                    fee_value = _parse_comma_usd(fee_match.group(1))
                    if fee_value is not None:
                        fees.append(ScrapedFee(
                            university_key=self.university_key,
                            program_name=pending_name,
                            fee_usd=fee_value,
                            language=None,
                            faculty=current_faculty,
                            source_url=self.source_url,
                            raw_text=f"{current_faculty or ''} | {pending_name} | {line}",
                        ))
                pending_name = None
                continue

            if current_faculty is not None:
                pending_name = line

        if not found_any_program_fee_line:
            raise ValueError(
                "Page text was extracted but no program-name-line-followed-by-"
                "bare-fee-line pattern was found anywhere -- the fee format has "
                "likely changed. Needs a human to re-check."
            )

        return fees
