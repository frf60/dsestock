"""
DSE Advanced Trading Dashboard - High-Speed Cloud Mirror Backend
================================================================
"""

from __future__ import annotations

import json
import time
import datetime as dt
from pathlib import Path
from typing import Optional
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_JSON = ROOT / "data.json"
CATEGORY_CACHE = DATA_DIR / "categories.json"

TIMEFRAMES = {
    "3_days": 3,
    "1_week": 5,
    "15_days": 15,
    "1_month": 22,
}

def load_category_map() -> dict[str, str]:
    """Loads categories. If cache doesn't exist, initializes with standard list."""
    if CATEGORY_CACHE.exists():
        try:
            return json.loads(CATEGORY_CACHE.read_text())
        except Exception:
            pass

    fallback = {
        "GP": "A", "BATBC": "A", "SQURPHARMA": "A", "RENATA": "A", "BEXIMCO": "A",
        "BRACBANK": "A", "EBL": "A", "CITYBANK": "A", "JAMUNAOIL": "A", "MPETROLEUM": "A",
        "LINDEBD": "A", "BERGERPBL": "A", "LHBL": "A", "MARICO": "A", "UPGDCL": "A",
        "ISLAMIBANK": "A", "HEIDELBCEM": "A", "BSRMLTD": "A", "PADMAOIL": "A", "OLYMPIC": "A",
        "BSRMSTEEL": "A", "BXPHARMA": "A", "TITASGAS": "A", "KPCL": "B", "GPHISPAT": "A",
        "MJSBL": "A", "IDLC": "A", "LANKABAFIN": "B", "UCB": "A", "ONEBANKLTD": "A",
        "PRIMEBANK": "A", "AL-ARAFABH": "A", "EXIMBANK": "A", "NBL": "B"
    }
    
    DATA_DIR.mkdir(exist_ok=True, parents=True)
    CATEGORY_CACHE.write_text(json.dumps(fallback, indent=2))
    return fallback

def rsi(series: pd.Series, period: int) -> Optional[float]:
    if len(series) < period + 1:
        return None
    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)

def atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    if len(df) < period + 1 or not {"high", "low", "close"}.issubset(df.columns):
        return None
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return round(val, 2) if pd.notna(val) else None

def compute_signal(current_price: float, hist: pd.DataFrame, lookback: int) -> dict:
    if len(hist) < lookback + 1 or "close" not in hist.columns:
        return {"mood": "Neutral", "entry": "-", "sl": "-", "exit": "-"}

    closes = hist["close"]
    sma = closes.iloc[-lookback:].mean()
    price_n_ago = closes.iloc[-lookback]
    momentum_pct = ((current_price - price_n_ago) / price_n_ago * 100) if price_n_ago else 0

    rsi_period = min(max(lookback, 3), 14)
    rsi_val = rsi(closes, rsi_period)
    momentum_threshold = round(1 + 0.3 * lookback, 1)

    score = 0
    score += 1 if current_price > sma * 1.002 else (-1 if current_price < sma * 0.998 else 0)
    score += 1 if momentum_pct > momentum_threshold else (-1 if momentum_pct < -momentum_threshold else 0)
    if rsi_val is not None:
        score += 1 if rsi_val > 60 else (-1 if rsi_val < 40 else 0)

    if score >= 2: mood = "Strong Buy"
    elif score == 1: mood = "Buy"
    elif score == -1: mood = "Sell"
    elif score <= -2: mood = "Strong Sell"
    else: mood = "Neutral"

    if mood == "Neutral":
        return {"mood": mood, "entry": "-", "sl": "-", "exit": "-"}

    entry = round(float(current_price), 2)
    atr_val = atr(hist) or round(closes.pct_change().std() * current_price, 2) or round(current_price * 0.02, 2)

    if score > 0:
        sl = round(entry - atr_val * 1.5, 2)
        if sl <= 0: sl = round(entry * 0.95, 2)
        exit_target = round(entry + (entry - sl) * 2, 2)
    else:
        sl = round(entry + atr_val * 1.5, 2)
        exit_target = round(entry - (sl - entry) * 2, 2)
        if exit_target <= 0: exit_target = round(entry * 0.9, 2)

    return {"mood": mood, "entry": entry, "sl": sl, "exit": exit_target}

def fetch_live_feed() -> dict[str, dict]:
    """Fetches the latest real-time tracking metrics from the cloud node."""
    url = "https://cloud.amarstock.com/api/feed/latest-price"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            return {}
        data = response.json()
        feed = {}
        for item in data:
            ticker = item.get("Scrip") or item.get("Symbol")
            if not ticker:
                continue
            ticker = str(ticker).strip().upper()
            
            feed[ticker] = {
                "price": float(item.get("LTP", 0)),
                "change": float(item.get("ChangeP", 0) or item.get("YcpChanageP", 0))
            }
        return feed
    except Exception as e:
        print(f"[error] Failed to parse live cloud metrics: {e}")
        return {}

def fetch_historical_candles(ticker: str, count: int = 50) -> Optional[pd.DataFrame]:
    """Fetches historical price candles for technical calculation."""
    url = f"https://cloud.amarstock.com/api/feed/ClosePriceHistoryByTicker?ticker={ticker}&Count={count}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            return None
            
        df = pd.DataFrame(data)
        rename_map = {
            'ClosePrice': 'close', 'HighPrice': 'high', 'LowPrice': 'low', 'OpenPrice': 'open',
            'closePrice': 'close', 'highPrice': 'high', 'lowPrice': 'low', 'openPrice': 'open'
        }
        df = df.rename(columns=rename_map)
        
        for col in ['close', 'high', 'low']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        # Reversing data arrays to align oldest-to-newest for rolling calculations
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    except Exception:
        return None

def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    categories = load_category_map()
    tickers = sorted(categories.keys())
    
    print(f"Tracking {len(tickers)} tickers via Cloud Mirror Node...")
    
    live_data = fetch_live_feed()
    if not live_data:
        print("[critical] Live feed download failed. Aborting execution loop.")
        return

    output = {}

    for ticker in tickers:
        if ticker not in live_data:
            print(f"[warn] Ticker {ticker} missing from live feed registry.")
            continue
            
        try:
            metrics = live_data[ticker]
            price = metrics["price"]
            pct_change = metrics["change"]

            if price <= 0:
                continue

            hist = fetch_historical_candles(ticker, count=45)
            if hist is None or hist.empty:
                print(f"[warn] No historical matrix generated for {ticker}")
                continue

            analysis = {tf: compute_signal(price, hist, n) for tf, n in TIMEFRAMES.items()}

            output[ticker] = {
                "category": categories[ticker],
                "price": round(price, 2),
                "change": pct_change,
                "analysis": analysis,
            }
            print(f"[ok] Compiled data for {ticker} (${price})")
            time.sleep(0.2)  # Polite pause between nodes
            
        except Exception as exc:
            print(f"[warn] Execution fault on processing token {ticker}: {exc}")

    # Write calculated data back directly into data.json
    DATA_JSON.write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.utcnow().isoformat() + "Z",
                "disclaimer": "Automated technical calculations. Data powered by open mirror cloud node.",
                "stocks": output,
            },
            indent=2,
            default=str,
        )
    )
    print(f"Successfully compiled metrics for {len(output)} stocks to {DATA_JSON}")

if __name__ == "__main__":
    main()
