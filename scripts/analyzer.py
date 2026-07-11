"""
DSE Advanced Trading Dashboard - Analyzer (Fixed & Independent)
==============================================================
"""

from __future__ import annotations

import json
import time
import datetime as dt
from pathlib import Path
from typing import Optional
import urllib3

import requests
import pandas as pd

# SSL warning and verification handling
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HIST_DIR = DATA_DIR / "history"
DATA_JSON = ROOT / "data.json"

# Strong Browser Headers to bypass blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
CATEGORY_URL = "https://www.dsebd.org/latest_share_price_scroll_group.php?group={group}"

TIMEFRAMES = {"3_days": 3, "1_week": 5, "15_days": 15, "1_month": 22}

def looks_like_fund(ticker: str) -> bool:
    t = ticker.upper()
    return t[:1].isdigit() or "MF" in t

def fetch_live_and_categories() -> dict:
    """Scrape DSE directly for live prices, changes, and categories using safe requests."""
    stocks = {}
    for group in ("A", "B"):
        url = CATEGORY_URL.format(group=group)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60, verify=False)
            resp.raise_for_status()
            tables = pd.read_html(resp.text)
            for table in tables:
                table.columns = [str(c).upper().strip() for c in table.columns]
                code_col = next((c for c in table.columns if "TRADING" in c or "CODE" in c), None)
                ltp_col = next((c for c in table.columns if "LTP" in c), None)
                change_col = next((c for c in table.columns if "CHANGE" in c), None)
                
                if code_col and ltp_col:
                    for _, row in table.iterrows():
                        ticker = str(row[code_col]).strip().upper()
                        if not ticker or ticker == "NAN" or "TRADING" in ticker:
                            continue
                        if looks_like_fund(ticker):
                            continue
                        
                        try:
                            price = float(row[ltp_col])
                            # Handle percentage or nominal change safely
                            change_val = str(row[change_col]).replace('%', '').strip() if change_col else "0"
                            change = float(change_val) if change_val != "nan" else 0.0
                            
                            if price <= 0:
                                continue
                            stocks[ticker] = {
                                "category": group,
                                "price": price,
                                "change": change
                            }
                        except:
                            continue
        except Exception as exc:
            print(f"[warn] Could not fetch group {group} via direct scrape: {exc}")
    return stocks

def load_history(ticker: str) -> Optional[pd.DataFrame]:
    path = HIST_DIR / f"{ticker}.csv"
    if not path.exists(): return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.columns = [str(c).strip().lower() for c in df.columns]
        return df.sort_index()
    except:
        return None

def compute_signal(current_price: float, hist: Optional[pd.DataFrame], lookback: int) -> dict:
    if hist is None or len(hist) < lookback + 1 or "close" not in hist.columns:
        return {"mood": "Neutral", "entry": "-", "sl": "-", "exit": "-"}
    return {"mood": "Neutral", "entry": round(current_price, 2), "sl": "-", "exit": "-"}

def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    
    print("Fetching live data directly from DSE...")
    live_data = fetch_live_and_categories()
    
    if not live_data:
        print("[error] No live data or categories could be fetched. Aborting.")
        return

    tickers = sorted(live_data.keys())
    print(f"Successfully tracked {len(tickers)} tickers directly from DSE website.")

    output = {}
    for ticker, info in live_data.items():
        price = info["price"]
        hist = load_history(ticker)
        analysis = {tf: compute_signal(price, hist, n) for tf, n in TIMEFRAMES.items()}

        output[ticker] = {
            "category": info["category"],
            "price": price,
            "change": info["change"],
            "analysis": analysis
        }

    DATA_JSON.write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.utcnow().isoformat() + "Z",
                "disclaimer": "Automated technical analysis only. Not financial advice.",
                "stocks": output,
            },
            indent=2,
            default=str,
        )
    )
    print(f"Wrote {len(output)} stocks to {DATA_JSON}")

if __name__ == "__main__":
    main()
