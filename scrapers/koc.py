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

FETCH MECHANISM -- KOC-SPECIFIC, READ BEFORE COPYING TO ANOTHER ADAPTER:
requests.get() with a realistic browser User-Agent still gets a 403 from
this site's WAF when run from GitHub Actions' runner IPs, even though the
identical request succeeds from other networks (confirmed 2026-07-16) --
i.e. IP-range/datacenter blocking, not a header problem. fetch() uses
Playwright's headless Chromium instead: a real browser engine with a real
TLS handshake and JS execution, which many basic WAF rules allow through
even from datacenter IPs that block plain HTTP-library requests. This is
deliberately isolated to this one adapter -- every other adapter in this
repo still uses plain requests.get(), and should keep doing so unless it
independently hits the same wall. Needs `playwright install chromium` (see
requirements.txt and .github/workflows/monthly-scrape.yml) -- if that
browser-binary install step is ever removed, this adapter breaks.
"""

from __future__ import annotations

import re

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
        # Deferred import: keeps `import scrapers.koc` cheap for callers that
        # don't need it (tests import KocAdapter without ever calling
        # fetch()), and means a broken/missing Playwright install only
        # breaks this adapter's fetch(), not module import for the whole
        # batch. See module docstring for why this uses a real browser
        # engine instead of requests.get().
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                # "domcontentloaded" not "networkidle": this is a static
                # WordPress page, not one that keeps polling in the
                # background -- networkidle would just add unnecessary wait
                # time (or hang) without changing what content is present.
                response = page.goto(self.source_url, timeout=30000, wait_until="domcontentloaded")
                if response is not None and not response.ok:
                    raise ValueError(
                        f"Playwright navigation returned HTTP {response.status} for "
                        f"{self.source_url} -- the WAF/bot-detection block was not "
                        f"avoided by using a real browser engine. Needs a human to "
                        f"investigate further (e.g. a different network path), not "
                        f"another automated retry."
                    )
                return page.content()
            finally:
                browser.close()

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
            # Check the first ROW's cells regardless of tag (<th> or <td>) --
            # this WordPress site's header row uses <td>, not <th> (confirmed
            # 2026-07, same root cause as scrapers/acibadem.py's identical
            # fix). table.find_all("th") alone was always empty, so the only
            # table on the page looked like "not the fee table" and was
            # silently skipped, producing zero rows.
            first_row = table.find("tr")
            first_row_cells = first_row.find_all(["td", "th"]) if first_row else []
            header_cells = [c.get_text(strip=True).upper() for c in first_row_cells]
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
