"""
One-time bootstrap: scan Reddit's top posts over the past ~2 weeks for
candidate "legitimate good trade" posts, extract the tickers mentioned, and
check what those tickers' prices actually did over the ~14 trading days
following the earliest mention - i.e. cross-verify the crowd's claim against
real price action instead of trusting the post.

Run this once now to seed data/labeled/ with a starting batch of resolved
examples; `scripts/daily_collect.py` takes over day-by-day collection and
resolution from here.

Note: Reddit's public listing API only supports coarse windows (day/week/
month/...), not an arbitrary 14-day range, so this uses t=week as the closest
available approximation - see PROGRESS.md decisions log.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.collectors import market_collector, reddit_collector
from src.rules.rules_engine import reddit_mentions_by_ticker, FLAGS_DIR

HORIZON_TRADING_DAYS = 14


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    print("[bootstrap] Scanning Reddit (t=week) for candidate posts across:", reddit_collector.SUBREDDITS)
    posts = reddit_collector.collect_window(days=14, time_filter="week", limit=200)
    print(f"[bootstrap] {len(posts)} posts with at least one cashtag found.")

    mentions = reddit_mentions_by_ticker(posts)
    legit_tickers = sorted(mentions.keys())
    print(f"[bootstrap] {len(legit_tickers)} distinct tickers cleared the legitimacy bar: {legit_tickers}")

    if not legit_tickers:
        print("[bootstrap] Nothing to verify - done.")
        return

    print("[bootstrap] Fetching market history to verify realized returns...")
    bars = market_collector.fetch_bars(legit_tickers, lookback_days=HORIZON_TRADING_DAYS + 20)
    featured = market_collector.compute_anomaly_features(bars)

    rows = []
    for t in legit_tickers:
        tdf = featured[featured["ticker"] == t].sort_values("date").reset_index(drop=True)
        if len(tdf) < HORIZON_TRADING_DAYS + 1:
            continue
        entry = tdf.iloc[-(HORIZON_TRADING_DAYS + 1)]
        exit_ = tdf.iloc[-1]
        realized_return = (exit_["close"] - entry["close"]) / entry["close"]
        m = mentions[t]
        rows.append({
            "ticker": t,
            "entry_date": entry["date"],
            "exit_date": exit_["date"],
            "mention_count": m["mention_count"],
            "max_score": m["max_score"],
            "max_upvote_ratio": m["max_upvote_ratio"],
            "realized_return": realized_return,
            "good_trade": realized_return > 0.0,
            "source_posts": "; ".join(m["posts"]),
        })

    result = pd.DataFrame(rows)
    os.makedirs(FLAGS_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    out_path = f"{FLAGS_DIR}/bootstrap_scan_{today}.csv"
    result.to_csv(out_path, index=False)

    n_good = int(result["good_trade"].sum()) if len(result) else 0
    print(f"[bootstrap] Wrote {len(result)} verified rows to {out_path}")
    print(f"[bootstrap] {n_good}/{len(result)} of the Reddit-mentioned tickers were actually up over the following {HORIZON_TRADING_DAYS} trading days.")


if __name__ == "__main__":
    main()
