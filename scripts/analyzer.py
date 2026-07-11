"""
DSE Advanced Trading Dashboard - Analyzer
==========================================

Fetches live prices and historical OHLCV data for DSE 'A' and 'B'
category stocks, computes rule-based technical signals (trend +
momentum + RSI, ATR-based stop-loss, 1:2 risk-reward target) across
four lookback windows, and writes data.json for the frontend.

IMPORTANT: The "mood" and price targets produced here come from a
simple, transparent rule-based formula applied to real historical
prices -- they are automated technical analysis, NOT a prediction and
NOT financial advice. See README.md for the exact formula and its
limitations, and for a note on DSE's terms of use.
"""

from __future__ import annotations

import json
import time
import datetime as dt
from pathlib import Path
from typing import Optional

import requests
import pandas as pd
from bdshare import get_current_trade_data, get_basic_historical_data, BDShareError

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HIST_DIR = DATA_DIR / "history"
DATA_JSON = ROOT / "data.json"
CATEGORY_CACHE = DATA_DIR / "categories.json"
REFRESH_MARKER = DATA_DIR / "last_full_refresh.txt"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dse-dashboard-bot/1.0)"}
CATEGORY_URL = "https://www.dsebd.org/latest_share_price_scroll_group.php?group={group}"

# Lookback windows expressed in trading days
TIMEFRAMES = {
    "3_days": 3,
    "1_week": 5,
    "15_days": 15,
    "1_month": 22,
}

CATEGORY_MAX_AGE_HOURS = 24        # category (A/B) list rarely changes
FULL_HISTORY_MAX_AGE_HOURS = 20    # refresh cached OHLCV history ~once/day
HIST_LOOKBACK_DAYS = 150           # calendar days of history to keep cached

# Rough heuristic to exclude mutual funds that sometimes carry an A/B
# rating (DSE fund codes typically start with a digit or contain "MF").
def looks_like_fund(ticker: str) -> bool:
    t = ticker.upper()
    return t[:1].isdigit() or "MF" in t


def fetch_category_tickers(group: str) -> list[str]:
    """Scrape one DSE category page (A or B) for its list of trading codes."""
    url = CATEGORY_URL.format(group=group)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    tables = pd.read_html(resp.text)
    for table in tables:
        code_col = next(
            (c for c in table.columns if "TRADING" in str(c).upper()), None
        )
        if code_col is not None:
            return (
                table[code_col]
                .astype(str)
                .str.strip()
                .replace("", pd.NA)
                .dropna()
                .tolist()
            )
    return []


def load_category_map() -> dict[str, str]:
    """{ticker: 'A'|'B'}, cached to disk since categories change rarely."""
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
        except Exception as exc:  # noqa: BLE001 - keep scraping resilient
            print(f"[warn] could not fetch category {group}: {exc}")

    if mapping:
        DATA_DIR.mkdir(exist_ok=True)
        CATEGORY_CACHE.write_text(json.dumps(mapping, indent=2))
    elif CATEGORY_CACHE.exists():
        mapping = json.loads(CATEGORY_CACHE.read_text())  # stale fallback
    return mapping


def full_history_is_stale() -> bool:
    if not REFRESH_MARKER.exists():
        return True
    age_h = (time.time() - REFRESH_MARKER.stat().st_mtime) / 3600
    return age_h >= FULL_HISTORY_MAX_AGE_HOURS


def refresh_history(tickers: list[str]) -> None:
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    end = dt.date.today()
    start = end - dt.timedelta(days=HIST_LOOKBACK_DAYS)
    ok, failed = 0, 0
    for i, ticker in enumerate(tickers, 1):
        try:
            df = get_basic_historical_data(str(start), str(end), ticker)
            if df is not None and not df.empty:
                df.to_csv(HIST_DIR / f"{ticker}.csv")
                ok += 1
        except BDShareError as exc:
            failed += 1
            print(f"[warn] history fetch failed for {ticker}: {exc}")
        if i % 50 == 0:
            print(f"  ...{i}/{len(tickers)} processed ({ok} ok, {failed} failed)")
    REFRESH_MARKER.write_text(dt.datetime.utcnow().isoformat())
    print(f"History refresh done: {ok} ok, {failed} failed")


