"""
Base adapter interface for university fee scrapers.

DESIGN PHILOSOPHY (read this before adding a new university):
Every Turkish private university publishes tuition fees differently — some
per-program (İstinye), some per-faculty/school (Bahçeşehir), some as PDFs,
some behind JS-rendered widgets. There is no universal parser that works
across all of them. Each university gets its OWN adapter class that knows
its specific page structure. This file defines the CONTRACT every adapter
must satisfy, so the orchestrator (run_scrape.py) can treat all of them
uniformly regardless of how different their scraping logic is internally.

SAFETY PRINCIPLE: adapters NEVER write to the database directly. They only
return proposed fee records. A human (or a review step) always approves
changes before they reach production data. See ARCHITECTURE.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ScrapedFee:
    """One proposed fee data point for one program at one university.

    This is intentionally a flat, simple record — the review step (not this
    file) is responsible for deciding how it maps onto the richer internal
    UNIVERSITY_META / Supabase schema.
    """
    university_key: str        # matches the internal university identifier (e.g. "istinye")
    program_name: str          # as scraped, in the source's own wording
    fee_usd: float              # the annual fee, already normalized to USD
    language: str | None = None       # "English" / "Turkish" / None if not specified
    source_url: str = ""
    raw_text: str = ""          # original matched text, kept for human review/debugging
    scraped_at: str = ""         # ISO timestamp, filled in automatically if omitted

    def __post_init__(self):
        if not self.scraped_at:
            object.__setattr__(self, "scraped_at", datetime.now(timezone.utc).isoformat())


@dataclass
class ScrapeResult:
    """The full outcome of running one adapter — success or failure, never partial-silent."""
    university_key: str
    ok: bool
    fees: list[ScrapedFee]
    error: str | None = None   # populated only when ok=False — NEVER silently swallow failures


class UniversityFeeAdapter(ABC):
    """Every university-specific scraper implements this.

    Naming convention: one file per university in scrapers/, class name
    <University>Adapter, university_key matching the slug used elsewhere
    in this project (and ideally matching the main AyranAI system's own
    internal identifier for that university, to make the review step's
    matching job easier).
    """

    university_key: str
    source_url: str

    @abstractmethod
    def fetch(self) -> str:
        """Fetch the raw page content (HTML/text). Kept separate from parse()
        so tests can feed in saved HTML fixtures without a live network call."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw_content: str) -> list[ScrapedFee]:
        """Parse raw content into a list of ScrapedFee records.

        MUST raise a descriptive exception (not return an empty list) if the
        page structure looks unrecognized — an empty list is indistinguishable
        from "this university genuinely has zero programs," which is never
        true. Silently returning [] on a parse failure is the failure mode
        this whole project exists to avoid (see ARCHITECTURE.md's
        "fail loud, not silent" principle).
        """
        raise NotImplementedError

    def run(self) -> ScrapeResult:
        """Orchestrates fetch+parse with error isolation. One university's
        failure (site down, structure changed, timeout) must never crash the
        whole batch run — see run_scrape.py, which calls .run() on every
        adapter and continues past failures, collecting them for the report."""
        try:
            raw = self.fetch()
            fees = self.parse(raw)
            if not fees:
                return ScrapeResult(
                    university_key=self.university_key,
                    ok=False,
                    fees=[],
                    error="Parser ran but returned zero fees — likely a structure change, not a real empty result. Treat as failure, not success.",
                )
            return ScrapeResult(university_key=self.university_key, ok=True, fees=fees)
        except Exception as e:  # noqa: BLE001 — intentionally broad: ANY adapter failure must be caught and reported, never crash the batch
            return ScrapeResult(university_key=self.university_key, ok=False, fees=[], error=str(e))
