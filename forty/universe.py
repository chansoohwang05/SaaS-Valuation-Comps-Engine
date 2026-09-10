"""Who counts as a software company.

The previous version of this project had a list of eight tickers I typed from
memory. That is not a universe, it is a preference, and every statistic computed
on it inherits the preference. Worse, the eight were chosen in 2026 knowing
which ones had done well — the survivorship problem in its purest form.

So the universe is defined by a rule and taken from the SEC's own
classification instead:

    every US-listed company whose SEC-assigned SIC code is software or
    software services, that clears a revenue floor and a gross-margin floor
    in the quarter being measured.

The gross-margin floor is doing real work. SIC alone lumps genuine software in
with IT-services firms that resell labour at 25% gross margin, and those two
businesses are not comparable at any multiple. 60% is the conventional line and
it is stated here rather than applied silently.

Because the screen is applied per quarter rather than once at the end, a company
that IPO'd in 2021 is absent from the 2019 cross-sections and a company acquired
in 2022 is present up to its last filing and then gone. That is what keeps the
coefficient history honest.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict

from . import config, edgar

# browse-edgar's atom feed exposes the CIK in more than one place and has
# changed shape before. Match the query-string form (CIK=0001108524) and the
# bare ten-digit element text, case-insensitively, rather than betting on one.
_ATOM_CIK = re.compile(r"CIK=(\d{10})", re.IGNORECASE)
MAJOR_EXCHANGES = {"Nasdaq", "NYSE", "NYSE American", "NYSEArca", "CBOE"}

# Below this, assume the browse endpoint changed shape rather than that the
# software sector emptied out, and take the slow road instead.
_MIN_PLAUSIBLE_UNIVERSE = 60


@dataclass(frozen=True)
class Company:
    cik: int
    ticker: str
    name: str
    sic: int
    sic_label: str
    exchange: str
    fiscal_year_end: str  # "MMDD"; software fiscal years are not all December

    def as_dict(self) -> dict:
        return asdict(self)


def _ciks_for_sic(sic: int, *, force: bool = False) -> set[int]:
    """Ask EDGAR which companies file under a SIC code.

    browse-edgar paginates a hundred at a time. Ten or so requests covers a SIC
    code that a full scan of every filer would need ten thousand to answer.
    """
    found: set[int] = set()
    for start in range(0, 2000, 100):
        raw = edgar.fetch(
            edgar.BROWSE_URL.format(sic=sic, start=start),
            force=force,
            max_age_days=30,
        )
        if not raw:
            break
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            break
        page = {int(m.group(1)) for m in _ATOM_CIK.finditer(raw.decode("utf-8", "replace"))}
        page |= {
            int(el.text)
            # The element is <cik> in the current feed and has been <CIK>
            # before; lowercasing the local tag name covers both.
            for el in root.iter()
            if el.tag.rpartition("}")[2].lower() == "cik"
            and el.text and el.text.strip().isdigit()
        }
        if not page - found:
            break  # pagination has run out; further pages repeat
        found |= page
    return found


def _scan_submissions_for_sic(
    tickers: dict[int, tuple[str, str, str]], *, force: bool = False
) -> dict[int, int]:
    """Fallback: read every listed filer's SIC from its own submissions file.

    Ten thousand requests rather than fifty, which at the SEC's rate limit is
    about twenty minutes — but it depends only on `data.sec.gov/submissions`,
    the most stable endpoint the SEC publishes, rather than on the shape of a
    CGI script's atom output. It runs once; the cache carries it afterwards.

    This exists because the fast path is the one piece of this project that
    could not be tested against a live response before it shipped, and a build
    that silently produces an empty universe is worse than one that takes
    twenty minutes.
    """
    wanted = set(config.SIC_CODES)
    found: dict[int, int] = {}
    total = len(tickers)
    print(f"      scanning {total} filers for SIC codes (one-off, ~{total / 8 / 60:.0f} min)")
    for i, cik in enumerate(sorted(tickers), 1):
        sub = edgar.submissions(cik, force=force, max_age_days=90)
        if not sub:
            continue
        try:
            sic = int(sub.get("sic") or 0)
        except (TypeError, ValueError):
            continue
        if sic in wanted:
            found[cik] = sic
        if i % 1000 == 0:
            print(f"      {i}/{total} scanned — {len(found)} in scope")
    return found


def _ticker_map(*, force: bool = False) -> dict[int, tuple[str, str, str]]:
    """CIK -> (ticker, name, exchange) for every listed filer."""
    doc = edgar.fetch_json(edgar.TICKERS_URL, force=force, max_age_days=7)
    if not doc:
        return {}
    fields = doc["fields"]
    idx = {name: i for i, name in enumerate(fields)}
    out: dict[int, tuple[str, str, str]] = {}
    for row in doc["data"]:
        cik = int(row[idx["cik"]])
        ticker = row[idx["ticker"]]
        name = row[idx["name"]]
        exchange = row[idx.get("exchange", 0)] or ""
        # A company with several share classes appears more than once. Keep the
        # shortest ticker, which is the primary class by convention (GOOG/GOOGL,
        # BRK.A/BRK.B), so one company contributes one observation.
        if cik in out and len(out[cik][0]) <= len(ticker):
            continue
        out[cik] = (ticker, name, exchange)
    return out


def build(*, force: bool = False, limit: int = 0) -> list[Company]:
    """Assemble the candidate universe. Screens on fundamentals come later."""
    tickers = _ticker_map(force=force)
    if not tickers:
        raise RuntimeError(
            "SEC ticker file unavailable — run `python audit.py` to check network access"
        )

    candidates: dict[int, int] = {}  # cik -> sic
    for sic in sorted(config.SIC_CODES):
        for cik in _ciks_for_sic(sic, force=force):
            candidates.setdefault(cik, sic)

    listed = len(set(candidates) & set(tickers))
    if listed < _MIN_PLAUSIBLE_UNIVERSE:
        print(f"      ! SIC browse returned only {listed} listed companies — "
              "assuming the endpoint changed and falling back to a full scan")
        candidates = _scan_submissions_for_sic(tickers, force=force)

    companies: list[Company] = []
    for cik, sic in sorted(candidates.items()):
        if cik not in tickers:
            continue  # filed with the SEC but is not listed; no price, no multiple
        ticker, name, exchange = tickers[cik]
        if exchange and exchange not in MAJOR_EXCHANGES:
            continue
        companies.append(
            Company(
                cik=cik,
                ticker=ticker,
                name=name,
                sic=sic,
                sic_label=config.SIC_CODES[sic],
                exchange=exchange,
                fiscal_year_end="",  # filled from submissions on demand
            )
        )

    companies.sort(key=lambda c: c.ticker)
    return companies[:limit] if limit else companies


def enrich(company: Company, *, force: bool = False) -> Company:
    """Add the fiscal year end, which decides how quarters line up."""
    sub = edgar.submissions(company.cik, force=force, max_age_days=30)
    if not sub:
        return company
    return Company(
        cik=company.cik,
        ticker=company.ticker,
        name=sub.get("name", company.name),
        sic=int(sub.get("sic") or company.sic),
        sic_label=sub.get("sicDescription", company.sic_label),
        exchange=company.exchange,
        fiscal_year_end=sub.get("fiscalYearEnd", "") or "",
    )
