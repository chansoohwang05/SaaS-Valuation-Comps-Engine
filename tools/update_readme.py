#!/usr/bin/env python3
"""Write the current build's numbers into the README.

A README with hand-typed results is a README that is wrong three builds later,
and a portfolio project whose headline number does not match its own output is
worse than one with no headline number. So the findings block is generated from
`site/index.json` and nothing between the markers is written by hand.

Called automatically at the end of a non-demo `run.py`. Also runnable alone:

    python tools/update_readme.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- FINDINGS:START -->", "<!-- FINDINGS:END -->"


def render(doc: dict) -> str:
    s, meta = doc["summary"], doc["meta"]
    rej, tested = s["rule40_rejected_quarters"], s["rule40_tested_quarters"]
    L = s["latest"]

    def ratio(v) -> str:
        return f"{v:.1f}x" if v else "n/a"

    lines = [
        f"Across **{s['quarters_fitted']} quarterly cross-sections** "
        f"({s['first_quarter']} to {s['last_quarter']}), a median of "
        f"**{s['median_companies_per_quarter']:.0f} software companies** each, "
        f"median R² **{s['median_r2']:.2f}**:",
        "",
        f"- Equal weighting of growth and margin — what the Rule of 40 assumes — "
        f"is **rejected at the 5% level in {rej} of {tested} quarters**.",
        f"- Across the whole history, a point of revenue growth priced at a median "
        f"of **{ratio(s['median_growth_margin_ratio'])} a point of FCF margin**.",
        f"- As of {L['date']}: growth **{L['b_growth']:.2f}**, margin "
        f"**{L['b_margin']:.2f}**, ratio **{ratio(L['ratio'])}**, "
        f"R² {L['r2']:.2f} on {L['n']} companies.",
        "",
        "| Period | Growth | FCF margin | Growth costs | Median EV/revenue |",
        "|---|---:|---:|---:|---:|",
    ]
    for era, v in s["eras"].items():
        if v:
            lines.append(
                f"| {era} | {v['b_growth']:.2f} | {v['b_margin']:.2f} | "
                f"{ratio(v['ratio'])} | {v['median_ev_revenue']:.1f}x |"
            )
    lines += ["", f"<sub>Generated from the build of {meta['generated_at'][:10]} "
                  f"by `tools/update_readme.py` — do not edit by hand.</sub>"]
    return "\n".join(lines)


def main() -> int:
    out = ROOT / "site" / "index.json"
    if not out.exists():
        print("No build output; run `python run.py` first.")
        return 1
    doc = json.loads(out.read_text())
    if doc["meta"]["demo"]:
        print("Demo build — README not updated (generated numbers are not findings).")
        return 0

    readme = ROOT / "README.md"
    text = readme.read_text()
    if START not in text or END not in text:
        print("README is missing the FINDINGS markers.")
        return 1
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    readme.write_text(f"{head}{START}\n\n{render(doc)}\n\n{END}{tail}")
    print("README findings updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
