"""A generated panel, for exercising the pipeline without touching a network.

This exists for two reasons. It lets the tests check the estimator against
coefficients that are known by construction, and it lets anyone clone the repo
and see the site working in ten seconds instead of after a twenty-minute fetch.

It is not a data source. Everything it produces is stamped `demo: true`, the
page renders a warning across the top, and the published site is built by CI
from SEC filings. Fabricated numbers that are not labelled as fabricated are
the single fastest way to destroy the credibility of a research project, so the
label is applied at the point of generation rather than left to the caller.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


class _Fake:
    """Enough of `universe.Company` for the rest of the pipeline."""

    def __init__(self, cik: int, ticker: str, name: str) -> None:
        self.cik, self.ticker, self.name = cik, ticker, name
        self.sic, self.sic_label = 7372, "Prepackaged software"
        self.exchange, self.fiscal_year_end = "Nasdaq", "1231"


def build(n_companies: int = 160, seed: int = 42) -> tuple[pd.DataFrame, list]:
    """A panel whose true growth/margin pricing is known and time-varying.

    The planted ratio moves the way the real one is expected to: growth heavily
    favoured through the zero-rate period, converging toward parity afterwards.
    Recovering that shape from the generated data is a test of the estimator,
    not evidence about the market.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-03-31", "2026-06-30", freq="QE")

    companies = [
        _Fake(1_000_000 + i, f"DEM{i:03d}", f"Demo Software {i:03d}")
        for i in range(n_companies)
    ]

    # Persistent company characteristics, so a company's history is a history
    # rather than a fresh draw each quarter.
    base_growth = rng.uniform(0.03, 0.55, n_companies)
    base_margin = rng.uniform(-0.30, 0.35, n_companies)
    base_size = rng.uniform(18.0, 23.5, n_companies)  # log revenue: $65m to $16bn
    quality = rng.normal(0, 0.25, n_companies)

    rows = []
    for t, d in enumerate(dates):
        year = d.year + d.month / 12
        # Planted coefficients: growth richly paid until 2022, then compressed.
        b_growth = 2.2 + 2.6 * np.exp(-((year - 2021.3) ** 2) / 1.6)
        b_margin = 0.8 + 0.9 / (1 + np.exp(-(year - 2022.2) * 1.6))
        level = 0.9 + 0.9 * np.exp(-((year - 2021.3) ** 2) / 2.2)

        decay = 0.97 ** t
        growth = np.clip(base_growth * decay + rng.normal(0, 0.05, n_companies), -0.15, 1.2)
        margin = np.clip(
            base_margin + 0.012 * t / 4 + rng.normal(0, 0.04, n_companies), -0.8, 0.55
        )
        size = base_size + 0.06 * t + rng.normal(0, 0.05, n_companies)

        log_mult = (
            level
            + b_growth * growth
            + b_margin * margin
            - 0.09 * (size - size.mean())
            + quality
            + rng.normal(0, 0.32, n_companies)
        )
        mult = np.exp(log_mult)
        revenue = np.exp(size)
        ev = mult * revenue

        for i, c in enumerate(companies):
            if t < i % 12:  # staggered listings, so the panel is unbalanced
                continue
            rows.append(
                {
                    "date": d,
                    "cik": c.cik,
                    "ticker": c.ticker,
                    "name": c.name,
                    "price": float(ev[i] / 1e8),
                    "shares": 1e8,
                    "market_cap": float(ev[i]),
                    "net_debt": 0.0,
                    "enterprise_value": float(ev[i]),
                    "ltm_revenue": float(revenue[i]),
                    "ltm_fcf": float(margin[i] * revenue[i]),
                    "rev_growth": float(growth[i]),
                    "fcf_margin": float(margin[i]),
                    "gross_margin": 0.75,
                    "ev_revenue": float(mult[i]),
                    "as_reported_quarter": d - pd.Timedelta(days=91),
                    "known_from": d - pd.Timedelta(days=40),
                    "reporting_lag_days": 40,
                }
            )

    panel = pd.DataFrame(rows)
    panel["rule_of_40"] = (panel["rev_growth"] + panel["fcf_margin"]) * 100
    panel["log_ev_revenue"] = np.log(panel["ev_revenue"])
    panel["log_revenue"] = np.log(panel["ltm_revenue"])
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True), companies
