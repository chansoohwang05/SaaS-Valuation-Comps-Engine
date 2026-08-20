"""Configuration — every number a reader might want to argue with lives here.

Nothing in this file is arbitrary, and each choice is defended in METHOD.md.
Anyone who disagrees with a threshold can change it in one place and rerun.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
SITE = ROOT / "site"
COMPANIES = SITE / "companies"

for _p in (DATA, CACHE, SITE, COMPANIES):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# SEC
# ---------------------------------------------------------------------------
# The SEC requires a declared identity on every request and throttles at 10
# requests per second. Both are honoured in edgar.py. Set your own address:
#   export SEC_USER_AGENT="Your Name your@email.com"
# The default below is deliberately obvious so an unset variable is caught in
# review rather than in a 403.
USER_AGENT = os.environ.get("SEC_USER_AGENT", "Forty Research UNSET@example.com")
SEC_RATE_LIMIT = 8.0          # requests/second, under the published 10
SEC_MAX_RETRIES = 4

# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
# SEC Standard Industrial Classification codes. 7372 is the core — it is what
# a prepackaged-software company files under, and it captures essentially every
# name a software investor would name unprompted. The others bring in the
# services and data-processing neighbours, which the gross-margin screen below
# then filters: an IT-services firm reselling labour does not clear 60% gross
# margin, and a software company almost always does.
SIC_CODES = {
    7372: "Prepackaged software",
    7370: "Computer programming, data processing",
    7371: "Computer programming services",
    7373: "Computer integrated systems design",
    7374: "Data processing and preparation",
}

# Screens. A company enters the panel for a given quarter only if it clears all
# of these *as of that quarter* — the universe is therefore time-varying, which
# is the point. Survivorship bias comes from applying today's screen to
# history; this applies each quarter's screen to that quarter.
MIN_LTM_REVENUE = 50e6        # $50m — below this, multiples are noise
MIN_GROSS_MARGIN = 0.60       # software economics, not services economics
MIN_QUARTERS_HISTORY = 8      # need two years to compute a YoY growth rate
MIN_PANEL_N = 40              # do not fit a cross-section thinner than this

# Outlier handling. Multiples have a fat right tail — one company at 90x
# revenue can bend a regression line on its own. Winsorising at the 2nd and
# 98th percentiles of each cross-section keeps those observations in the sample
# at a bounded value rather than deleting them, which would be a silent
# survivorship filter of its own.
WINSOR = 0.02

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
HISTORY_START = "2014-01-01"
BENCHMARK = "^SPX"            # context only; the model is cross-sectional

# ---------------------------------------------------------------------------
# XBRL tag priority
# ---------------------------------------------------------------------------
# US-GAAP has no single revenue tag. ASC 606 (2018) introduced the
# RevenueFromContractWithCustomer family and filers migrated at different
# times, so a series stitched from one tag alone has a hole in 2018-2019.
# Order matters: the first tag with data for a period wins.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueServicesNet",
]
GROSS_PROFIT_TAGS = ["GrossProfit"]
COST_OF_REVENUE_TAGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold"]
OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]
CASH_TAGS = [
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "CashAndCashEquivalentsAtCarryingValue",
]
SHORT_INVESTMENT_TAGS = ["ShortTermInvestments", "MarketableSecuritiesCurrent"]
DEBT_TAGS = [
    "LongTermDebtNoncurrent",
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
]
DEBT_CURRENT_TAGS = ["LongTermDebtCurrent", "DebtCurrent"]
SHARES_TAGS = [
    "dei:EntityCommonStockSharesOutstanding",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "CommonStockSharesOutstanding",
]
