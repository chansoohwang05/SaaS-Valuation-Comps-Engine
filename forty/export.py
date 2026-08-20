"""Writing the results out for the site.

The page makes no live calls. Everything it displays was computed by the build
and written here as static JSON, which means a data source having a bad day can
make the numbers stale but can never make the page break or, worse, render
half-wrong. It also means the site loads instantly and costs nothing to host.

Two shapes: one index with the coefficient history and a directory of every
company, and one small file per company holding its full history. The index has
to be small enough to load on a phone, so per-company detail is sharded rather
than inlined.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from . import config


def _clean(obj: Any) -> Any:
    """JSON has no NaN. Anything not finite becomes null so the page can test
    for it, instead of `NaN` appearing in the document and failing to parse."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj.date())
    if obj is pd.NaT or obj is None:
        return None
    return obj


def _write(path, payload) -> float:
    path.write_text(json.dumps(_clean(payload), separators=(",", ":")))
    return path.stat().st_size / 1024


def write(
    coefs: pd.DataFrame,
    members: pd.DataFrame,
    summary: dict,
    meta: dict,
) -> dict:
    """Emit the index and one file per company. Returns size statistics."""
    for stale in config.COMPANIES.glob("*.json"):
        stale.unlink()

    latest_date = members["date"].max()
    latest = members[members["date"] == latest_date].copy()
    latest["premium_rank"] = latest["premium"].rank(ascending=False, method="min")

    directory = [
        {
            "ticker": r.ticker,
            "name": r.name,
            "ev_revenue": r.ev_revenue,
            "fair_ev_revenue": r.fair_ev_revenue,
            "premium": r.premium,
            "growth": r.rev_growth,
            "fcf_margin": r.fcf_margin,
            "rule_of_40": r.rule_of_40,
            "market_cap": r.market_cap,
            "lag_days": int(r.reporting_lag_days),
        }
        for r in latest.sort_values("market_cap", ascending=False).itertuples()
    ]

    history = [
        {
            "date": str(idx.date()),
            "b_growth": row.b_growth,
            "b_margin": row.b_margin,
            "ratio": row.growth_margin_ratio,
            "se_growth": row.se_growth,
            "se_margin": row.se_margin,
            "r2": row.r2,
            "n": row.n,
            "median_multiple": row.median_ev_revenue,
            "rule40_t": row.rule40_t,
            "rule40_rejected": row.rule40_rejected,
        }
        for idx, row in coefs.iterrows()
    ]

    index_kb = _write(
        config.SITE / "index.json",
        {
            "meta": meta,
            "summary": summary,
            "history": history,
            "companies": directory,
            "as_of": str(latest_date.date()),
        },
    )

    shard_kb = 0.0
    for ticker, g in members.groupby("ticker"):
        g = g.sort_values("date")
        last = g.iloc[-1]
        shard_kb += _write(
            config.COMPANIES / f"{ticker}.json",
            {
                "ticker": ticker,
                "name": last["name"],
                "cik": int(last["cik"]),
                "latest": {
                    "date": last["date"],
                    "price": last["price"],
                    "market_cap": last["market_cap"],
                    "enterprise_value": last["enterprise_value"],
                    "net_debt": last["net_debt"],
                    "ltm_revenue": last["ltm_revenue"],
                    "ltm_fcf": last["ltm_fcf"],
                    "growth": last["rev_growth"],
                    "fcf_margin": last["fcf_margin"],
                    "gross_margin": last["gross_margin"],
                    "rule_of_40": last["rule_of_40"],
                    "ev_revenue": last["ev_revenue"],
                    "fair_ev_revenue": last["fair_ev_revenue"],
                    "premium": last["premium"],
                    "reported_quarter": last["as_reported_quarter"],
                    "known_from": last["known_from"],
                    "lag_days": int(last["reporting_lag_days"]),
                },
                "history": [
                    {
                        "date": str(r.date.date()),
                        "ev_revenue": r.ev_revenue,
                        "fair": r.fair_ev_revenue,
                        "premium": r.premium,
                        "growth": r.rev_growth,
                        "fcf_margin": r.fcf_margin,
                        "revenue": r.ltm_revenue,
                    }
                    for r in g.itertuples()
                ],
            },
        )

    return {
        "index_kb": index_kb,
        "shards": int(members["ticker"].nunique()),
        "shard_mb": shard_kb / 1024,
    }
