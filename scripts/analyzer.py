"""
DSE Advanced Trading Dashboard - Yahoo Finance Backend
======================================================
"""

from __future__ import annotations

import json
import time
import datetime as dt
from pathlib import Path
from typing import Optional
import pandas as pd
import yfinance as yf

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

def looks_like_fund(ticker: str) -> bool:
    t = ticker.upper()
    return t[:1].isdigit() or "MF" in t

def load_category_map() -> dict[str, str]:
    """
    Loads categories. If cache doesn't exist, initializes with a fallback list 
    of prominent DSE A/B shares to keep the script fully autonomous.
    """
    if CATEGORY_CACHE.exists():
        try:
            return json.loads(CATEGORY_CACHE.read_text())
        except Exception:
            pass

    # High-signal fallback list of major DSE A & B category stocks
    fallback = {
        "GP": "A", "BATBC": "A", "SQURPHARMA": "A", "RENATA": "A", "BEXIMCO": "A",
        "BRACBANK": "A", "EBL": "A", "CITYBANK": "A", "JAMUNAOIL": "A", "MPETROLEUM": "A",
        "LINDEBD": "A", "BERGERPBL": "A", "LHBL": "A", "MARICO": "A", "UPGDCL": "A",
        "ISLAMIBANK": "A", "HEIDELBCEM": "A", "BSRMLTD": "A", "PADMAOIL": "A", "OLYMPIC": "A"
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
        return {"mood": "Neutral", "entry": "-", "sl": "-", "exit": "-", "note": "insufficient_history"}

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

    return {"mood": mood, "entry": entry, "sl": sl, "exit": exit_target, "rsi": rsi_val}

def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    categories = load_category_map()
    tickers = sorted(categories.keys())
    
    print(f"Tracking {len(tickers)} tickers via Yahoo Finance backend...")
    output = {}

    for ticker in tickers:
        try:
            # DSE tickers on Yahoo Finance use the .BD suffix
            yf_ticker = f"{ticker}.BD"
            stock = yf.Ticker(yf_ticker)
            
            # Fetch 6 months of history to cover all lookback windows safely
            hist = stock.history(period="6mo")
            if hist.empty:
                print(f"[warn] No data found for {yf_ticker}")
                continue
                
            hist.columns = [str(c).strip().lower() for c in hist.columns]
            
            # Get current metadata
            price = float(hist["close"].iloc[-1])
            prev_close = float(hist["close"].iloc[-2]) if len(hist) > 1 else price
            pct_change = round(((price - prev_close) / prev_close) * 100, 2)

            if price <= 0: continue

            analysis = {tf: compute_signal(price, hist, n) for tf, n in TIMEFRAMES.items()}

            output[ticker] = {
                "category": categories[ticker],
                "price": round(price, 2),
                "change": pct_change,
                "analysis": analysis,
            }
            print(f"[ok] Processed {ticker} (${price})")
            
        except Exception as exc:
            print(f"[warn] Failed to process {ticker}: {exc}")

    # Write output to the main data.json file
    DATA_JSON.write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.utcnow().isoformat() + "Z",
                "disclaimer": "Automated technical analysis only. Powered by Yahoo Finance.",
                "stocks": output,
            },
            indent=2,
            default=str,
        )
    )
    print(f"Successfully compiled metrics for {len(output)} stocks to {DATA_JSON}")

if __name__ == "__main__":
    main()
