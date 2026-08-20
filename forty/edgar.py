"""A polite, cached client for SEC EDGAR.

Two rules govern access to EDGAR and both are enforced here rather than left to
good intentions: declare who you are on every request, and stay under ten
requests a second. Exceeding either gets an IP blocked, and an IP block in the
middle of a nightly build is indistinguishable from the data being wrong.

Everything is cached to disk keyed by URL. A first full run costs a few thousand
requests; every run after that costs almost none, which is what makes a nightly
job viable and what lets you iterate on the model without re-fetching a thing.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import config

_lock = threading.Lock()
_last_request = [0.0]

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
BROWSE_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}"
    "&type=10-K&dateb=&owner=include&count=100&start={start}&output=atom"
)


class FetchError(RuntimeError):
    """Raised when a URL cannot be retrieved after retries."""


def _cache_path(url: str) -> Path:
    return config.CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".gz")


def _throttle() -> None:
    """Space requests out to at most SEC_RATE_LIMIT per second."""
    with _lock:
        gap = 1.0 / config.SEC_RATE_LIMIT
        wait = gap - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


def fetch(url: str, *, force: bool = False, max_age_days: float | None = None) -> bytes:
    """Return the body at `url`, from cache when possible.

    `max_age_days` expires the cached copy; None means the cache never goes
    stale on its own. Prices and quarterly filings change on known schedules,
    so callers set this rather than the transport guessing.
    """
    path = _cache_path(url)
    if path.exists() and not force:
        fresh = (
            max_age_days is None
            or (time.time() - path.stat().st_mtime) < max_age_days * 86400
        )
        if fresh:
            return gzip.decompress(path.read_bytes())

    last_error: Exception | None = None
    for attempt in range(config.SEC_MAX_RETRIES):
        _throttle()
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": config.USER_AGENT,
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            path.write_bytes(gzip.compress(raw))
            return raw
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                # A company with no XBRL facts is a fact about the company, not
                # a transport failure. Cache the absence so we stop asking.
                path.write_bytes(gzip.compress(b""))
                return b""
            if exc.code in (403, 429):
                # Rate limited or blocked: back off hard, not politely.
                time.sleep(2 ** attempt * 5)
                continue
            time.sleep(2 ** attempt)
        except Exception as exc:  # noqa: BLE001 - transport errors are all equal here
            last_error = exc
            time.sleep(2 ** attempt)

    # A stale cached copy beats a hole in the data. Say so loudly and move on.
    if path.exists():
        print(f"      ! {url[:60]} failed ({last_error}); using cached copy")
        return gzip.decompress(path.read_bytes())
    raise FetchError(f"{url} failed after {config.SEC_MAX_RETRIES} attempts: {last_error}")


def fetch_json(url: str, **kw: Any) -> Any:
    raw = fetch(url, **kw)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def company_facts(cik: int, **kw: Any) -> dict | None:
    """Every XBRL fact a company has ever filed, in one document."""
    return fetch_json(FACTS_URL.format(cik=cik), **kw)


def submissions(cik: int, **kw: Any) -> dict | None:
    """Filing history and company metadata: SIC, exchange, tickers, name."""
    return fetch_json(SUBMISSIONS_URL.format(cik=cik), **kw)


def cache_stats() -> dict:
    files = list(config.CACHE.glob("*.gz"))
    return {
        "files": len(files),
        "mb": sum(f.stat().st_size for f in files) / 1e6,
    }
