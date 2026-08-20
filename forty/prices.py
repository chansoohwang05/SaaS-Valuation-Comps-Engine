"""Price history, and the market capitalisation implied by it.

Fundamentals come from filings; prices have to come from a market data source,
and the free ones are all somebody's undocumented endpoint. Two are wired up —
Yahoo through `yfinance`, and Stooq as a fallback that speaks plain CSV over
HTTP and has never rate-limited anyone. If the primary fails for a ticker the
fallback is tried before the ticker is dropped.

Market cap is not taken from a vendor field. It is computed as price times the
share count disclosed on the most recent filing cover page that had been
published on that date, so a market cap in March 2021 uses the share count that
was public in March 2021 rather than today's. Vendor market-cap history uses
today's share count throughout, which for a software company that has diluted
itself 8% a year is a material and one-directional error.
"""

from __future__ import annotations

import io
import time

import numpy as np
import pandas as pd

from . import config

CACHE = config.DATA / "prices.parquet"
STOOQ = "https://stooq.com/q/d/l/?s={sym}.us&i=d"


def _from_yfinance(tickers: list[str], start: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()

    frames: list[pd.Series] = []
    for i in range(0, len(tickers), 100):
        batch = tickers[i : i + 100]
        try:
            raw = yf.download(
                batch,
                start=start,
                auto_adjust=False,
                progress=False,
                threads=True,
                group_by="column",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"      ! yfinance batch {i // 100 + 1} failed: {exc}")
            continue
        if raw is None or raw.empty:
            continue
        # Close, not Adj Close. A multiple is price over revenue per share, and
        # the price in that ratio is the actual traded price; back-adjusting for
        # dividends would put a number in the numerator that nobody paid.
        close = raw["Close"] if "Close" in raw else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(batch[0])
        frames.append(close)
        time.sleep(1.0)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


def _from_stooq(ticker: str, start: str) -> pd.Series | None:
    import urllib.request

    sym = ticker.lower().replace(".", "-")
    try:
        req = urllib.request.Request(
            STOOQ.format(sym=sym), headers={"User-Agent": config.USER_AGENT}
        )
        raw = urllib.request.urlopen(req, timeout=30).read().decode()
    except Exception:  # noqa: BLE001
        return None
    if "Date" not in raw[:64]:
        return None
    df = pd.read_csv(io.StringIO(raw), parse_dates=["Date"]).set_index("Date")
    s = df["Close"].astype(float)
    return s[s.index >= pd.Timestamp(start)].rename(ticker)


def fetch(tickers: list[str], *, force: bool = False) -> pd.DataFrame:
    """Daily closes for the universe, cached to parquet between runs."""
    cached = pd.DataFrame()
    if CACHE.exists() and not force:
        cached = pd.read_parquet(CACHE)
        stale = (pd.Timestamp.utcnow().tz_localize(None) - cached.index.max()).days > 1
        missing = [t for t in tickers if t not in cached.columns]
        if not stale and not missing:
            return cached

    fresh = _from_yfinance(tickers, config.HISTORY_START)

    got = set(fresh.columns) if not fresh.empty else set()
    fallback = [t for t in tickers if t not in got or fresh[t].notna().sum() < 100]
    if fallback:
        print(f"      trying Stooq for {len(fallback)} tickers Yahoo did not return")
        series = [s for t in fallback if (s := _from_stooq(t, config.HISTORY_START)) is not None]
        if series:
            fresh = pd.concat([fresh, pd.concat(series, axis=1)], axis=1) if not fresh.empty \
                else pd.concat(series, axis=1)

    if fresh.empty:
        if not cached.empty:
            print("      ! no price source reachable; using cache")
            return cached
        raise RuntimeError("No price source reachable — run `python audit.py`")

    fresh = fresh.loc[:, ~fresh.columns.duplicated()].sort_index()
    if not cached.empty:
        fresh = fresh.combine_first(cached)
    fresh.to_parquet(CACHE)
    return fresh


def as_of(prices: pd.DataFrame, ticker: str, when: pd.Timestamp) -> float | None:
    """Last close on or before a date. Quarter ends land on weekends and
    holidays often enough that an exact-date lookup loses a fifth of the panel.
    """
    if ticker not in prices.columns:
        return None
    s = prices[ticker].dropna()
    s = s[s.index <= when]
    if s.empty:
        return None
    if (when - s.index[-1]).days > 10:
        return None  # delisted, or the series simply stops here
    v = float(s.iloc[-1])
    return v if np.isfinite(v) and v > 0 else None
