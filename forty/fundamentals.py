"""Turning raw XBRL into the four numbers the model needs.

The four are LTM revenue, LTM growth, LTM free cash flow margin, and net debt.
Getting them out of company facts is most of the work in this repo, for three
reasons that are worth stating because each one is a place where a naive build
goes quietly wrong.

**Revenue has no single tag.** ASC 606 replaced `Revenues` with the
`RevenueFromContractWithCustomer` family in 2018, and filers moved at different
times. A series built from one tag has a hole somewhere in 2018-2019, and the
growth rate computed across that hole is fiction. So tags are tried in priority
order per period.

**Cash flow statements are cumulative.** A software company's Q3 10-Q reports
nine months of operating cash flow, not three. Treating the filed number as a
quarter overstates cash generation by roughly three times, and does it worse
later in the fiscal year — a seasonal artefact that looks like a real pattern.
Quarterly values are differenced out of the year-to-date series here.

**Fiscal years do not line up.** Salesforce closes in January, Workday in
January, NVIDIA in January, most of the rest in December. Their "Q3" figures
describe different three-month windows of the world. Everything is placed on
the calendar quarter its period actually ended in, so a cross-section compares
companies over the same weeks.

And one discipline that governs all of it: every value carries the date it was
filed, and nothing enters a cross-section dated before that. See METHOD.md.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable

import numpy as np
import pandas as pd

from . import config, edgar

# Day-count windows for classifying a reporting period by its length. Filers'
# quarters are 13 weeks but their period boundaries wander by a few days, and a
# 52/53-week fiscal calendar adds a week to one year in every five or six.
_QUARTER = (80, 100)
_HALF = (168, 195)
_NINE = (260, 288)
_YEAR = (350, 380)


def _duration_facts(facts: dict, tags: Iterable[str]) -> dict[tuple[str, str], dict]:
    """Collect period facts across a tag priority list.

    Keyed by (start, end). Earlier tags win. Within a tag, the *earliest* filing
    of a period wins: this is what was reported at the time, before any
    restatement. Using restated history would let a 2024 correction change what
    the model saw in 2019, which is the definition of look-ahead.
    """
    out: dict[tuple[str, str], dict] = {}
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        node = gaap.get(tag)
        if not node:
            continue
        for unit, entries in node.get("units", {}).items():
            if unit != "USD":
                continue
            for e in entries:
                if not e.get("start") or not e.get("end"):
                    continue
                if e.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F"):
                    continue
                key = (e["start"], e["end"])
                prev = out.get(key)
                if prev is None:
                    out[key] = {"val": e["val"], "filed": e["filed"], "tag": tag}
                elif prev["tag"] == tag and e["filed"] < prev["filed"]:
                    out[key] = {"val": e["val"], "filed": e["filed"], "tag": tag}
    return out


def _instant_facts(facts: dict, tags: Iterable[str]) -> dict[str, dict]:
    """Balance-sheet and cover-page facts, keyed by the date they describe."""
    out: dict[str, dict] = {}
    all_facts = facts.get("facts", {})
    for tag in tags:
        ns, _, name = tag.partition(":")
        if not name:
            ns, name = "us-gaap", tag
        node = all_facts.get(ns, {}).get(name)
        if not node:
            continue
        for unit, entries in node.get("units", {}).items():
            if unit not in ("USD", "shares"):
                continue
            for e in entries:
                if e.get("start") or not e.get("end"):
                    continue
                key = e["end"]
                prev = out.get(key)
                if prev is None or (prev["tag"] == tag and e["filed"] < prev["filed"]):
                    out[key] = {"val": e["val"], "filed": e["filed"], "tag": tag}
    return out


def _days(start: str, end: str) -> int:
    return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days


def _in(n: int, window: tuple[int, int]) -> bool:
    return window[0] <= n <= window[1]


def _quarterly(periods: dict[tuple[str, str], dict]) -> pd.DataFrame:
    """Reduce a mix of quarterly, half-year, nine-month and annual periods to
    discrete quarters.

    A cumulative period is resolved by subtracting the next-shortest period that
    shares its start date: Q4 is the fiscal year minus the nine months, Q3 is
    the nine months minus the half, and so on. The filing date attached to the
    difference is the later of the two, because that is when the arithmetic
    first became possible.
    """
    by_start: dict[str, list[tuple[str, dict, int]]] = {}
    for (start, end), rec in periods.items():
        n = _days(start, end)
        if n < 60 or n > 400:
            continue
        by_start.setdefault(start, []).append((end, rec, n))

    rows: list[dict] = []
    for start, items in by_start.items():
        items.sort(key=lambda t: t[2])
        for i, (end, rec, n) in enumerate(items):
            if _in(n, _QUARTER):
                rows.append({"end": end, "val": rec["val"], "filed": rec["filed"]})
                continue
            if not (_in(n, _HALF) or _in(n, _NINE) or _in(n, _YEAR)):
                continue
            prev = items[i - 1] if i else None
            if prev is None:
                continue
            gap = n - prev[2]
            if not _in(gap, _QUARTER):
                continue
            rows.append(
                {
                    "end": end,
                    "val": rec["val"] - prev[1]["val"],
                    "filed": max(rec["filed"], prev[1]["filed"]),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["val", "filed"])

    df = pd.DataFrame(rows)
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    # A period can be reconstructed more than one way; keep the version that was
    # knowable earliest.
    df = df.sort_values("filed").drop_duplicates(subset="end", keep="first")
    return df.set_index("end").sort_index()[["val", "filed"]]


def _ltm(q: pd.DataFrame) -> pd.DataFrame:
    """Trailing-twelve-month sums, refusing to sum across a gap.

    A rolling four-quarter window over an index with a missing quarter silently
    produces a nine-month "year". Requiring the window to span 330-400 days
    throws those away instead.
    """
    if q.empty:
        return pd.DataFrame(columns=["ltm", "filed"])
    vals = q["val"].astype(float)
    out = []
    idx = list(q.index)
    for i in range(3, len(idx)):
        window = idx[i - 3 : i + 1]
        span = (window[-1] - window[0]).days
        if not 240 <= span <= 300:  # three steps between four quarter-ends
            continue
        out.append(
            {
                "end": idx[i],
                "ltm": float(vals.loc[window].sum()),
                "filed": q["filed"].loc[window].max(),
            }
        )
    if not out:
        return pd.DataFrame(columns=["ltm", "filed"])
    return pd.DataFrame(out).set_index("end").sort_index()


def _latest_as_of(instants: dict[str, dict], when: pd.Timestamp) -> float | None:
    """The most recent balance-sheet value that had actually been filed by `when`."""
    best, best_end = None, None
    for end, rec in instants.items():
        filed = pd.Timestamp(rec["filed"])
        if filed > when:
            continue
        e = pd.Timestamp(end)
        if best_end is None or e > best_end:
            best, best_end = rec["val"], e
    return float(best) if best is not None else None


def build(cik: int, *, force: bool = False) -> pd.DataFrame | None:
    """Per-quarter fundamentals for one company, each row stamped with the date
    it became public knowledge.

    Columns
    -------
    ltm_revenue, ltm_fcf, ltm_gross_profit : trailing twelve months, USD
    rev_growth : LTM revenue over LTM revenue four quarters earlier
    fcf_margin, gross_margin : fractions of LTM revenue
    cash, debt, shares : latest instant values
    known_from : the date every number in the row had been filed
    """
    facts = edgar.company_facts(cik, force=force, max_age_days=1)
    if not facts:
        return None

    rev_q = _quarterly(_duration_facts(facts, config.REVENUE_TAGS))
    if len(rev_q) < config.MIN_QUARTERS_HISTORY:
        return None

    ocf_q = _quarterly(_duration_facts(facts, config.OCF_TAGS))
    capex_q = _quarterly(_duration_facts(facts, config.CAPEX_TAGS))
    gp_q = _quarterly(_duration_facts(facts, config.GROSS_PROFIT_TAGS))
    if gp_q.empty:
        cor_q = _quarterly(_duration_facts(facts, config.COST_OF_REVENUE_TAGS))
        if not cor_q.empty:
            joined = rev_q[["val"]].join(cor_q[["val"]], how="inner", rsuffix="_cor")
            gp_q = pd.DataFrame(
                {"val": joined["val"] - joined["val_cor"]},
                index=joined.index,
            ).join(rev_q[["filed"]])

    rev = _ltm(rev_q)
    if rev.empty:
        return None
    ocf = _ltm(ocf_q)
    capex = _ltm(capex_q)
    gp = _ltm(gp_q)

    df = pd.DataFrame(index=rev.index)
    df["ltm_revenue"] = rev["ltm"]
    df["filed_revenue"] = rev["filed"]

    # CapEx is filed as a positive outflow; free cash flow subtracts it.
    df["ltm_ocf"] = ocf["ltm"].reindex(df.index) if not ocf.empty else np.nan
    df["ltm_capex"] = capex["ltm"].reindex(df.index).abs() if not capex.empty else np.nan
    df["ltm_fcf"] = df["ltm_ocf"] - df["ltm_capex"].fillna(0.0)
    df["ltm_gross_profit"] = gp["ltm"].reindex(df.index) if not gp.empty else np.nan

    filed_cols = [rev["filed"]]
    for series in (ocf, capex, gp):
        if not series.empty:
            filed_cols.append(series["filed"].reindex(df.index))
    df["known_from"] = pd.concat(filed_cols, axis=1).max(axis=1)

    # Year-on-year growth of the trailing-twelve-month figure. Comparing the
    # same four-quarter window a year apart removes seasonality without needing
    # to model it, and it is the number a software investor quotes.
    prior = df["ltm_revenue"].shift(4)
    gap_ok = df.index.to_series().diff(4).dt.days.between(330, 400)
    df["rev_growth"] = np.where(
        gap_ok & (prior > 0), df["ltm_revenue"] / prior - 1.0, np.nan
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        df["fcf_margin"] = df["ltm_fcf"] / df["ltm_revenue"]
        df["gross_margin"] = df["ltm_gross_profit"] / df["ltm_revenue"]

    cash_f = _instant_facts(facts, config.CASH_TAGS)
    sti_f = _instant_facts(facts, config.SHORT_INVESTMENT_TAGS)
    debt_f = _instant_facts(facts, config.DEBT_TAGS)
    debt_c_f = _instant_facts(facts, config.DEBT_CURRENT_TAGS)
    share_f = _instant_facts(facts, config.SHARES_TAGS)

    for col, source in (
        ("cash", cash_f),
        ("short_investments", sti_f),
        ("debt_noncurrent", debt_f),
        ("debt_current", debt_c_f),
        ("shares", share_f),
    ):
        df[col] = [_latest_as_of(source, ts) for ts in df["known_from"]]

    df["net_debt"] = (
        df[["debt_noncurrent", "debt_current"]].sum(axis=1, min_count=1).fillna(0.0)
        - df[["cash", "short_investments"]].sum(axis=1, min_count=1).fillna(0.0)
    )

    df = df.dropna(subset=["ltm_revenue", "known_from"])
    return df if len(df) else None
