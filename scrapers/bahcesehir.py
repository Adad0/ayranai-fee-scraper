"""
Bahçeşehir University (BAU) fee scraper.

STRUCTURAL DIFFERENCE FROM İSTINYE — READ THIS FIRST:
BAU's page does NOT list fees per-program. It lists fees per SCHOOL/FACULTY
(e.g. "School of Engineering & Natural Sciences: $9,000/year" applies to
Computer Engineering, Industrial Engineering, Mechanical Engineering, etc.
all at once), with only a handful of individually-priced exceptions
(Artificial Intelligence Engineering, Pilotage — these get their own line
because they cost more than their school's blanket rate).

CONSEQUENCE: this scraper's output is coarser-grained than İstinye's. It
CANNOT be matched 1:1 against AyranAI's per-department annual_fee_usd without
a school→department mapping step. That mapping is deliberately NOT done here
— see ARCHITECTURE.md's "adapters propose raw data, review step maps it"
principle. Applying a blanket school-level fee to every department under it
without a human confirming the mapping is exactly the kind of silent-wrong-
data risk this whole project is designed to avoid.

Page shape (verified by hand, 2026-07): WordPress site, fee entries are
anchor (<a>) elements whose full text content concatenates "{Program/School
name}{Duration} Years ${amount} per year" or "... /whole program" for
graduate programs — not a clean HTML table. Parsing is regex-based on the
anchor's flattened text.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .base import ScrapedFee, UniversityFeeAdapter

# Matches e.g. "School of Engineering & Natural Sciences4 Years $9,000 per year"
# or "Online Master's Degree Programs1.5 Years $7,000 /whole program"
_ENTRY_RE = re.compile(
    r"^(?P<name>.+?)"
    r"(?P<duration>\d+(?:\.\d+)?)\s*Years?\s*"
    r"\$(?P<amount>[\d,]+)"
    r"(?:\s*\+\s*€[\d,]+)?"  # tolerate a trailing "+ €22,000" (Pilotage has a Euro component we don't parse — flagged in raw_text for human review)
    r"\s*(?P<basis>per year|/whole program)",
    re.IGNORECASE,
)


class BahcesehirAdapter(UniversityFeeAdapter):
    university_key = "bahcesehir"
    source_url = "https://int.bau.edu.tr/admission/tuition-fees/"

    def fetch(self) -> str:
        resp = requests.get(self.source_url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AyranAI-FeeScraper/1.0; +https://ayranai.com)"
        })
        resp.raise_for_status()
        return resp.text

    def parse(self, raw_content: str) -> list[ScrapedFee]:
        soup = BeautifulSoup(raw_content, "html.parser")

        # Fee entries live inside the "Graduate Programs" / "Undergraduate
        # Programs" sections as links pointing to /programs/?... — this is
        # more reliable than scoping by CSS class (WordPress themes change
        # class names far more often than URL patterns for this university).
        candidate_links = [
            a for a in soup.find_all("a", href=True)
            if "/programs/" in a["href"] or "/programs?" in a["href"]
        ]
        if not candidate_links:
            raise ValueError(
                "No links pointing to /programs/ found on the page — the site's "
                "structure has likely changed. Needs a human to re-check, not a "
                "silent skip."
            )

        fees: list[ScrapedFee] = []
        for a in candidate_links:
            text = " ".join(a.get_text(" ", strip=True).split())  # collapse whitespace
            m = _ENTRY_RE.match(text)
            if not m:
                continue  # not every /programs/ link on the page is a fee card (some are nav links) — skip non-matches silently, they're not fee data by definition

            name = m.group("name").strip()
            amount = float(m.group("amount").replace(",", ""))
            basis = m.group("basis").lower()

            # School-level entries (e.g. "School of Engineering & Natural
            # Sciences") ARE the faculty — the program_name and faculty are
            # the same string. Individually-priced exceptions (Artificial
            # Intelligence Engineering, Pilotage) and graduate-level entries
            # aren't school-level rows, so we leave faculty null rather than
            # guessing which parent faculty administratively owns them.
            faculty = name if name.lower().startswith("school of") else None

            fees.append(ScrapedFee(
                university_key=self.university_key,
                program_name=name,
                fee_usd=amount,
                language=None,  # BAU's fee page doesn't split by language the way İstinye's does — left unset, not guessed
                faculty=faculty,
                source_url=self.source_url,
                raw_text=f"{text}  [[basis={basis}; NOTE: school/faculty-level rate, not per-department — see module docstring]]",
            ))

        if not fees:
            raise ValueError(
                "Found /programs/ links but none matched the expected fee-text "
                "pattern — the fee format on the page has likely changed. Needs "
                "a human to re-check, not a silent skip."
            )

        return fees
