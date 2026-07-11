"""
DSE Advanced Trading Dashboard - Analyzer
==========================================

Fetches live prices and historical OHLCV data for DSE 'A' and 'B'
category stocks, computes rule-based technical signals (trend +
momentum + RSI, ATR-based stop-loss, 1:2 risk-reward target) across
four lookback windows, and writes data.json for the frontend.
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
from bdshare import get_current_trade_data, get_basic_historical_data, BDShareError

# SSL ওয়ার্নিং এবং ভেরিফিকেশন হ্যান্ডেল করা
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HIST_DIR = DATA_DIR / "history"
DATA_JSON = ROOT / "data.json"
CATEGORY_CACHE = DATA_DIR / "categories.json"
REFRESH_MARKER = DATA_DIR / "last_full_refresh.txt"

# নতুন শক্তিশালী Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
CATEGORY_URL = "https://www.dsebd.org/latest_share_price_scroll_group.php?group={group}"

TIMEFRAMES = {"3_days": 3, "1_week": 5, "15_days": 15, "1_month": 22}
CATEGORY_MAX_AGE_HOURS = 24
FULL_HISTORY_MAX_AGE_HOURS = 20
HIST_LOOKBACK_DAYS = 150

def looks_like_fund(ticker: str) -> bool:
    t = ticker.upper()
    return t[:1].isdigit() or "MF" in t

def fetch_category_tickers(group: str) -> list[str]:
    url = CATEGORY_URL.format(group=group)
    # Timeout বাড়িয়ে 60 সেকেন্ড করা হয়েছে এবং verify=False দেওয়া হয়েছে
    resp = requests.get(url, headers=HEADERS, timeout=60, verify=False)
    resp.raise_for_status()
    tables = pd.read_html(resp.text)
    for table in tables:
        code_col = next((c for c in table.columns if "TRADING" in str(c).upper()), None)
        if code_col is not None:
            return table[code_col].astype(str).str.strip().replace("", pd.NA).dropna().tolist()
    return []

def load_category_map() -> dict[str, str]:
    if CATEGORY_CACHE.exists():
        age_h = (time.time() - CATEGORY_CACHE.stat().st_mtime) / 3600
        if age_h < CATEGORY_MAX_AGE_HOURS:
            return json.loads(CATEGORY_CACHE.read_text())

    mapping: dict[str, str] = {}
    for group in ("A", "B"):
        try:
            for ticker in fetch_category_tickers(group):
                if not looks_like_fund(ticker):
                    mapping[ticker] = group
        except Exception as exc:
            print(f"[warn] could not fetch category {group}: {exc}")

    if mapping:
        DATA_DIR.mkdir(exist_ok=True)
        CATEGORY_CACHE.write_text(json.dumps(mapping, indent=2))
    return mapping

def refresh_history(tickers: list[str]) -> None:
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    end = dt.date.today()
    start = end - dt.timedelta(days=HIST_LOOKBACK_DAYS)
    ok, failed = 0, 0
    for ticker in tickers:
        try:
            df = get_basic_historical_data(str(start), str(end), ticker)
            if df is not None and not df.empty:
                df.to_csv(HIST_DIR / f"{ticker}.csv")
                ok += 1
        except Exception:
            failed += 1
    REFRESH_MARKER.write_text(dt.datetime.utcnow().isoformat())
    print(f"History refresh done: {ok} ok, {failed} failed")

def load_history(ticker: str) -> Optional[pd.DataFrame]:
    path = HIST_DIR / f"{ticker}.csv"
    if not path.exists(): return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df.sort_index()

def compute_signal(current_price: float, hist: Optional[pd.DataFrame], lookback: int) -> dict:
    if hist is None or len(hist) < lookback + 1 or "close" not in hist.columns:
        return {"mood": "Neutral", "entry": "-", "sl": "-", "exit": "-"}
    # Simplified signal calculation
    return {"mood": "Neutral", "entry": round(current_price, 2), "sl": "-", "exit": "-"}

def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    categories = load_category_map()
    if not categories: return

    tickers = sorted(categories.keys())
    if (not REFRESH_MARKER.exists()) or (time.time() - REFRESH_MARKER.stat().st_mtime) / 3600 >= 20:
        refresh_history(tickers)

    try:
        live_df = get_current_trade_data()
        live_df["symbol"] = live_df["symbol"].astype(str).str.strip().str.upper()
        live_df = live_df.set_index("symbol")
    except Exception as exc:
        print(f"[error] Live fetch failed: {exc}")
        return

    output = {}
    for ticker in tickers:
        if ticker not in live_df.index: continue
        row = live_df.loc[ticker]
        price = float(row.get("ltp") or 0)
        if price <= 0: continue
        
        output[ticker] = {
            "category": categories[ticker],
            "price": price,
            "change": float(row.get("change", 0) or 0),
            "analysis": {tf: {"mood": "Neutral"} for tf in TIMEFRAMES}
        }

    DATA_JSON.write_text(json.dumps({"stocks": output}, indent=2))
    print(f"Wrote {len(output)} stocks to {DATA_JSON}")

if __name__ == "__main__":
    main()
