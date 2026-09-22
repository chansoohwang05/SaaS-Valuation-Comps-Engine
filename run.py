#!/usr/bin/env python3
"""Forty — build.

    python run.py                  full build from SEC filings and market prices
    python run.py --quotes         intraday: new prices, cached filings, refit
    python run.py --demo           generated data, no network, for a quick look
    python run.py --limit 150      first N companies only, for development
    python run.py --force          ignore every cache and re-fetch

A first full run fetches a few thousand documents from EDGAR and takes roughly
twenty minutes. Everything is cached, so later runs take about a minute unless
new filings have landed.

Then, because the page loads one file per company and browsers block that on
file:// URLs:

    python serve.py
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from forty import config, edgar, export, fundamentals, model, panel, prices, universe
from forty.edgar import FetchError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="build from generated data; requires no network and "
                         "labels every output as a demo")
    ap.add_argument("--force", action="store_true", help="ignore caches")
    ap.add_argument("--limit", type=int, default=0, help="cap the universe size")
    ap.add_argument("--quotes", action="store_true",
                    help="intraday refresh: re-fetch prices and refit, leaving "
                         "filings alone. Multiples move with the price all day; "
                         "the filings behind them do not change until the next "
                         "10-Q, so a run every half hour must not touch EDGAR or "
                         "it burns the rate limit the nightly build needs.")
    args = ap.parse_args()

    t0 = time.time()
    print("Forty — what the market pays for growth\n" + "=" * 64)

    if args.demo:
        print("[1/5] DEMO MODE — generated data, not SEC filings")
        pnl, companies = __import__("forty.synthetic", fromlist=["build"]).build()
        lineage = {"source": "generated", "demo": True}
    else:
        if "UNSET@example.com" in config.USER_AGENT:
            print("  ! SEC_USER_AGENT is not set. EDGAR requires a real contact\n"
                  "    address on every request and will return 403 without one:\n"
                  '      export SEC_USER_AGENT="Your Name you@example.com"')
            return 2

        print("[1/5] universe")
        try:
            companies = universe.build(
                force=args.force, limit=args.limit, cached_only=args.quotes
            )
        except (FetchError, RuntimeError) as exc:
            # A blocked network is the single most common reason this fails, and
            # a stack trace is a bad way to learn it. Say which it is.
            print(f"\n  Could not reach EDGAR: {exc}\n\n"
                  "  This is almost always the network rather than the code.\n"
                  "    python audit.py       checks every source and says which failed\n"
                  "    python run.py --demo  builds the site offline from generated data\n"
                  "  Corporate and campus networks commonly block sec.gov; GitHub\n"
                  "  Actions does not, so pushing is often the fastest fix.")
            return 3

        if not companies:
            print("\n  Empty universe — nothing to build.\n"
                  "  On an intraday run this means the filing cache was evicted;\n"
                  "  the next nightly build will repopulate it. Otherwise, check\n"
                  "  `python audit.py`.")
            return 3

        print(f"      {len(companies)} listed filers under SIC "
              f"{', '.join(str(s) for s in sorted(config.SIC_CODES))}")

        label = "cached filings (intraday)" if args.quotes else "SEC XBRL company facts"
        print(f"[2/5] fundamentals — {label}")
        funds, failed = {}, 0
        for i, c in enumerate(companies, 1):
            try:
                f = fundamentals.build(
                    c.cik,
                    force=args.force and not args.quotes,
                    max_age_days=None if args.quotes else 1,
                    cached_only=args.quotes,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"      ! {c.ticker}: {type(exc).__name__}: {exc}")
                f = None
            if f is None:
                failed += 1
            else:
                funds[c.cik] = f
            if i % 50 == 0 or i == len(companies):
                print(f"      {i}/{len(companies)} — {len(funds)} usable, "
                      f"{failed} without enough XBRL history")

        print("[3/5] prices")
        tickers = [c.ticker for c in companies if c.cik in funds]
        # An intraday run exists precisely to move the prices, so it always
        # re-fetches them even though it leaves everything else on cache.
        try:
            px = prices.fetch(tickers, force=args.force or args.quotes)
        except RuntimeError as exc:
            print(f"\n  {exc}\n\n"
                  "  Yahoo and Stooq were both unreachable. This is a network\n"
                  "  fact, not a bug — `python audit.py` will confirm which.")
            return 3
        print(f"      {px.shape[1]}/{len(tickers)} tickers, {len(px)} trading days")

        print("[4/5] panel")
        pnl = panel.build(companies, funds, px)
        lineage = {
            "source": "SEC EDGAR XBRL company facts + daily closes",
            "demo": False,
            "intraday": bool(args.quotes),
            "cache": edgar.cache_stats(),
        }

    if pnl.empty:
        print("      panel is empty — nothing survived the screens")
        return 1

    print(f"      {len(pnl):,} company-quarters, "
          f"{pnl['ticker'].nunique()} companies, "
          f"{pnl['date'].nunique()} quarters")
    if not args.demo:
        print(f"      median reporting lag {pnl['reporting_lag_days'].median():.0f} days "
              "(fundamentals are as-filed, never backdated)")

    print("[5/5] model")
    coefs, members = model.fit_all(pnl)
    if coefs.empty:
        print(f"      no quarter had {config.MIN_PANEL_N}+ companies; nothing fitted")
        return 1
    summary = model.summarise(coefs)

    meta = {
        "title": "Forty",
        "subtitle": "A point of growth was worth 2.4 points of margin in 2021 and "
                    "0.8 across the past two years. The Rule of 40 calls them equal.",
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "demo": bool(args.demo),
        "lineage": lineage,
        "screens": {
            "sic_codes": sorted(config.SIC_CODES),
            "min_ltm_revenue_usd": config.MIN_LTM_REVENUE,
            "min_gross_margin": config.MIN_GROSS_MARGIN,
            "min_companies_per_cross_section": config.MIN_PANEL_N,
            "winsorised_at": config.WINSOR,
        },
    }
    stats = export.write(coefs, members, summary, meta)

    print("=" * 64)
    rej, tested = summary["rule40_rejected_quarters"], summary["rule40_tested_quarters"]
    print(f"Quarters fitted:        {summary['quarters_fitted']} "
          f"({summary['first_quarter']} to {summary['last_quarter']})")
    print(f"Median companies:       {summary['median_companies_per_quarter']:.0f} per cross-section")
    print(f"Median R-squared:       {summary['median_r2']:.2f}")
    print(f"Equal weighting rejected in {rej} of {tested} quarters "
          f"({rej / tested:.0%})" if tested else "")
    if summary["median_growth_margin_ratio"]:
        print(f"Median price of growth: {summary['median_growth_margin_ratio']:.1f}x "
              "a point of margin")
    print()
    for era, v in summary["eras"].items():
        if v:
            r = f"{v['ratio']:.1f}x" if v["ratio"] else "n/a"
            print(f"  {era:<26} growth {v['b_growth']:>5.2f}  "
                  f"margin {v['b_margin']:>5.2f}  ratio {r:>6}  "
                  f"median multiple {v['median_ev_revenue']:.1f}x")
    print()
    print(f"index  {stats['index_kb']:.0f} KB")
    print(f"shards {stats['shards']} files, {stats['shard_mb']:.1f} MB")

    # Keep the README's headline numbers tied to the build that produced them.
    # Not on intraday runs: the coefficients barely move between 10am and 2pm,
    # and a commit every half hour would bury the repository's real history.
    if not args.demo and not args.quotes:
        sys.path.insert(0, str(config.ROOT / "tools"))
        import update_readme

        update_readme.main()

    print(f"\nBuilt in {time.time() - t0:.1f}s.  Run:  python serve.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
