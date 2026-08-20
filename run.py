#!/usr/bin/env python3
"""Forty — build.

    python run.py                  full build from SEC filings and market prices
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="build from generated data; requires no network and "
                         "labels every output as a demo")
    ap.add_argument("--force", action="store_true", help="ignore caches")
    ap.add_argument("--limit", type=int, default=0, help="cap the universe size")
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
        companies = universe.build(force=args.force, limit=args.limit)
        print(f"      {len(companies)} listed filers under SIC "
              f"{', '.join(str(s) for s in sorted(config.SIC_CODES))}")

        print("[2/5] fundamentals — SEC XBRL company facts")
        funds, failed = {}, 0
        for i, c in enumerate(companies, 1):
            try:
                f = fundamentals.build(c.cik, force=args.force)
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
        px = prices.fetch(tickers, force=args.force)
        print(f"      {px.shape[1]}/{len(tickers)} tickers, {len(px)} trading days")

        print("[4/5] panel")
        pnl = panel.build(companies, funds, px)
        lineage = {
            "source": "SEC EDGAR XBRL company facts + daily closes",
            "demo": False,
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
        "subtitle": "The Rule of 40 weights a point of growth the same as a point "
                    "of margin. The market never has.",
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
    if not args.demo:
        sys.path.insert(0, str(config.ROOT / "tools"))
        import update_readme

        update_readme.main()

    print(f"\nBuilt in {time.time() - t0:.1f}s.  Run:  python serve.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
