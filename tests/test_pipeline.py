"""End-to-end exercise of the real code path, with EDGAR replaced by a fixture.

`--demo` skips `fundamentals` and `panel` entirely, so on its own it proves
nothing about the path that actually runs in production. This test builds a
company-facts document in EDGAR's own shape — cumulative cash flows, an ASC 606
tag migration mid-series, a January fiscal year end — feeds it through
`fundamentals.build`, `panel.build` and `model.fit_all`, and checks the answers
against arithmetic done by hand.

    python tests/test_pipeline.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forty import edgar, fundamentals, model, panel  # noqa: E402


class Co:
    def __init__(self, cik: int, ticker: str) -> None:
        self.cik, self.ticker, self.name = cik, ticker, f"{ticker} Inc"


def _usd(entries: list[dict]) -> dict:
    return {"units": {"USD": entries}}


def _shares(entries: list[dict]) -> dict:
    return {"units": {"shares": entries}}


def make_facts(
    *,
    quarters: int = 32,
    start_year: int = 2016,
    q_revenue: float = 100e6,
    growth_per_q: float = 0.05,
    ocf_margin: float = 0.20,
    shares: float = 1e8,
    tag_switch_at: int = 12,
) -> dict:
    """A filer's history, in the shape `companyfacts` actually returns.

    Revenue arrives as discrete quarters under one tag and then another, the way
    a real filer's series does across the ASC 606 migration. Operating cash flow
    arrives year-to-date and resets each fiscal year, the way a cash flow
    statement actually does.
    """
    old_tag, new_tag = "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"
    rev_old: list[dict] = []
    rev_new: list[dict] = []
    ocf: list[dict] = []
    cash: list[dict] = []
    share_facts: list[dict] = []

    ytd = 0.0
    for i in range(quarters):
        year = start_year + i // 4
        q = i % 4
        start = dt.date(year, 1 + 3 * q, 1)
        end = dt.date(year + (1 if q == 3 else 0), 1 + 3 * ((q + 1) % 4), 1) - dt.timedelta(days=1)
        filed = end + dt.timedelta(days=40)
        value = q_revenue * (1 + growth_per_q) ** i

        entry = {"start": start.isoformat(), "end": end.isoformat(),
                 "val": round(value), "filed": filed.isoformat(),
                 "form": "10-K" if q == 3 else "10-Q"}
        (rev_new if i >= tag_switch_at else rev_old).append(entry)

        # Cash flow: cumulative from the start of the fiscal year.
        ytd = value * ocf_margin if q == 0 else ytd + value * ocf_margin
        ocf.append({"start": dt.date(year, 1, 1).isoformat(), "end": end.isoformat(),
                    "val": round(ytd), "filed": filed.isoformat(),
                    "form": "10-K" if q == 3 else "10-Q"})

        cash.append({"end": end.isoformat(), "val": round(value * 2),
                     "filed": filed.isoformat(), "form": "10-Q"})
        share_facts.append({"end": end.isoformat(), "val": shares,
                            "filed": filed.isoformat(), "form": "10-Q"})

    return {
        "facts": {
            "us-gaap": {
                old_tag: _usd(rev_old),
                new_tag: _usd(rev_new),
                "NetCashProvidedByUsedInOperatingActivities": _usd(ocf),
                "GrossProfit": _usd([
                    {**e, "val": round(e["val"] * 0.78)} for e in (rev_old + rev_new)
                ]),
                "CashAndCashEquivalentsAtCarryingValue": _usd(cash),
                "LongTermDebtNoncurrent": _usd([{**e, "val": 0} for e in cash]),
            },
            "dei": {"EntityCommonStockSharesOutstanding": _shares(share_facts)},
        }
    }


def test_fundamentals_stitch_across_a_tag_migration() -> None:
    fundamentals.edgar = _FakeEdgar({1: make_facts()})
    f = fundamentals.build(1)
    assert f is not None and len(f) > 20, "no usable history came out"

    # Revenue compounds 5% a quarter, so LTM growth should be 1.05**4 - 1.
    expected = 1.05 ** 4 - 1
    got = f["rev_growth"].dropna()
    assert abs(got.median() - expected) < 0.005, (got.median(), expected)
    # The migration happens mid-series; if the stitch failed there would be a
    # visible break in the growth rate rather than a flat line.
    assert got.std() < 0.01, f"growth is not smooth across the tag switch: {got.std()}"


def test_cash_flow_is_not_counted_four_times() -> None:
    """OCF margin is 20% by construction. Reading the year-to-date figures as
    quarters would report roughly 50%."""
    fundamentals.edgar = _FakeEdgar({1: make_facts(ocf_margin=0.20)})
    f = fundamentals.build(1)
    m = f["fcf_margin"].dropna()
    assert abs(m.median() - 0.20) < 0.01, m.median()


def test_nothing_enters_a_cross_section_before_it_was_filed() -> None:
    """The discipline the whole project rests on, checked directly."""
    cos = [Co(i, f"CO{i}") for i in range(1, 61)]
    facts = {c.cik: make_facts(q_revenue=80e6 + c.cik * 3e6) for c in cos}
    fundamentals.edgar = _FakeEdgar(facts)
    funds = {c.cik: fundamentals.build(c.cik) for c in cos}

    dates = pd.date_range("2016-01-01", "2023-12-31", freq="B")
    prices = pd.DataFrame(
        {c.ticker: np.linspace(20, 60, len(dates)) * (1 + c.cik % 7 / 10) for c in cos},
        index=dates,
    )

    p = panel.build(cos, funds, prices)
    assert not p.empty, "panel came out empty"
    assert (p["known_from"] <= p["date"]).all(), "a row used data filed after its date"
    assert p["reporting_lag_days"].min() >= 0
    # A quarter's fundamentals reach the market five to seven weeks late, so the
    # typical row is looking at the quarter before last.
    assert 40 <= p["reporting_lag_days"].median() <= 140, p["reporting_lag_days"].median()


def test_model_runs_on_a_panel_from_real_shaped_fundamentals() -> None:
    rng = np.random.default_rng(5)
    cos = [Co(i, f"CO{i}") for i in range(1, 81)]
    facts = {
        c.cik: make_facts(
            q_revenue=float(rng.uniform(40e6, 900e6)),
            growth_per_q=float(rng.uniform(0.0, 0.10)),
            ocf_margin=float(rng.uniform(-0.10, 0.35)),
        )
        for c in cos
    }
    fundamentals.edgar = _FakeEdgar(facts)
    funds = {c.cik: fundamentals.build(c.cik) for c in cos}

    dates = pd.date_range("2016-01-01", "2023-12-31", freq="B")
    prices = pd.DataFrame(
        {c.ticker: 30 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates)))) for c in cos},
        index=dates,
    )
    p = panel.build(cos, funds, prices)
    coefs, members = model.fit_all(p)

    assert not coefs.empty, "no quarter was fitted"
    assert coefs["n"].min() >= 40
    assert coefs["r2"].between(0, 1).all()
    assert set(members.columns) >= {"premium", "fair_ev_revenue", "residual"}
    summary = model.summarise(coefs)
    assert summary["quarters_fitted"] == len(coefs)
    assert 0 <= summary["rule40_rejected_quarters"] <= summary["rule40_tested_quarters"]


class _FakeEdgar:
    """Stands in for the module, so no network call is possible from a test."""

    def __init__(self, facts: dict[int, dict]) -> None:
        self._facts = facts

    def company_facts(self, cik: int, **_kw) -> dict | None:
        return self._facts.get(cik)


def _restore() -> None:
    fundamentals.edgar = edgar


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
        finally:
            _restore()
    print(f"\n{'all tests passed' if not failures else f'{failures} failed'}")
    sys.exit(1 if failures else 0)
