import numpy as np
import pandas as pd

def position_size(signal: int, confidence: float, vol_20d: float, vol_target: float = 0.15) -> float:
    # inverse-vol scaling (annualized vol_20d), capped in [-1,1]
    ivol = 1.0 / max(1e-6, vol_20d)
    raw = signal * confidence * ivol * (vol_target)
    return float(np.clip(raw, -1.0, 1.0))

def apply_positions(day_df: pd.DataFrame,
                     preds: pd.DataFrame,
                     vol_target: float = 0.15,
                     max_position_weight: float = 0.25,
                     risk_on: bool = True) -> pd.DataFrame:
    """
    Merge predictions into day_df and compute target weights.

    risk_on=False forces the book flat (all weights zero) for this day, used by the
    drawdown kill switch in run_backtest so a breach actually stops new risk instead
    of only being recorded in a stats dict.
    """
    df = day_df.merge(preds[["ticker", "direction", "confidence"]], on="ticker", how="left")
    df["direction"] = df["direction"].fillna("neutral")
    df["confidence"] = df["confidence"].fillna(0.0)

    from ..agents.trading_agent import TradingAgent
    df["signal"] = df["direction"].apply(TradingAgent.direction_to_signal)
    if "vol_20d" not in df.columns:
        df["vol_20d"] = 0.2  # fallback

    if not risk_on:
        df["weight"] = 0.0
        return df

    df["weight"] = df.apply(
        lambda r: position_size(int(r["signal"]), float(r["confidence"]), float(r["vol_20d"]), vol_target),
        axis=1,
    )

    # Per-name concentration cap, applied before normalization so one loud signal
    # cannot eat the whole risk budget.
    df["weight"] = df["weight"].clip(lower=-max_position_weight, upper=max_position_weight)

    # Normalize weights to sum to 1 in absolute values (risk budget)
    abs_sum = df["weight"].abs().sum()
    if abs_sum > 1e-9:
        df["weight"] = df["weight"] / abs_sum
    else:
        df["weight"] = 0.0
    return df

def pnl_from_weights(day_df: pd.DataFrame,
                      next_day_prices: pd.DataFrame,
                      trading_cost_bps: float = 5.0,
                      slippage_bps: float = 3.0,
                      short_borrow_bps_annual: float = 50.0) -> float:
    """
    Close-to-close return net of: flat fees, a slippage/impact charge proportional to
    turnover, and an annualized borrow cost charged only on short exposure.
    """
    df = day_df[["ticker", "weight", "close"]].merge(
        next_day_prices[["ticker", "close"]].rename(columns={"close": "close_next"}),
        on="ticker", how="inner",
    )
    df["ret"] = (df["close_next"] - df["close"]) / df["close"]
    gross = (df["weight"] * df["ret"]).sum()

    turnover = df["weight"].abs().sum()
    fee_cost = trading_cost_bps * 1e-4 * turnover
    slippage_cost = slippage_bps * 1e-4 * turnover

    short_exposure = df.loc[df["weight"] < 0, "weight"].abs().sum()
    borrow_cost = (short_borrow_bps_annual * 1e-4 / 252.0) * short_exposure

    return float(gross - fee_cost - slippage_cost - borrow_cost)

def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    return float(dd.min()) if len(dd) else 0.0
