import yfinance as yf
import pandas as pd
import numpy as np
import os

# 1. Define Target Tech / Enterprise SaaS Peers
tickers = ["MSFT", "CRM", "NOW", "SNOW", "DDOG", "CRWD", "PLTR", "NET"]

comps_data = []

print("Extracting live market data & financial statements...")

for ticker in tickers:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # Financial metrics extraction
        company_name = info.get("shortName", ticker)
        price = info.get("currentPrice", np.nan)
        market_cap = info.get("marketCap", np.nan)
        enterprise_value = info.get("enterpriseValue", np.nan)
        revenue = info.get("totalRevenue", np.nan)
        ebitda = info.get("ebitda", np.nan)
        rev_growth = info.get("revenueGrowth", np.nan)
        fcf = info.get("freeCashflow", np.nan)
        
        # Core SaaS & Valuation Multiples
        ev_to_rev = (enterprise_value / revenue) if pd.notna(enterprise_value) and pd.notna(revenue) else np.nan
        ev_to_ebitda = (enterprise_value / ebitda) if pd.notna(enterprise_value) and pd.notna(ebitda) else np.nan
        fcf_margin = (fcf / revenue) if pd.notna(fcf) and pd.notna(revenue) else np.nan
        rule_of_40 = ((rev_growth if pd.notna(rev_growth) else 0) + (fcf_margin if pd.notna(fcf_margin) else 0)) * 100
        
        comps_data.append({
            "Ticker": ticker,
            "Company Name": company_name,
            "Stock Price ($)": round(price, 2) if pd.notna(price) else "N/A",
            "Market Cap ($B)": round(market_cap / 1e9, 2) if pd.notna(market_cap) else "N/A",
            "Enterprise Value ($B)": round(enterprise_value / 1e9, 2) if pd.notna(enterprise_value) else "N/A",
            "LTM Revenue ($B)": round(revenue / 1e9, 2) if pd.notna(revenue) else "N/A",
            "LTM EBITDA ($B)": round(ebitda / 1e9, 2) if pd.notna(ebitda) else "N/A",
            "YoY Rev Growth (%)": round(rev_growth * 100, 1) if pd.notna(rev_growth) else "N/A",
            "FCF Margin (%)": round(fcf_margin * 100, 1) if pd.notna(fcf_margin) else "N/A",
            "Rule of 40 (%)": round(rule_of_40, 1),
            "EV / LTM Revenue": round(ev_to_rev, 2) if pd.notna(ev_to_rev) else "N/A",
            "EV / LTM EBITDA": round(ev_to_ebitda, 2) if pd.notna(ev_to_ebitda) else "N/A"
        })
        print(f"✅ Successfully pulled data for {ticker}")
    except Exception as e:
        print(f"❌ Error pulling data for {ticker}: {e}")

# Create DataFrame
df = pd.DataFrame(comps_data)

# 2. Force Save to Desktop using Python OS module
desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
csv_path = os.path.join(desktop_path, "tech_valuation_comps.csv")
excel_path = os.path.join(desktop_path, "tech_valuation_comps.xlsx")

df.to_csv(csv_path, index=False)
df.to_excel(excel_path, index=False)

print("\n--- TECH M&A PUBLIC TRADING COMPS ---")
print(df.to_string(index=False))
print(f"\n🎉 SUCCESS! Files successfully forced to your Desktop at:\n -> {csv_path}")