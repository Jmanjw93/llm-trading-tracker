"""
Daily market data collector.

Pulls recent daily bars for a configured ticker universe (Alpaca if ALPACA_API_KEY
/ ALPACA_SECRET_KEY are set, otherwise a deterministic synthetic fallback so the
whole pipeline stays testable before you've wired up real keys), computes the
anomaly features rules_engine.py looks for, and appends one row per ticker per
day to data/market/history.csv plus a dated snapshot under data/market/.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np
import pandas as pd

HISTORY_PATH = "./data/market/history.csv"


def _fetch_alpaca(tickers: List[str], lookback_days: int) -> pd.DataFrame:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]
    client = StockHistoricalDataClient(api_key, secret_key)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(lookback_days * 1.6) + 5)
    req = StockBarsRequest(symbol_or_symbols=tickers, timeframe=TimeFrame.Day, start=start, end=end)
    bars = client.get_stock_bars(req).df.reset_index()
    bars = bars.rename(columns={"symbol": "ticker", "timestamp": "date"})
    bars["date"] = pd.to_datetime(bars["date"]).dt.tz_localize(None).dt.normalize()
    return bars[["date", "ticker", "open", "high", "low", "close", "volume"]]


def _fetch_synthetic(tickers: List[str], lookback_days: int, seed: int = 11) -> pd.DataFrame:
    """Used when no Alpaca keys are set yet, so collection can start today and
    swap to real data later without changing anything downstream."""
    rng = np.random.default_rng(seed + hash(datetime.now().date().isoformat()) % 1000)
    rows = []
    dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=lookback_days)
    for t in tickers:
        price = 100.0 + rng.normal(0, 10)
        vol_base = rng.uniform(5e5, 5e6)
        for d in dates:
            spike = 3.0 if rng.random() < 0.05 else 1.0  # occasional volume spike to exercise rules
            price = max(1.0, price * (1 + rng.normal(0, 0.015)))
            rows.append({
                "date": d, "ticker": t,
                "open": price * (1 + rng.normal(0, 0.003)),
                "high": price * 1.012, "low": price * 0.988, "close": price,
                "volume": vol_base * spike * rng.uniform(0.8, 1.2),
            })
    return pd.DataFrame(rows)


def fetch_bars(tickers: List[str], lookback_days: int = 35) -> pd.DataFrame:
    if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"):
        return _fetch_alpaca(tickers, lookback_days)
    return _fetch_synthetic(tickers, lookback_days)


def compute_anomaly_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker rolling features used by rules_engine.py: volume z-score vs a
    20-day average, overnight gap %, RSI(14), and simple boolean anomaly flags."""
    parts = []
    for t, g in df.groupby("ticker", sort=False):
        g = g.sort_values("date").copy()
        g["prev_close"] = g["close"].shift(1)
        g["gap_pct"] = (g["open"] - g["prev_close"]) / g["prev_close"]

        vol_mean = g["volume"].rolling(20, min_periods=5).mean()
        vol_std = g["volume"].rolling(20, min_periods=5).std().replace(0, np.nan)
        g["volume_zscore"] = (g["volume"] - vol_mean) / vol_std

        delta = g["close"].diff()
        up = delta.clip(lower=0).rolling(14, min_periods=5).mean()
        down = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
        rs = up / (down + 1e-9)
        g["rsi_14"] = 100 - 100 / (1 + rs)

        g["flag_volume_spike"] = g["volume_zscore"] > 2.5
        g["flag_price_gap"] = g["gap_pct"].abs() > 0.03
        g["flag_rsi_extreme"] = (g["rsi_14"] < 25) | (g["rsi_14"] > 75)
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def append_to_history(df: pd.DataFrame) -> pd.DataFrame:
    """
    Merges `df` (must have at least date, ticker, close) into the shared
    data/market/history.csv, de-duplicated on (date, ticker) so re-running the
    same day or overlapping lookback windows is safe. Shared by the daily
    collector and the paper trading runner, so trade_ledger.py can resolve a
    prediction made by *either* path against one persistent price history
    instead of each keeping its own.
    """
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    keys = list(zip(df["date"], df["ticker"]))
    if os.path.exists(HISTORY_PATH):
        history = pd.read_csv(HISTORY_PATH, parse_dates=["date"])
        history = history[~history.apply(lambda r: (r["date"], r["ticker"]) in keys, axis=1)]
        combined = pd.concat([history, df], ignore_index=True)
    else:
        combined = df
    combined = combined.sort_values(["ticker", "date"])
    combined.to_csv(HISTORY_PATH, index=False)
    return combined


def collect_today(tickers: List[str]) -> pd.DataFrame:
    """Fetches bars, computes features, appends today's rows to history.csv,
    and returns just today's feature rows for the rule engine to consume."""
    raw = fetch_bars(tickers)
    featured = compute_anomaly_features(raw)
    today = featured["date"].max()
    today_rows = featured[featured["date"] == today].copy()

    append_to_history(featured[featured["ticker"].isin(tickers)])

    snapshot_path = f"./data/market/{today.date()}.csv"
    today_rows.to_csv(snapshot_path, index=False)
    return today_rows
