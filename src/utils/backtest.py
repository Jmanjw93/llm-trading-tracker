import os
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from .metrics import (
    annualized_return, sharpe_ratio, sortino_ratio,
    compute_max_drawdown, calmar_ratio, hit_rate, avg_daily_turnover,
)
from .portfolio import apply_positions, pnl_from_weights
import matplotlib.pyplot as plt

def _buy_and_hold_curve(df: pd.DataFrame, all_dates, benchmark_ticker: Optional[str] = None) -> pd.Series:
    """
    No-signal baseline: equal-weight, buy on day 1 and hold, across every ticker in the
    data (or a single benchmark_ticker if one is configured and present). Lets you see
    whether the LLM strategy is actually adding anything over doing nothing.
    """
    if benchmark_ticker is not None and benchmark_ticker in df["ticker"].unique():
        universe = [benchmark_ticker]
    else:
        universe = sorted(df["ticker"].unique())

    wide = df[df["ticker"].isin(universe)].pivot(index="date", columns="ticker", values="close")
    wide = wide.reindex(all_dates).ffill()
    rets = wide.pct_change().fillna(0.0)
    port_ret = rets.mean(axis=1)  # equal weight
    equity = (1 + port_ret).cumprod()
    equity.iloc[0] = 1.0
    return equity

def run_backtest(df: pd.DataFrame,
                  agent,
                  trading_cost_bps: float = 5.0,
                  slippage_bps: float = 3.0,
                  short_borrow_bps_annual: float = 50.0,
                  vol_target: float = 0.15,
                  max_position_weight: float = 0.25,
                  max_dd: float = 0.25,
                  dd_recover_frac: float = 0.5,
                  benchmark_ticker: Optional[str] = None,
                  blotter_path: Optional[str] = None,
                  equity_curve_path: str = "./outputs/equity_curve.png") -> Dict[str, Any]:
    """
    Assumes df is sorted by date; intra-day uses close-to-close.

    Drawdown kill switch: once equity falls more than max_dd from its running peak,
    risk_on is set False (book goes flat, zero new positions) and stays False until
    equity recovers dd_recover_frac of the drawdown that triggered it. This replaces
    the original repo's max_dd config field, which was defined but never enforced.
    """
    all_dates = sorted(df["date"].unique())
    bench_equity = _buy_and_hold_curve(df, all_dates, benchmark_ticker)
    equity = [1.0]
    rets = []
    logs = []
    detail_rows = []

    risk_on = True
    dd_trigger_equity = None   # equity level (post-shutdown) that counts as "recovered"
    peak_at_trigger = None

    for i in range(len(all_dates)-1):
        d = all_dates[i]
        nd = all_dates[i+1]
        day_df = df[df["date"] == d].copy()
        next_df = df[df["date"] == nd].copy()

        peak_so_far = max(equity)
        current_dd = (equity[-1] - peak_so_far) / peak_so_far if peak_so_far > 0 else 0.0

        if risk_on and current_dd <= -abs(max_dd):
            risk_on = False
            peak_at_trigger = peak_so_far
            dd_trigger_equity = equity[-1]
        elif not risk_on:
            # Stay flat until we've clawed back dd_recover_frac of the drawdown.
            recovered = (equity[-1] - dd_trigger_equity) / (peak_at_trigger - dd_trigger_equity + 1e-9)
            if recovered >= dd_recover_frac:
                risk_on = True

        preds = agent.predict_day(day_df)
        alloc = apply_positions(day_df, preds, vol_target=vol_target,
                                 max_position_weight=max_position_weight, risk_on=risk_on)
        ret = pnl_from_weights(alloc, next_df,
                                trading_cost_bps=trading_cost_bps,
                                slippage_bps=slippage_bps,
                                short_borrow_bps_annual=short_borrow_bps_annual)
        rets.append(ret)
        equity.append(equity[-1] * (1 + ret))

        turnover = float(alloc["weight"].abs().sum())
        logs.append({
            "date": d, "ret": ret, "equity": equity[-1], "turnover": turnover, "risk_on": risk_on,
            "benchmark_equity": float(bench_equity.get(d, np.nan)),
        })

        for _, r in alloc.iterrows():
            detail_rows.append({
                "date": d, "ticker": r["ticker"], "direction": r["direction"],
                "confidence": r["confidence"], "weight": r["weight"], "risk_on": risk_on,
            })

    equity_series = pd.Series(equity, index=all_dates)
    ret_series = pd.Series(rets, index=all_dates[1:])

    stats = {
        "annual_return": annualized_return(ret_series),
        "sharpe": sharpe_ratio(ret_series),
        "sortino": sortino_ratio(ret_series),
        "max_drawdown": compute_max_drawdown(equity_series),
        "calmar": calmar_ratio(ret_series, equity_series),
        "hit_rate": hit_rate(ret_series),
        "avg_daily_turnover": avg_daily_turnover(logs),
        "days_risk_off": int(sum(1 for l in logs if not l["risk_on"])),
    }

    stats["benchmark_annual_return"] = annualized_return(bench_equity.pct_change().dropna())
    stats["benchmark_max_drawdown"] = compute_max_drawdown(bench_equity)
    stats["excess_annual_return"] = stats["annual_return"] - stats["benchmark_annual_return"]

    os.makedirs(os.path.dirname(equity_curve_path) or ".", exist_ok=True)
    plt.figure()
    equity_series.plot(label="strategy")
    bench_equity.reindex(equity_series.index).plot(label="buy_and_hold")
    plt.title("Equity Curve vs Benchmark")
    plt.xlabel("Date")
    plt.ylabel("Equity")
    plt.legend()
    plt.tight_layout()
    plt.savefig(equity_curve_path)
    plt.close()

    if blotter_path:
        os.makedirs(os.path.dirname(blotter_path) or ".", exist_ok=True)
        pd.DataFrame(detail_rows).to_csv(blotter_path, index=False)

    return {"stats": stats, "equity_path": equity_curve_path, "logs": logs, "blotter_path": blotter_path}
