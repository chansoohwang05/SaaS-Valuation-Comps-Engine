"""The model, and the test the whole project exists to run.

The Rule of 40 says a software company is healthy when revenue growth plus free
cash flow margin exceeds forty. Its arithmetic gives a point of growth and a
point of margin exactly equal weight — twenty and twenty is the same score as
forty and zero.

That is a claim about how the market prices software, and it can be checked.
Fit, separately in each quarter:

    log(EV / LTM revenue) = a + b_g x growth + b_m x FCF margin
                              + b_s x log(revenue) + e

If the Rule of 40 describes market pricing, b_g equals b_m. Every quarter of
the estimate produces a t-statistic on that equality, so the question is not
argued, it is answered with a number, quarter by quarter, for a decade.

Three implementation notes, each of which changes the answer:

**Logs.** Multiples are bounded below by zero and have a long right tail. In
levels, one company at 90x drags the fit; in logs the model is estimating a
proportional relationship, so a coefficient reads as "a percentage point of
growth is worth b_g percent on the multiple" — which is how the quantity is
actually used.

**Robust standard errors.** Valuation errors are wildly heteroskedastic: the
model misses by half a turn on a mature company and by fifteen on a hypergrowth
one. Classical standard errors assume they miss by the same amount everywhere
and would overstate significance. HC1 does not assume that.

**Size control.** Large companies trade at lower revenue multiples than small
ones at identical growth, and large companies also grow more slowly. Without
log(revenue) in the regression, that size effect loads onto the growth
coefficient and the model reports the market paying for growth when part of
what it sees is the market paying for being small.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, panel as panel_mod

FEATURES = ["rev_growth", "fcf_margin", "log_revenue"]


def ols_hc1(y: np.ndarray, X: np.ndarray) -> dict:
    """Least squares with heteroskedasticity-consistent (HC1) covariance.

    Written out rather than imported so that every step of the estimate is on
    the page and can be checked against a textbook. `tests/test_model.py`
    verifies it against known coefficients on generated data.
    """
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    dof = max(n - k, 1)

    # HC1: the White sandwich with the small-sample correction n/(n-k).
    meat = (X * (resid ** 2)[:, None]).T @ X
    cov = XtX_inv @ meat @ XtX_inv * (n / dof)

    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, beta / se, np.nan)

    return {
        "beta": beta,
        "se": se,
        "t": t,
        "cov": cov,
        "resid": resid,
        "r2": r2,
        "adj_r2": 1 - (1 - r2) * (n - 1) / dof if np.isfinite(r2) else np.nan,
        "n": n,
    }


def _equality_test(fit: dict, i: int, j: int) -> dict:
    """t-test of b_i = b_j, the Rule of 40's implicit assumption.

    Var(b_i - b_j) needs the covariance term. Growth and margin are negatively
    correlated across software companies — that is the whole growth-versus-
    profitability trade-off — so ignoring the covariance would materially
    misstate the standard error of the difference.
    """
    b, cov = fit["beta"], fit["cov"]
    diff = float(b[i] - b[j])
    var = float(cov[i, i] + cov[j, j] - 2 * cov[i, j])
    if var <= 0:
        return {"difference": diff, "t": None, "significant": None}
    t = diff / np.sqrt(var)
    return {
        "difference": diff,
        "t": float(t),
        # 1.96 is the 5% two-sided normal critical value; cross-sections here
        # run 80-400 observations, where t and normal are indistinguishable.
        "significant": bool(abs(t) > 1.96),
    }


def fit_quarter(cs: pd.DataFrame) -> dict | None:
    """One cross-section: every company in the universe on a single date."""
    d = cs.dropna(subset=["log_ev_revenue"] + FEATURES).copy()
    if len(d) < config.MIN_PANEL_N:
        return None

    # Winsorise the inputs only. The dependent variable's outlier treatment is
    # the log transform itself; clipping it as well would attenuate exactly the
    # coefficients being estimated, and it does so by a measurable amount —
    # `tests/test_model.py` demonstrates the bias.
    for col in ["rev_growth", "fcf_margin"]:
        d[col] = panel_mod.winsorize(d[col])

    y = d["log_ev_revenue"].to_numpy(float)
    X = np.column_stack([np.ones(len(d))] + [d[f].to_numpy(float) for f in FEATURES])
    fit = ols_hc1(y, X)

    b = fit["beta"]
    b_growth, b_margin = float(b[1]), float(b[2])

    # The headline quantity: how many points of margin the market would accept
    # in exchange for one point of growth. The Rule of 40 asserts this is 1.
    # It is only meaningful when the market is paying for margin at all, so a
    # near-zero or negative denominator returns None rather than a large number
    # that looks like a finding.
    ratio = (
        b_growth / b_margin
        if b_margin > 0.05 and abs(fit["t"][2]) > 1.0
        else None
    )

    d["fitted_log"] = X @ b
    d["residual"] = fit["resid"]
    d["fair_ev_revenue"] = np.exp(d["fitted_log"])
    # exp(residual) - 1: how far above or below the multiple its own growth,
    # margin and size imply, in percent. This is the per-company output.
    d["premium"] = np.exp(d["residual"]) - 1.0

    return {
        "date": cs["date"].iloc[0],
        "n": int(fit["n"]),
        "r2": float(fit["r2"]),
        "adj_r2": float(fit["adj_r2"]),
        "intercept": float(b[0]),
        "b_growth": b_growth,
        "b_margin": b_margin,
        "b_size": float(b[3]),
        "se_growth": float(fit["se"][1]),
        "se_margin": float(fit["se"][2]),
        "t_growth": float(fit["t"][1]),
        "t_margin": float(fit["t"][2]),
        "t_size": float(fit["t"][3]),
        "growth_margin_ratio": ratio,
        "rule_of_40_test": _equality_test(fit, 1, 2),
        "median_ev_revenue": float(d["ev_revenue"].median()),
        "companies": d,
    }


def fit_all(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit every quarter. Returns (coefficient history, per-company residuals)."""
    coefs, members = [], []
    for date, cs in panel.groupby("date", sort=True):
        fit = fit_quarter(cs)
        if fit is None:
            continue
        members.append(fit.pop("companies"))
        test = fit.pop("rule_of_40_test")
        fit["rule40_difference"] = test["difference"]
        fit["rule40_t"] = test["t"]
        fit["rule40_rejected"] = test["significant"]
        coefs.append(fit)

    if not coefs:
        return pd.DataFrame(), pd.DataFrame()

    return (
        pd.DataFrame(coefs).set_index("date").sort_index(),
        pd.concat(members).sort_values(["date", "ticker"]),
    )


