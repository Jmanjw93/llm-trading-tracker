"""
Daily orchestrator: run market + Reddit collection, evaluate rules, resolve any
flags whose 14-trading-day horizon has elapsed, update PROGRESS.md, and commit
+ push everything to the private tracking repo.

Meant to be invoked once per day by Windows Task Scheduler (see README "Daily
scheduling"), not run continuously. Safe to re-run the same day - collectors
de-duplicate on date.
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.collectors import market_collector, reddit_collector
from src.rules import rules_engine

# ~50 large-cap names (not a true point-in-time index snapshot - just a
# defensible-sized, recognizable universe) instead of the original 10. Per
# RESEARCH.md section 4 (Q5): a 10-name universe is a case study, not a
# backtest - this is a step toward the field's own ~50-name floor, not a
# claim of full index replication.
DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "COST",
    "NFLX", "AMD", "ADBE", "PEP", "CSCO", "TMUS", "INTC", "QCOM", "INTU", "TXN",
    "AMAT", "AMGN", "HON", "BKNG", "ISRG", "VRTX", "SBUX", "GILD", "MDLZ", "ADI",
    "LRCX", "REGN", "PANW", "PYPL", "SNPS", "CDNS", "KLAC", "MU", "CRWD", "MAR",
    "ORLY", "CTAS", "ABNB", "FTNT", "ADP", "MNST", "PCAR", "NXPI", "SPY", "QQQ",
]
PROGRESS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PROGRESS.md")


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _update_progress_log(date_str: str, trading_day_n: int, tickers, flagged_df, pending_count: int, resolved_count: int):
    with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    flagged_tickers = ", ".join(flagged_df[flagged_df["flagged"]]["ticker"].tolist()) or "none"
    new_row = f"| {date_str} | {trading_day_n} | {len(tickers)} | {flagged_tickers} | {pending_count} | {resolved_count} | |\n"

    content = content.replace("| (none yet - first run of daily_collect.py appends here) | | | | | | |\n", "")
    # Drop any existing row for today's date so re-running the same day is
    # idempotent instead of appending a duplicate.
    content = re.sub(rf"\| {re.escape(date_str)} \|[^\n]*\n", "", content)

    content = re.sub(
        r"(\| Date \| Trading day # \| Tickers \| Flagged \| Pending \| Resolved \| Notes \|\n\|[-| ]+\|\n)",
        r"\1" + new_row,
        content,
        count=1,
    )

    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def _git_commit_and_push(date_str: str):
    root = _repo_root()
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root)
    if diff.returncode == 0:
        print("[daily_collect] Nothing changed, skipping commit.")
        return
    subprocess.run(["git", "commit", "-m", f"daily collection: {date_str}"], cwd=root, check=True)
    subprocess.run(["git", "push"], cwd=root, check=True)


def main():
    # The collectors/rules modules use paths relative to the repo root
    # (./data/...). Task Scheduler launches with an arbitrary working
    # directory, so pin it explicitly rather than relying on the caller.
    os.chdir(_repo_root())

    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--min_confluence", type=int, default=2)
    ap.add_argument("--no_push", action="store_true", help="Skip the git commit/push step (for local testing).")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    today_str = datetime.now(timezone.utc).date().isoformat()
    print(f"[daily_collect] {today_str} - tickers: {tickers}")

    market_today = market_collector.collect_today(tickers)
    print(f"[daily_collect] market rows: {len(market_today)}")

    reddit_posts = reddit_collector.collect(time_filter="day", limit=100)
    print(f"[daily_collect] reddit posts collected: {len(reddit_posts)}")

    flagged_df = rules_engine.evaluate(market_today, reddit_posts, min_confluence=args.min_confluence)
    rules_engine.record_pending_flags(flagged_df)
    resolved = rules_engine.resolve_outcomes()

    flagged_list = flagged_df[flagged_df["flagged"]]["ticker"].tolist()
    print(f"[daily_collect] flagged today: {flagged_list or 'none'}")
    print(f"[daily_collect] newly resolved: {len(resolved)}")

    pending_count = 0
    if os.path.exists(rules_engine.PENDING_PATH):
        import pandas as pd
        pending_count = len(pd.read_csv(rules_engine.PENDING_PATH))
    resolved_count = 0
    if os.path.exists(rules_engine.RESOLVED_PATH):
        import pandas as pd
        resolved_count = len(pd.read_csv(rules_engine.RESOLVED_PATH))

    # Trading-day counter: number of distinct dates ever written to history.csv.
    import pandas as pd
    history = pd.read_csv(market_collector.HISTORY_PATH, parse_dates=["date"])
    trading_day_n = history["date"].nunique()

    _update_progress_log(today_str, trading_day_n, tickers, flagged_df, pending_count, resolved_count)

    if not args.no_push:
        _git_commit_and_push(today_str)
    else:
        print("[daily_collect] --no_push set, leaving changes uncommitted.")


if __name__ == "__main__":
    main()
