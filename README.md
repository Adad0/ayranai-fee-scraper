# AyranAI Fee Scraper

Automatically tracks tuition fee changes across Turkish private universities, on a monthly schedule, for [AyranAI](https://ayranai.com) — an AI-powered university matching platform for international students.

**Status:** 3 universities implemented (İstinye, Bahçeşehir, Üsküdar), proving out three structurally different scraping patterns. 2 more investigated and found to be **blocked by robots.txt** (Altınbaş, Biruni) — see "Known blocked universities" below. Designed to scale to more universities incrementally — see "Adding a university" below.

## Why this exists

AyranAI's recommendation engine shows students a university's annual tuition fee as one of several matching criteria. That data was previously updated by hand. Fees change yearly (sometimes announced mid-year), and manually checking 40+ university websites is exactly the kind of repetitive, error-prone task worth automating — carefully.

## Design principles

1. **Never auto-apply.** A scraper is a proposal generator, not a database writer. Every run produces a human-readable review report (`data/review_<date>.md`) listing changes and failures — nothing reaches production data without a human confirming it. A silent scraping bug must never become the price a real student sees.
2. **Fail loud, never silent.** If a university's page structure changes and a parser can't find what it expects, it *raises an exception* — it does not return an empty list or a stale guess. An empty result is indistinguishable from "this university genuinely has zero programs," which is never true, so it's treated as a bug, not a data point.
3. **One university's failure never blocks another's.** The orchestrator (`run_scrape.py`) runs every adapter independently and catches failures per-adapter — a site being down or blocking scrapers doesn't stop the other 43 from running.
4. **Adapters propose raw data; a review step maps it.** Not every university publishes fees the same way. İstinye lists per-program fees that map 1:1 onto AyranAI's internal department names. Bahçeşehir lists per-*school* fees (one number covers several departments at once). The scraper does not guess this mapping — it surfaces the raw scraped value with a clear note when the granularity doesn't match, and a human maps it during review.

## Architecture

```
scrapers/
  base.py           — the adapter interface every university implements
  istinye.py         — per-program fee table (HTML <table>, embedded header rows)
  bahcesehir.py       — per-school fee cards (HTML <a> links, regex-parsed)
  uskudar.py          — one <table> per faculty, fee column header text varies (undergrad vs graduate)
tests/
  fixtures/           — saved HTML samples (see note below on why)
  test_istinye.py
  test_bahcesehir.py
  test_uskudar.py
run_scrape.py         — orchestrator: runs all adapters, diffs against last
                         snapshot, writes a review report
data/
  last_known_fees.json — committed snapshot of the last successful scrape
  review_<date>.md      — human-readable report from each run
.github/workflows/
  monthly-scrape.yml   — scheduled run (1st of each month) + manual trigger
```

## Known blocked universities (robots.txt)

Some universities' `robots.txt` explicitly disallows automated access to their site. This project treats that as a **hard rule, not an obstacle to route around** — scraping a site that has opted out via robots.txt is both an ethical line and a practical risk (IP bans, ToS violations). Confirmed blocked as of 2026-07:

- **Altınbaş University** (`international.altinbas.edu.tr`)
- **Biruni University** (`int.biruni.edu.tr`)

For these, the only legitimate path forward is a **permission-based approach** — e.g. contacting the university's international office to ask about an official data feed or API, or getting explicit written permission to scrape. Do not build a scraper that ignores their `robots.txt`.

## Known blocked universities (IP-range, not robots.txt)

**Koç University** (`international.ku.edu.tr`) — this is a *different* kind of block from the robots.txt cases above, and not an ethical opt-out. `robots.txt` allows access here; the site's WAF is blocking GitHub Actions' runner IP range specifically. Confirmed via dual-testing, 2026-07:

- A plain `requests.get()` with a realistic browser `User-Agent`: 403 Forbidden.
- Playwright headless Chromium (a real browser engine — real TLS handshake, JS execution, not just a header string): also 403 Forbidden, from the same GitHub Actions run.
- The identical request succeeds from other networks (confirmed by hand, outside GitHub Actions).

Two different HTTP clients hitting the same wall from the same network, while both succeed elsewhere, points to IP-range/datacenter blocking rather than a client-fingerprint check — a User-Agent or browser-engine swap can't fix that from within GitHub Actions.

`scrapers/koc.py` and `tests/test_koc.py` remain in the repo, **unchanged and fully correct** — this is blocked-by-environment code, not dead code. `KocAdapter()` is commented out in `run_scrape.py`'s `ADAPTERS` list (see the comment there) so it doesn't produce a known, un-actionable failure in every monthly run. It's ready to work immediately if run from a different network path — a proxy, a self-hosted runner, or a different CI provider.

## Known non-scrapable universities (fee data not published in structured/public form)

A third category, distinct from both of the above: no robots.txt block, no WAF/IP block — the fee data itself just isn't published anywhere this project can scrape.

**PDF-only** (fee data exists, but only inside a PDF — needs a PDF-text-extraction adapter type, not built yet; every adapter in this repo so far assumes an HTML page (`requests`/Playwright + BeautifulSoup), which has nothing to parse on these):

- **Kadir Has University** — the official tuition page links only to a PDF ([13_69088b66553ed.pdf](https://www.khas.edu.tr/wp-content/uploads/2025/11/13_69088b66553ed.pdf)); no HTML fee table exists on the page at all.
- **İstanbul Medipol University** — official tuition data is published only as a PDF (linked from `mio.medipol.edu.tr/annual-tuitions-rates`, titled "2025-2026 ACADEMIC INTAKE INTERNATIONAL STUDENTS TUITION FEE LIST.pdf"). The HTML page itself contains only scholarship/policy prose, no fee table.

**Not published at all** (no PDF, no table, nothing to scrape in any form):

- **Işık University** — the official tuition-fees page (`isikun.edu.tr/en/international/tuition-fees`) explicitly states fees are not published on the site, and directs applicants to email `international.admissions@isikun.edu.tr` instead. This isn't a technical block of any kind — the data genuinely doesn't exist in any public, scrapable form.

### Why tests use saved HTML fixtures instead of hitting live sites

Two reasons: (1) tests should be fast and not depend on a university's website being up; (2) this avoids hammering a real university's server on every CI run. The fixtures are built from real, hand-verified page content (see each fixture file's header comment) — they're not synthetic placeholder data. A separate scheduled job (the actual monthly GitHub Action) is the real integration test against live pages.

### The Turkish-number-format bug this project specifically guards against

Turkish fee pages format numbers like `27.550 $` — period as a thousands separator, not a decimal point. A naive `float("27.550")` silently gives you `27.55`, not `27,550`. Every adapter has an explicit test for this (see `test_price_parsing_turkish_thousands_format` in `tests/test_istinye.py`).

## Adding a university

1. Fetch the university's official international/foreign-student tuition page by hand once, and read its actual structure (table? cards? PDF? JS-rendered?). Turkish private universities commonly publish a dedicated `international.<domain>` or `int.<domain>` subdomain aimed at foreign students and agencies — these tend to be cleaner and already in USD, unlike the Turkish-facing pages (which show scholarship-tier percentage tables aimed at OSYM-placed domestic students). **Check `robots.txt` first** (`<domain>/robots.txt`) — if it disallows access, stop, don't build an adapter, see "Known blocked universities" above.
2. Save a representative sample of that page as a fixture in `tests/fixtures/`.
3. Write a new adapter in `scrapers/<university>.py`, subclassing `UniversityFeeAdapter`. Three structural patterns have been seen so far — pick whichever your target university's structure resembles:
   - **Per-program table with embedded header rows** (İstinye) — one big table, faculty names as bold spanning rows mixed in with program rows.
   - **Anchor-tag cards** (Bahçeşehir) — fee info concatenated into link text, regex-parsed, school-level (not per-department) granularity.
   - **One table per faculty** (Üsküdar) — cleanest pattern seen so far, watch out for the fee-column header text differing between undergrad ("PER YEAR") and graduate ("FULL PROGRAM") tables.
4. Write tests against your fixture, following the existing test files' structure — cover the happy path, the "structure changed" failure case, the "field found but with no price" case, and (importantly, per the İstinye/Üsküdar experience) a test that catches picking the WRONG price column when a row has multiple dollar figures (installment vs full payment vs advance-payment discount).
5. Register the adapter in `run_scrape.py`'s `ADAPTERS` list.

## Running locally

```bash
pip install -r requirements.txt
pytest tests/ -v          # verify parsers against saved fixtures
python run_scrape.py       # live scrape + review report (needs real internet access)
```

## What's NOT built yet (by design, not oversight)

- **Auto-applying confirmed changes to AyranAI's Supabase.** Deliberately deferred until this has run reliably for a few months — see design principle #1.
- **A school→department mapping table for Bahçeşehir-style universities.** The scraper surfaces the raw school-level number; mapping it onto specific AyranAI department records is a manual review-step task for now.
- **Currency conversion for non-USD fees** (e.g. Pilotage's Euro component at BAU). Flagged in the raw scraped text for a human to see, not silently converted or dropped.
- **Universities #4–44.** Three adapters exist, covering three structural patterns (per-program table, per-school cards, per-faculty tables). 2 of the remaining 41 are already known to be robots.txt-blocked (see above) — scaling to the rest is incremental, one adapter at a time, checking `robots.txt` first for each.
