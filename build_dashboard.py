import json
import pandas as pd

equity = pd.read_csv("./outputs/live_sim_equity_curve.csv")
blotter = pd.read_csv("./outputs/live_sim_blotter.csv")

tickers = sorted(blotter["ticker"].unique().tolist())
dates = equity["date"].tolist()

blotter_by_ticker = {}
for t in tickers:
    sub = blotter[blotter["ticker"] == t].set_index("date")
    rows = []
    for d in dates:
        if d in sub.index:
            r = sub.loc[d]
            rows.append({
                "direction": str(r["direction"]),
                "confidence": float(r["confidence"]),
                "weight": float(r["weight"]),
            })
        else:
            rows.append(None)
    blotter_by_ticker[t] = rows

# Recompute stats from the equity/blotter CSVs we already have, matching the
# metrics module so the dashboard numbers always match the console output.
import sys
sys.path.insert(0, ".")
from src.utils.metrics import (
    annualized_return, sharpe_ratio, sortino_ratio, compute_max_drawdown,
    calmar_ratio, hit_rate, avg_daily_turnover,
)

ret_series = equity["ret"].iloc[1:]
equity_series = equity["equity"]
bench_series = equity["benchmark_equity"]

stats = {
    "annual_return": annualized_return(ret_series),
    "sharpe": sharpe_ratio(ret_series),
    "sortino": sortino_ratio(ret_series),
    "max_drawdown": compute_max_drawdown(equity_series),
    "calmar": calmar_ratio(ret_series, equity_series),
    "hit_rate": hit_rate(ret_series),
    "avg_daily_turnover": avg_daily_turnover(equity.to_dict("records")),
    "days_risk_off": int((~equity["risk_on"]).sum()),
    "benchmark_annual_return": annualized_return(bench_series.pct_change().dropna()),
    "excess_annual_return": None,
}
stats["excess_annual_return"] = stats["annual_return"] - stats["benchmark_annual_return"]

payload = {
    "tickers": tickers,
    "dates": dates,
    "equity": equity.to_dict("records"),
    "blotter": blotter.to_dict("records"),
    "blotter_by_ticker": blotter_by_ticker,
    "stats": stats,
}

with open("dashboard_template.html", "r", encoding="utf-8") as f:
    template = f.read()

out = template.replace("__DATA_JSON__", json.dumps(payload))
with open("paper_trading_dashboard.html", "w", encoding="utf-8") as f:
    f.write(out)

print("wrote paper_trading_dashboard.html", len(out), "bytes")
