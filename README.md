# Forty

**The Rule of 40 weights a point of growth exactly the same as a point of margin.
The market never has.**

Twenty and twenty scores the same forty as forty and zero. That is an assertion
about how software is priced, it is used in real investment committees, and it
is testable. This repository tests it.

For every quarter since 2015, it fits a cross-sectional regression across every
US-listed software company that clears a revenue and gross-margin screen:

```
log(EV / LTM revenue) = a + b_growth · revenue growth
                          + b_margin · FCF margin
                          + b_size   · log(revenue) + e
```

If the Rule of 40 describes market pricing, `b_growth` equals `b_margin`. Each
quarter's fit produces a t-statistic on that equality, so the question gets an
answer with a standard error attached rather than an opinion.

The fundamentals come from SEC XBRL filings rather than a vendor's summary
field, and every one is dated by when it was *filed*. See
[METHOD.md](METHOD.md) — that discipline is most of what separates this from a
comps table.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export SEC_USER_AGENT="Your Name you@example.com"   # EDGAR requires this
.venv/bin/python audit.py      # is anything reachable from this network?
.venv/bin/python run.py        # ~20 min cold, ~1 min cached
.venv/bin/python serve.py      # opens the site
```

`python run.py --demo` builds the whole thing from generated data in half a
second, with no network at all, if you just want to see the page. Everything it
produces is labelled as a demo, on the page and in the JSON.

`serve.py` is needed locally because the page loads one file per company and
browsers block that on `file://` URLs. On GitHub Pages it is served over HTTP
and just works.

---

## Findings

<!-- FINDINGS:START -->

*Run `python run.py` to populate this section — it is generated from the build's
own output by `tools/update_readme.py`, so it cannot drift from the numbers on
the site.*

<!-- FINDINGS:END -->

---

## Why a comps table cannot answer this

The obvious version of this project — the one this repository used to be — pulls
a handful of tickers from a market data API, computes EV/Revenue and EV/EBITDA,
and prints a table. Four things go wrong, and all four are fatal to the
question:

**A multiple compared across companies with different growth means nothing.**
Palantir at 66x and Salesforce at 4x is not a finding, it is a restatement of the
fact that one grows at 90% and the other at 13%. The only way to make multiples
comparable is to condition on what drives them, which is a regression.

**Eight hand-picked tickers is a preference, not a universe.** Any statistic
computed on names chosen in 2026 inherits the knowledge of which ones survived.
Here the universe is a rule — SEC SIC codes, a revenue floor, a gross-margin
floor — applied to each quarter as it stood, so companies enter at IPO and leave
at delisting the way they actually did.

**A vendor's `ebitda` field is not comparable across software companies.** The
old script computed EV/EBITDA for companies with negative EBITDA and printed
-101x and 3,610x as though they were valuations. Revenue and free cash flow are
the two lines in software that mean the same thing at every company, so those are
what the model uses.

**One snapshot cannot show a change.** The interesting quantity is not what the
market pays for growth today but how much that has moved — and it has moved far
more than the multiple itself. That needs a decade of cross-sections.

## Layout

```
forty/
  config.py        every threshold, in one place
  edgar.py         cached, rate-limited SEC client
  universe.py      SIC codes -> the software universe
  fundamentals.py  XBRL -> LTM revenue, growth, FCF margin, net debt
  prices.py        price history -> point-in-time market cap and EV
  panel.py         company x quarter, with nothing dated before it was public
  model.py         the regression, robust standard errors, the equality test
  export.py        search index + one JSON per company
  synthetic.py     generated panel for the offline demo and the tests
run.py             orchestrator
audit.py           are the data sources reachable from here?
serve.py           local preview server
tests/             the estimator, checked against known coefficients
site/              the page
```

Deployed by GitHub Actions on every push and on a nightly schedule; the workflow
runs the tests first and refuses to publish a build that looks thin or that was
generated in demo mode.

## Known limits — read this one

**The model has three variables and the market has more.** A company above the
line may be growing into it, may have a revenue mix the model cannot see, or may
simply be expensive. The residual is a question worth asking about a company, not
an answer about it. Nothing here is investment advice.

**Free cash flow flatters software.** Operating cash flow adds back stock-based
compensation, which for a software company can be 20-30% of revenue and is a real
cost to shareholders. The Rule of 40 is conventionally computed this way, so the
model computes it this way to test the rule as used — but the FCF margins here are
not the margins a cash-basis owner would experience.

**Each quarter is fit on one quarter of data.** Roughly 200-400 companies, so the
individual estimates are noisy and a single quarter's ratio should not be quoted
on its own. The count of quarters rejecting equal weighting is the robust
statistic, which is why it leads.

**Coefficients are associations, not mechanisms.** That the market pays more per
point of growth does not establish that growth causes the multiple. Both respond
to the same rate environment, among other things.

**Coverage thins at the small end.** Companies below $50m of revenue are excluded
because their multiples are dominated by things this model does not contain. The
gross-margin screen also drops IT-services firms that file under software SIC
codes, which is deliberate and which someone could reasonably draw differently —
`forty/config.py` is where to change it.

**Fundamentals are as first reported, not restated.** A company that later
corrected its 2019 revenue still appears in the 2019 cross-sections with the
number it originally filed. That is the point — it is what the market saw — but
it means these figures will not always tie to a current data terminal.

## Earlier version

`archive/tableau_dashboard_v0.png` is the Tableau dashboard from the first
version of this project, which pulled eight tickers from Yahoo into a CSV. It is
kept because the contrast is the story: the same interest, asked as a question
that has an answer.
