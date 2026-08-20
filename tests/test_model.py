"""Checks that the estimator does what the README says it does.

The live data sources cannot be reached from every environment, so the maths is
verified against generated data with coefficients that are known by construction.
If `ols_hc1` cannot recover a planted coefficient, nothing downstream is worth
reading.

    python -m pytest tests/ -q      (or simply: python tests/test_model.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forty import fundamentals, model, panel  # noqa: E402


def test_ols_recovers_known_coefficients() -> None:
    rng = np.random.default_rng(0)
    n = 5000
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    y = 1.5 + 3.0 * x1 - 0.7 * x2 + rng.normal(scale=0.5, size=n)
    fit = model.ols_hc1(y, np.column_stack([np.ones(n), x1, x2]))
    assert np.allclose(fit["beta"], [1.5, 3.0, -0.7], atol=0.05), fit["beta"]
    assert fit["r2"] > 0.95


def test_hc1_standard_errors_survive_heteroskedasticity() -> None:
    """Under non-constant error variance, HC1 must stay honest where classical
    standard errors do not. Verified by simulation: a nominal 95% interval
    should contain the truth about 95% of the time."""
    rng = np.random.default_rng(1)
    covered_hc1 = covered_classical = 0
    trials = 400
    for _ in range(trials):
        n = 300
        x = rng.normal(size=n)
        # Error scale rises with x — exactly the pattern valuation errors show.
        y = 2.0 * x + rng.normal(scale=0.5 + 1.5 * np.abs(x), size=n)
        X = np.column_stack([np.ones(n), x])
        fit = model.ols_hc1(y, X)
        if abs(fit["beta"][1] - 2.0) < 1.96 * fit["se"][1]:
            covered_hc1 += 1
        s2 = float(fit["resid"] @ fit["resid"]) / (n - 2)
        se_classical = np.sqrt(s2 * np.linalg.pinv(X.T @ X)[1, 1])
        if abs(fit["beta"][1] - 2.0) < 1.96 * se_classical:
            covered_classical += 1
    hc1_rate = covered_hc1 / trials
    assert 0.91 < hc1_rate < 0.99, hc1_rate
    assert hc1_rate > covered_classical / trials


def _cross_section(rng, b_growth: float, b_margin: float, n: int = 400) -> pd.DataFrame:
    growth = rng.uniform(-0.05, 0.60, n)
    margin = rng.uniform(-0.35, 0.40, n)
    size = rng.uniform(18, 26, n)
    log_mult = (
        1.0 + b_growth * growth + b_margin * margin - 0.10 * size
        + rng.normal(scale=0.30, size=n)
    )
    return pd.DataFrame(
        {
            "date": pd.Timestamp("2024-06-30"),
            "ticker": [f"T{i}" for i in range(n)],
            "log_ev_revenue": log_mult,
            "ev_revenue": np.exp(log_mult),
            "rev_growth": growth,
            "fcf_margin": margin,
            "log_revenue": size,
        }
    )


def test_pipeline_recovers_the_planted_pricing() -> None:
    """A cross-section built so growth is priced at four times margin must come
    back out of `fit_quarter` that way, size control and winsorising included."""
    rng = np.random.default_rng(2)
    fit = model.fit_quarter(_cross_section(rng, 4.0, 1.0, n=3000))
    assert abs(fit["b_growth"] - 4.0) < 0.15, fit["b_growth"]
    assert abs(fit["b_margin"] - 1.0) < 0.15, fit["b_margin"]
    assert abs(fit["b_size"] + 0.10) < 0.02, fit["b_size"]
    assert abs(fit["growth_margin_ratio"] - 4.0) < 0.5, fit["growth_margin_ratio"]
    assert fit["rule_of_40_test"]["significant"] is True


def test_equality_test_has_the_right_error_rates() -> None:
    """A single significant quarter proves nothing — at a 5% threshold, one
    cross-section in twenty rejects by chance. What must hold is the rate:
    close to 5% when growth and margin really are priced equally, and close to
    100% when they are not. This is why the README counts rejected quarters
    rather than pointing at one."""
    rng = np.random.default_rng(7)
    trials = 200

    false_rejections = sum(
        model.fit_quarter(_cross_section(rng, 2.0, 2.0))["rule_of_40_test"]["significant"]
        for _ in range(trials)
    )
    assert 0.01 < false_rejections / trials < 0.12, false_rejections / trials

    true_rejections = sum(
        model.fit_quarter(_cross_section(rng, 4.0, 1.0))["rule_of_40_test"]["significant"]
        for _ in range(trials)
    )
    assert true_rejections / trials > 0.95, true_rejections / trials


def test_winsorising_the_dependent_variable_would_attenuate() -> None:
    """The reason `fit_quarter` clips inputs but not the multiple. Clipping the
    left-hand side pulls the coefficient toward zero; this measures it, so the
    choice is documented rather than asserted."""
    rng = np.random.default_rng(11)
    cs = _cross_section(rng, 4.0, 1.0, n=3000)
    honest = model.fit_quarter(cs)

    clipped = cs.copy()
    clipped["log_ev_revenue"] = panel.winsorize(clipped["log_ev_revenue"], 0.02)
    biased = model.fit_quarter(clipped)

    assert abs(honest["b_growth"] - 4.0) < abs(biased["b_growth"] - 4.0)
    assert biased["b_growth"] < honest["b_growth"]


def test_premium_is_zero_on_average() -> None:
    """The premium is a residual, so the median company must sit near zero.
    A systematic offset would mean the model is mispricing the whole sector and
    calling it a stock-specific signal."""
    rng = np.random.default_rng(3)
    n = 300
    growth = rng.uniform(0, 0.5, n)
    log_mult = 1.0 + 3.0 * growth + rng.normal(scale=0.3, size=n)
    cs = pd.DataFrame(
        {
            "date": pd.Timestamp("2024-06-30"),
            "ticker": [f"T{i}" for i in range(n)],
            "log_ev_revenue": log_mult,
            "ev_revenue": np.exp(log_mult),
            "rev_growth": growth,
            "fcf_margin": rng.uniform(-0.2, 0.3, n),
            "log_revenue": rng.uniform(18, 26, n),
        }
    )
    fit = model.fit_quarter(cs)
    assert abs(fit["companies"]["premium"].median()) < 0.05


def test_quarterly_derivation_from_cumulative_filings() -> None:
    """Cash flow arrives year-to-date. Q2 must come out as the half year minus
    Q1, and Q4 as the full year minus nine months — not as the filed number."""
    facts = {
        "facts": {
            "us-gaap": {
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            _f("2023-01-01", "2023-03-31", 100, "2023-04-28"),
                            _f("2023-01-01", "2023-06-30", 250, "2023-07-28"),
                            _f("2023-01-01", "2023-09-30", 420, "2023-10-27"),
                            _f("2023-01-01", "2023-12-31", 600, "2024-02-15", form="10-K"),
                        ]
                    }
                }
            }
        }
    }
    q = fundamentals._quarterly(
        fundamentals._duration_facts(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    )
    got = {str(d.date()): v for d, v in q["val"].items()}
    assert got == {
        "2023-03-31": 100,
        "2023-06-30": 150,
        "2023-09-30": 170,
        "2023-12-31": 180,
    }, got
    # The Q4 figure only became knowable when the 10-K landed.
    assert str(q.loc[pd.Timestamp("2023-12-31"), "filed"].date()) == "2024-02-15"


def test_ltm_refuses_to_span_a_gap() -> None:
    """Four quarters with one missing is a nine-month year. It must be dropped,
    not summed, or the company appears to have shrunk 25% overnight."""
    q = pd.DataFrame(
        {"val": [100, 110, 120, 130], "filed": pd.to_datetime(
            ["2022-05-01", "2022-08-01", "2023-11-01", "2024-02-01"])},
        index=pd.to_datetime(["2022-03-31", "2022-06-30", "2023-09-30", "2023-12-31"]),
    )
    assert _rows(fundamentals._ltm(q)) == 0

    clean = pd.DataFrame(
        {"val": [100, 110, 120, 130, 140], "filed": pd.to_datetime(
            ["2022-05-01", "2022-08-01", "2022-11-01", "2023-02-01", "2023-05-01"])},
        index=pd.to_datetime(
            ["2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31", "2023-03-31"]),
    )
    ltm = fundamentals._ltm(clean)
    assert _rows(ltm) == 2
    assert ltm["ltm"].iloc[0] == 460  # 100+110+120+130


def test_winsorize_clips_rather_than_drops() -> None:
    s = pd.Series([1.0] * 98 + [500.0, -400.0])
    w = panel.winsorize(s, 0.02)
    assert len(w) == len(s)
    assert w.max() < 500 and w.min() > -400


def _f(start: str, end: str, val: float, filed: str, form: str = "10-Q") -> dict:
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def _rows(df: pd.DataFrame) -> int:
    return int(len(df))


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  pass  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'all tests passed' if not failures else f'{failures} failed'}")
    sys.exit(1 if failures else 0)
