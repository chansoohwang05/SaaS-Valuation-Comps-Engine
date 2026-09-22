# Forty

**In 2021 the market paid 2.4 points of free cash flow margin for one point of
revenue growth. Today it pays 0.8. The Rule of 40 treats the two as equal — and
averaged across seven years it is roughly right, which is exactly what makes it
misleading.**

Twenty and twenty scores the same forty as forty and zero. That is an assertion
about how software is priced, it is used in real investment committees, and it
is testable. This repository tests it quarter by quarter, and the answer is not
the one it was built to find: equal weighting is rejected in only 5 of 30
quarters, and the median price of growth is 1.2x a point of margin. The rule
survives on average. It survives because the eras cancel.

For every quarter in which at least forty US-listed software companies clear the
revenue and gross-margin screens — in practice 2019 onward, as XBRL tagging
thins out before that — it fits a cross-sectional regression:

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

## Running it

**The build runs in CI, not on your laptop.** Push to `main` and GitHub Actions
fetches the filings, fits every quarterly cross-section, writes the findings
into this README, and deploys the site. Nothing needs configuring first — not
even an API key, because there isn't one.

After that it maintains itself on two schedules: a full rebuild each weeknight
that refetches filings and refits every quarter, and a prices-only refresh every
thirty minutes through the US session, so the multiples on the page move with the
market rather than with the last time anyone remembered to run something.

```bash
git push origin main
```

Then, once: **Settings → Pages → Source → GitHub Actions**. That is the only
click.

Two optional refinements, neither of which blocks anything:

- **Settings → Secrets → Actions → `SEC_USER_AGENT`**, set to
  `Your Name your@email.com`. EDGAR requires a contact address on every request;
  without the secret the build derives one from the repository owner, which
  works but is less courteous.
- **Actions → Build and deploy → Run workflow**, with `limit` set to `150`. A
  five-minute smoke test over the largest names that proves the pipeline runs
  end to end. It deliberately does not deploy or touch the README.

### Locally, if you want to see it before the world does

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py --demo    # generated data, no network, half a second
.venv/bin/python serve.py         # opens the site
```

`--demo` labels everything it produces as a demo, on the page and in the JSON,
so generated numbers can never be mistaken for findings. For the real thing
locally you need EDGAR reachable from your network, which is not a given:

```bash
export SEC_USER_AGENT="Your Name your@email.com"
.venv/bin/python audit.py    # is anything reachable from here?
.venv/bin/python run.py      # ~20 min cold, ~1 min cached
```

If the audit fails, that is a network fact and not a bug — push instead and read
the numbers off the Actions log.

`serve.py` is needed locally because the page loads one file per company and
browsers block that on `file://` URLs. On GitHub Pages it is served over HTTP
and just works.

---

## Findings

<!-- FINDINGS:START -->

Across **30 quarterly cross-sections** (2019-03-31 to 2026-06-30), a median of **81 software companies** each, median R² **0.27**:

- Equal weighting of growth and margin — what the Rule of 40 assumes — is **rejected at the 5% level in 5 of 30 quarters**.
- Across the whole history, a point of revenue growth priced at a median of **1.2x a point of FCF margin**.
- As of 2026-06-30: growth **4.69**, margin **0.85**, ratio **n/a**, R² 0.36 on 100 companies.

| Period | Growth | FCF margin | Growth costs | Median EV/revenue |
|---|---:|---:|---:|---:|
| 2015-2019 (pre-pandemic) | 2.30 | 1.77 | 1.3x | 6.7x |
| 2020-2021 (zero rates) | 2.69 | 0.92 | 2.4x | 10.1x |
| 2022-2023 (repricing) | 1.40 | 1.27 | 0.9x | 4.9x |
| 2024-now | 2.47 | 2.11 | 0.8x | 4.2x |

<sub>Generated from the build of 2026-09-22 by `tools/update_readme.py` — do not edit by hand.</sub>

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

Deployed by GitHub Actions on every push and on a nightly schedule. The workflow
runs the tests before it is allowed to fetch anything, refuses to publish a build
that looks thin or that was generated in demo mode, and commits the findings
above back to this file so the README cannot disagree with the site.

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
