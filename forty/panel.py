"""Assembling the cross-sections.

One row per company per calendar quarter, and the rule that makes the whole
thing defensible: a row dated 2021-06-30 contains only information that was
public on 2021-06-30. The price is that day's close. The fundamentals are from
the most recent quarter *whose filing date had already passed* — which in
practice is the quarter before last, because a 10-Q lands five to seven weeks
after the period it describes.

That lag is not a flaw to be corrected. It is what an investor actually had.
Pairing a June 30 price with June 30 fundamentals, as most quick builds do,
credits the market with knowing a number it would not see until August, and it
inflates every relationship in the model — most of all the growth coefficient,
because growth is the number the market is trying to anticipate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, prices as px


def quarter_ends(start: str, end: pd.Timestamp) -> list[pd.Timestamp]:
    return list(pd.date_range(start=start, end=end, freq="QE"))


def build(
    companies: list,
    funds: dict[int, pd.DataFrame],
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """The panel: company x quarter, with everything the model reads."""
    dates = quarter_ends(config.HISTORY_START, prices.index.max())
    rows: list[dict] = []

    for c in companies:
        f = funds.get(c.cik)
        if f is None or f.empty:
            continue
        known = f["known_from"]

        for d in dates:
            # The latest fundamental row that had been filed by this date.
            eligible = f[known <= d]
            if eligible.empty:
                continue
            row = eligible.iloc[-1]

            price = px.as_of(prices, c.ticker, d)
            if price is None:
                continue

            shares = row.get("shares")
            if shares is None or not np.isfinite(shares) or shares <= 0:
                continue

            revenue = float(row["ltm_revenue"])
            if revenue < config.MIN_LTM_REVENUE:
                continue
            gm = row.get("gross_margin")
            if gm is None or not np.isfinite(gm) or gm < config.MIN_GROSS_MARGIN:
                continue
            growth = row.get("rev_growth")
            if growth is None or not np.isfinite(growth):
                continue

            market_cap = price * float(shares)
            ev = market_cap + float(row["net_debt"])
            if ev <= 0:
                continue  # net cash exceeds market cap; the multiple is meaningless

            rows.append(
                {
                    "date": d,
                    "cik": c.cik,
                    "ticker": c.ticker,
                    "name": c.name,
                    "price": price,
                    "shares": float(shares),
                    "market_cap": market_cap,
                    "net_debt": float(row["net_debt"]),
                    "enterprise_value": ev,
                    "ltm_revenue": revenue,
                    "ltm_fcf": float(row["ltm_fcf"]) if np.isfinite(row["ltm_fcf"]) else np.nan,
                    "rev_growth": float(growth),
                    "fcf_margin": float(row["fcf_margin"])
                    if np.isfinite(row["fcf_margin"])
                    else np.nan,
                    "gross_margin": float(gm),
                    "ev_revenue": ev / revenue,
                    "as_reported_quarter": row.name,
                    "known_from": row["known_from"],
                    "reporting_lag_days": (d - row["known_from"]).days,
                }
            )

    panel = pd.DataFrame(rows)
    if panel.empty:
        return panel

    panel["rule_of_40"] = (panel["rev_growth"] + panel["fcf_margin"]) * 100
    panel["log_ev_revenue"] = np.log(panel["ev_revenue"])
    panel["log_revenue"] = np.log(panel["ltm_revenue"])
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True)


def winsorize(s: pd.Series, frac: float = config.WINSOR) -> pd.Series:
    """Clip to the frac / 1-frac quantiles.

    Deleting outliers would quietly remove the most interesting companies from
    the sample — the fastest growers and the most expensive multiples are
    exactly the observations a model of growth pricing should be fitting.
    Clipping keeps them and bounds their leverage.
    """
    if s.notna().sum() < 10:
        return s
    lo, hi = s.quantile(frac), s.quantile(1 - frac)
    return s.clip(lo, hi)