def summarise(coefs: pd.DataFrame) -> dict:
    """The findings, stated as numbers so the README cannot drift from them."""
    if coefs.empty:
        return {}

    rejected = coefs["rule40_rejected"].dropna()
    ratio = coefs["growth_margin_ratio"].dropna()

    def era(lo: str, hi: str) -> dict:
        sl = coefs.loc[lo:hi]
        if sl.empty:
            return {}
        return {
            "quarters": int(len(sl)),
            "b_growth": float(sl["b_growth"].mean()),
            "b_margin": float(sl["b_margin"].mean()),
            "ratio": float(sl["growth_margin_ratio"].dropna().median())
            if sl["growth_margin_ratio"].notna().any()
            else None,
            "median_ev_revenue": float(sl["median_ev_revenue"].median()),
        }

    return {
        "quarters_fitted": int(len(coefs)),
        "first_quarter": str(coefs.index[0].date()),
        "last_quarter": str(coefs.index[-1].date()),
        "median_companies_per_quarter": float(coefs["n"].median()),
        "median_r2": float(coefs["r2"].median()),
        "rule40_rejected_quarters": int(rejected.sum()),
        "rule40_tested_quarters": int(len(rejected)),
        "median_growth_margin_ratio": float(ratio.median()) if len(ratio) else None,
        "latest": {
            "date": str(coefs.index[-1].date()),
            "b_growth": float(coefs["b_growth"].iloc[-1]),
            "b_margin": float(coefs["b_margin"].iloc[-1]),
            "ratio": (
                float(coefs["growth_margin_ratio"].iloc[-1])
                if pd.notna(coefs["growth_margin_ratio"].iloc[-1])
                else None
            ),
            "r2": float(coefs["r2"].iloc[-1]),
            "n": int(coefs["n"].iloc[-1]),
        },
        "eras": {
            "2015-2019 (pre-pandemic)": era("2015", "2019"),
            "2020-2021 (zero rates)": era("2020", "2021"),
            "2022-2023 (repricing)": era("2022", "2023"),
            "2024-now": era("2024", "2030"),
        },
    }
