#!/usr/bin/env python3
"""Are the data sources reachable from here?

Run this before assuming the build is broken. Every source this project uses is
somebody else's free endpoint, and each fails in its own way: EDGAR returns 403
without a declared User-Agent, Yahoo rate-limits by IP, corporate and campus
networks block one or the other. This separates "the network is refusing me"
from "my code is wrong", which are otherwise indistinguishable at 8pm.

    python audit.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

CHECKS = [
    ("SEC ticker directory", "https://www.sec.gov/files/company_tickers_exchange.json", "sec"),
    ("SEC company facts (Salesforce)",
     "https://data.sec.gov/api/xbrl/companyfacts/CIK0001108524.json", "sec"),
    ("SEC company submissions",
     "https://data.sec.gov/submissions/CIK0001108524.json", "sec"),
    ("SEC SIC browse (prepackaged software)",
     "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=7372"
     "&type=10-K&count=10&output=atom", "sec"),
    ("Yahoo daily prices", "https://query1.finance.yahoo.com/v8/finance/chart/CRM"
     "?range=1y&interval=1d", "prices"),
    ("Stooq daily prices (fallback)", "https://stooq.com/q/d/l/?s=crm.us&i=d", "prices"),
]


def probe(name: str, url: str) -> dict:
    import os
    ua = os.environ.get("SEC_USER_AGENT", "Forty Research UNSET@example.com")
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
        return {"name": name, "url": url, "ok": True, "status": r.status,
                "bytes": len(body), "seconds": round(time.time() - t0, 2)}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "url": url, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.time() - t0, 2)}


def main() -> int:
    import os
    print("Forty — data source audit\n" + "=" * 62)
    if "UNSET@example.com" in os.environ.get("SEC_USER_AGENT", "UNSET@example.com"):
        print("! SEC_USER_AGENT is not set. EDGAR requires a contact address:")
        print('    export SEC_USER_AGENT="Your Name you@example.com"')
        print("  The SEC checks below will almost certainly 403 without it.\n")

    results = [probe(n, u) for n, u, _ in CHECKS]
    for r in results:
        mark = "OK  " if r["ok"] else "FAIL"
        detail = f"{r['bytes']:>10,}b  {r['seconds']:>5.2f}s" if r["ok"] else r["error"][:52]
        print(f"  [{mark}] {r['name']:<38} {detail}")

    Path("audit_results.json").write_text(json.dumps(results, indent=2))

    sec_ok = all(r["ok"] for r, (_, _, kind) in zip(results, CHECKS) if kind == "sec")
    px_ok = any(r["ok"] for r, (_, _, kind) in zip(results, CHECKS) if kind == "prices")

    print("=" * 62)
    if sec_ok and px_ok:
        print("Everything reachable. `python run.py` will work.")
        return 0
    if not sec_ok:
        print("EDGAR is unreachable — fundamentals cannot be built. Check "
              "SEC_USER_AGENT, then the network.")
    if not px_ok:
        print("No price source is reachable — try again off a corporate VPN, or "
              "run the build in GitHub Actions where both usually work.")
    print("`python run.py --demo` still works offline.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