def load_history(ticker: str) -> Optional[pd.DataFrame]:
    path = HIST_DIR / f"{ticker}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df.sort_index()


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


def atr(df: Optional[pd.DataFrame], period: int = 14) -> Optional[float]:
    if df is None or len(df) < period + 1 or not {"high", "low", "close"}.issubset(df.columns):
        return None
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return round(val, 2) if pd.notna(val) else None


def compute_signal(current_price: float, hist: Optional[pd.DataFrame], lookback: int) -> dict:
    """Rule-based signal: trend (price vs SMA) + momentum + RSI score.
    Score ranges -3..+3 -> mapped to mood. See README for details."""
    if hist is None or len(hist) < lookback + 1 or "close" not in hist.columns:
        return {"mood": "Neutral", "entry": "-", "sl": "-", "exit": "-", "note": "insufficient_history"}

    closes = pd.concat([hist["close"], pd.Series([current_price])], ignore_index=True)

    sma = closes.iloc[-(lookback + 1):-1].mean()
    price_n_ago = closes.iloc[-(lookback + 1)]
    momentum_pct = ((current_price - price_n_ago) / price_n_ago * 100) if price_n_ago else 0

    rsi_period = min(max(lookback, 3), 14)
    rsi_val = rsi(closes, rsi_period)
    momentum_threshold = round(1 + 0.3 * lookback, 1)

    score = 0
    score += 1 if current_price > sma * 1.002 else (-1 if current_price < sma * 0.998 else 0)
    score += 1 if momentum_pct > momentum_threshold else (-1 if momentum_pct < -momentum_threshold else 0)
    if rsi_val is not None:
        score += 1 if rsi_val > 60 else (-1 if rsi_val < 40 else 0)

    if score >= 2:
        mood = "Strong Buy"
    elif score == 1:
        mood = "Buy"
    elif score == -1:
        mood = "Sell"
    elif score <= -2:
        mood = "Strong Sell"
    else:
        mood = "Neutral"

    if mood == "Neutral":
        return {"mood": mood, "entry": "-", "sl": "-", "exit": "-"}

    entry = round(float(current_price), 2)
    atr_val = atr(hist) or round(closes.pct_change().std() * current_price, 2) or round(current_price * 0.02, 2)

    if score > 0:
        sl = round(entry - atr_val * 1.5, 2)
        if sl <= 0:
            sl = round(entry * 0.95, 2)
        exit_target = round(entry + (entry - sl) * 2, 2)
    else:
        sl = round(entry + atr_val * 1.5, 2)
        exit_target = round(entry - (sl - entry) * 2, 2)
        if exit_target <= 0:
            exit_target = round(entry * 0.9, 2)

    return {"mood": mood, "entry": entry, "sl": sl, "exit": exit_target, "rsi": rsi_val}


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    categories = load_category_map()
    if not categories:
        print("[error] no A/B category tickers found - aborting")
        return

    tickers = sorted(categories.keys())
    print(f"Tracking {len(tickers)} A/B category tickers")

    if full_history_is_stale():
        print("Refreshing full OHLCV history (runs about once a day)...")
        refresh_history(tickers)

    try:
        live_df = get_current_trade_data()
    except BDShareError as exc:
        print(f"[error] could not fetch live prices: {exc}")
        return

    live_df["symbol"] = live_df["symbol"].astype(str).str.strip().str.upper()
    live_df = live_df.set_index("symbol")

    output = {}
    for ticker in tickers:
        if ticker not in live_df.index:
            continue
        row = live_df.loc[ticker]
        price = float(row.get("ltp") or row.get("close") or 0)
        if price <= 0:
            continue

        hist = load_history(ticker)
        analysis = {tf: compute_signal(price, hist, n) for tf, n in TIMEFRAMES.items()}

        output[ticker] = {
            "category": categories[ticker],
            "price": price,
            "change": float(row.get("change", 0) or 0),
            "analysis": analysis,
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
