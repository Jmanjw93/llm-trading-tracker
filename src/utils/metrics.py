import numpy as np
import pandas as pd

def annualized_return(daily_returns: pd.Series, trading_days: int = 252) -> float:
    if len(daily_returns) == 0:
        return 0.0
    cum = (1 + daily_returns).prod()
    years = len(daily_returns) / trading_days
    if years <= 0:
        return 0.0
    return float(cum ** (1/years) - 1)

def sharpe_ratio(daily_returns: pd.Series, trading_days: int = 252) -> float:
    if len(daily_returns) == 0:
        return 0.0
    mean = daily_returns.mean() * trading_days
    vol = daily_returns.std(ddof=1) * np.sqrt(trading_days)
    return float(mean / (vol + 1e-9))

def sortino_ratio(daily_returns: pd.Series, trading_days: int = 252) -> float:
    """Like Sharpe but only penalizes downside volatility."""
    if len(daily_returns) == 0:
        return 0.0
    mean = daily_returns.mean() * trading_days
    downside = daily_returns[daily_returns < 0]
    down_vol = downside.std(ddof=1) * np.sqrt(trading_days) if len(downside) > 1 else 0.0
    return float(mean / (down_vol + 1e-9))

def compute_max_drawdown(equity_curve: pd.Series) -> float:
    if len(equity_curve) == 0:
        return 0.0
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak.replace(0, np.nan)
    return float(dd.min())

def calmar_ratio(daily_returns: pd.Series, equity_curve: pd.Series, trading_days: int = 252) -> float:
    """Annualized return divided by the magnitude of the worst drawdown."""
    ar = annualized_return(daily_returns, trading_days)
    mdd = abs(compute_max_drawdown(equity_curve))
    return float(ar / (mdd + 1e-9))

def hit_rate(daily_returns: pd.Series) -> float:
    """Fraction of trading days with a positive net return."""
    if len(daily_returns) == 0:
        return 0.0
    return float((daily_returns > 0).mean())

def avg_daily_turnover(logs: list) -> float:
    """Mean of |weight| summed across names per day, from the per-day blotter logs."""
    if not logs:
        return 0.0
    vals = [l.get("turnover", 0.0) for l in logs]
    return float(np.mean(vals)) if vals else 0.0
