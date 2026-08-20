# Method

Every decision in this repository that a reader could reasonably disagree with,
stated so they can disagree with it precisely. The thresholds all live in
`forty/config.py`; changing one and rerunning takes a minute.

---

## 1. The point-in-time rule

This is the load-bearing one.

A row of the panel dated 2021-06-30 contains the closing price of 2021-06-30 and
the most recent fundamentals **whose filing date had already passed on that
day**. In practice that is the quarter before last, because a 10-Q lands five to
seven weeks after the period it covers. The median gap between the price date and
the filing date is reported by every build.

The tempting alternative — pair the June 30 price with the June 30 quarter — is
wrong in a specific and expensive way. It credits the market with knowing a
revenue figure it would not see until August. Because growth is precisely the
quantity the market is trying to anticipate, the error loads onto the growth
coefficient and inflates it. A backtest built that way looks brilliant and is
unreproducible.

The same rule governs balance-sheet items: net debt at a date is taken from the
most recent balance sheet *filed* by that date, not the one dated closest to it.

Fundamentals are also **as first reported**. When a company later restates, the
original number stays in the historical cross-sections. Restated history is
strictly more accurate about what was true and strictly less accurate about what
was known, and this model is about what was known.

## 2. The universe

`SIC ∈ {7370, 7371, 7372, 7373, 7374}`, US-listed on a major exchange, and in the
quarter being measured:

- LTM revenue ≥ $50m
- LTM gross margin ≥ 60%
- at least eight quarters of filed history (needed for a YoY growth rate)

The gross-margin screen is the one doing real work. SIC codes put genuine
software next to IT-services firms that resell labour, and those businesses are
not comparable at any multiple. Sixty percent is the conventional line.

Screens are applied **per quarter**, not once at the end. A company that IPO'd in
2021 is absent from the 2019 cross-sections; one acquired in 2022 is present up
to its last filing and then gone; one that fell below the revenue floor drops out
and can come back. Applying today's screen to history is how survivorship bias
gets in, and it is a large effect in a sector where a third of the 2021 cohort
was taken private or delisted.

## 3. The metrics

**Revenue.** Tag priority: `RevenueFromContractWithCustomerExcludingAssessedTax`,
then `...IncludingAssessedTax`, then `Revenues`, then `SalesRevenueNet`. ASC 606
replaced the old tags in 2018 and filers migrated at different times, so a series
built from any single tag has a hole somewhere in 2018-2019 — and a growth rate
computed across that hole is fiction.

**Quarterly values from cumulative filings.** A Q3 10-Q reports nine months of
operating cash flow, not three. Quarterly figures are differenced: Q4 is the
fiscal year minus the nine months, Q3 the nine months minus the half, and so on.
The filing date attached to a differenced quarter is the later of the two inputs,
because that is when the arithmetic first became possible. `tests/test_model.py`
checks this against a constructed example.

**LTM.** Four consecutive quarters, and the window must span 240-300 days. A
rolling four-quarter sum over an index with a gap silently produces a nine-month
"year", which shows up as a 25% revenue collapse that never happened.

**Growth.** LTM revenue over LTM revenue four quarters earlier. Comparing the
same four-quarter window a year apart removes seasonality without modelling it.

**Free cash flow.** Operating cash flow minus capital expenditure, trailing twelve
months. This adds back stock-based compensation, which flatters software
companies specifically. It is how the Rule of 40 is conventionally computed, and
the object here is to test the rule as used — but see the limits in the README.

**Enterprise value.** Price times the share count disclosed on the most recent
filing cover page published by that date, plus net debt from the most recent
balance sheet published by that date. Vendor market-cap history applies *today's*
share count to *past* prices; for a software company diluting 5-8% a year that
error is material and runs one way.

**Fiscal-year alignment.** Salesforce closes in January, most of the sector in
December. Their "Q3" figures describe different three-month windows of the world,
so everything is placed on the calendar quarter its period actually ended in.

## 4. The regression

Refit independently in each quarter:

```
log(EV / LTM revenue) = a + b_g · growth + b_m · FCF margin + b_s · log(revenue) + e
```

**Why logs.** Multiples are bounded below by zero with a long right tail. In
levels a single 90x company bends the line. In logs the model estimates a
proportional relationship and a coefficient reads as "a point of growth is worth
b_g percent on the multiple", which is how the quantity is used.

**Why the size control.** Large companies trade at lower revenue multiples than
small ones at identical growth, and they also grow more slowly. Without
`log(revenue)` in the regression that size effect loads onto growth, and the model
reports the market paying for growth when part of what it sees is the market
paying for being small.

**Why robust standard errors.** Valuation errors are severely
heteroskedastic — half a turn on a mature company, fifteen on a hypergrowth one.
Classical standard errors assume constant variance and would overstate
significance. HC1 does not. The simulation in `tests/test_model.py` shows
classical intervals under-covering on data of this shape and HC1 holding near
nominal.

**Why winsorise the inputs but not the multiple.** Growth and margin are clipped
at the 2nd and 98th percentiles of each cross-section — clipped rather than
deleted, since dropping the fastest growers would remove exactly the observations
a model of growth pricing should be fitting. The dependent variable is left
alone: the log transform is already its outlier treatment, and clipping it as
well attenuates the coefficients being estimated. `tests/test_model.py` measures
that attenuation, so the choice is demonstrated rather than asserted.

**The test.** `t = (b_g − b_m) / sqrt(Var(b_g) + Var(b_m) − 2·Cov(b_g, b_m))`,
rejected at |t| > 1.96. The covariance term matters: growth and margin are
negatively correlated across software companies — that is the growth-versus-
profitability trade-off itself — so omitting it would misstate the standard error
of the difference.

**Minimum cross-section.** No quarter with fewer than 40 companies is fitted.

## 5. The per-company residual

`premium = exp(residual) − 1`: how far a company's multiple sits above or below
what its own growth, margin and size imply, relative to its peers *in that
quarter*. A residual is not a valuation. It is the part of the multiple the model
does not explain, which includes everything real that the model has no variable
for — net revenue retention, mix, competitive position, acquisition speculation —
alongside genuine mispricing.

Median premium across the cross-section is approximately zero by construction,
which is a useful check: a systematic offset would mean the model is mispricing
the whole sector and reporting it as stock-specific.

## 6. What would change the answer

Stated so a reader can attack the result on its merits:

- **A different FCF definition.** Subtracting stock-based compensation rather
  than adding it back would lower every margin and could plausibly raise the
  margin coefficient. This is the largest single judgement call in the project.
- **Forward rather than trailing growth.** The market prices expectations. LTM
  growth is a proxy for them, and a consensus-estimate feed would be better — it
  is not free, which is the entire reason it is not used here.
- **A wider universe.** Loosening the gross-margin screen pulls in IT services
  and would compress the growth coefficient.
- **Weighting by size.** Every observation counts equally here, so a $200m
  company moves the fit as much as a $2tn one. Value-weighting would produce a
  different and equally defensible number.
