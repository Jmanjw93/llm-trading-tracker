"""
Rule engine: turns today's market features + Reddit posts into a short list of
flagged tickers, following the confluence rule in RULES.md - no single signal
is trusted alone. See RULES.md for the human-readable version of every rule
here; keep the two in sync when either changes.
"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd

FLAGS_DIR = "./data/labeled"
PENDING_PATH = f"{FLAGS_DIR}/pending_flags.csv"  # flags awaiting their 14-trading-day outcome
RESOLVED_PATH = f"{FLAGS_DIR}/resolved_flags.csv"  # flags with a realized outcome, i.e. the training set


def reddit_mentions_by_ticker(posts: List[Dict]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for p in posts:
        if not p.get("legitimate_candidate"):
            continue
        for t in p.get("tickers", []):
            rec = out.setdefault(t, {"mention_count": 0, "max_score": 0, "max_upvote_ratio": 0.0, "posts": []})
            rec["mention_count"] += 1
            rec["max_score"] = max(rec["max_score"], p.get("score", 0))
            rec["max_upvote_ratio"] = max(rec["max_upvote_ratio"], p.get("upvote_ratio") or 0.0)
            rec["posts"].append(p["url"])
    return out


def evaluate(market_today: pd.DataFrame, reddit_posts: List[Dict], min_confluence: int = 2) -> pd.DataFrame:
    """
    market_today: one row per ticker, output of market_collector.collect_today()
    (must have flag_volume_spike, flag_price_gap, flag_rsi_extreme columns).

    Returns one row per ticker with each rule's boolean, a reddit_momentum flag
    (>=3 legitimate-candidate mentions today), an anomaly_score (count of
    triggered rules), and `flagged` = anomaly_score >= min_confluence. This is
    Rule R5 (confluence) from RULES.md: single-signal noise never gets flagged.
    """
    mentions = reddit_mentions_by_ticker(reddit_posts)

    rows = []
    for _, r in market_today.iterrows():
        t = r["ticker"]
        m = mentions.get(t, {"mention_count": 0, "max_score": 0, "max_upvote_ratio": 0.0, "posts": []})
        reddit_momentum = m["mention_count"] >= 3

        rule_flags = {
            "flag_volume_spike": bool(r.get("flag_volume_spike", False)),
            "flag_price_gap": bool(r.get("flag_price_gap", False)),
            "flag_rsi_extreme": bool(r.get("flag_rsi_extreme", False)),
            "flag_reddit_momentum": reddit_momentum,
        }
        anomaly_score = sum(rule_flags.values())

        rows.append({
            "date": r["date"], "ticker": t,
            **rule_flags,
            "reddit_mention_count": m["mention_count"],
            "reddit_max_score": m["max_score"],
            "reddit_max_upvote_ratio": m["max_upvote_ratio"],
            "reddit_post_urls": "; ".join(m["posts"]),
            "anomaly_score": anomaly_score,
            "flagged": anomaly_score >= min_confluence,
        })
    return pd.DataFrame(rows)


def record_pending_flags(flagged_df: pd.DataFrame, horizon_trading_days: int = 14) -> None:
    """Appends every newly flagged ticker to pending_flags.csv so a later run
    of resolve_outcomes() can check back in `horizon_trading_days` and compute
    whether it was actually a good trade."""
    new_flags = flagged_df[flagged_df["flagged"]].copy()
    if new_flags.empty:
        return
    new_flags["horizon_trading_days"] = horizon_trading_days
    new_flags["resolved"] = False

    os.makedirs(FLAGS_DIR, exist_ok=True)
    if os.path.exists(PENDING_PATH):
        existing = pd.read_csv(PENDING_PATH, parse_dates=["date"])
        existing = existing[~((existing["date"].astype(str) == new_flags["date"].astype(str).iloc[0]) &
                               (existing["ticker"].isin(new_flags["ticker"])))]
        combined = pd.concat([existing, new_flags], ignore_index=True)
    else:
        combined = new_flags
    combined.to_csv(PENDING_PATH, index=False)


def resolve_outcomes(market_history_path: str = "./data/market/history.csv") -> pd.DataFrame:
    """
    For every pending flag whose horizon has elapsed (>= horizon_trading_days of
    market data now exist after its flag date), compute the realized forward
    return and move it from pending_flags.csv to resolved_flags.csv. This is
    the labeled dataset: ground truth on whether each rule-and-Reddit-backed
    callout actually made money, used by weekly_rule_review() and as source
    material for few-shot examples / future SFT training data.
    """
    if not os.path.exists(PENDING_PATH) or not os.path.exists(market_history_path):
        return pd.DataFrame()

    pending = pd.read_csv(PENDING_PATH, parse_dates=["date"])
    history = pd.read_csv(market_history_path, parse_dates=["date"])

    resolved_rows = []
    still_pending = []
    for _, row in pending.iterrows():
        t = row["ticker"]
        tdf = history[history["ticker"] == t].sort_values("date")
        after = tdf[tdf["date"] > row["date"]]
        if len(after) < row["horizon_trading_days"]:
            still_pending.append(row)
            continue

        entry_rows = tdf[tdf["date"] == row["date"]]
        if entry_rows.empty:
            still_pending.append(row)
            continue
        entry_price = float(entry_rows["close"].iloc[0])
        exit_price = float(after.iloc[row["horizon_trading_days"] - 1]["close"])
        realized_return = (exit_price - entry_price) / entry_price

        resolved = row.to_dict()
        resolved["realized_return"] = realized_return
        resolved["good_trade"] = realized_return > 0.0
        resolved["resolved"] = True
        resolved_rows.append(resolved)

    os.makedirs(FLAGS_DIR, exist_ok=True)
    if resolved_rows:
        new_resolved = pd.DataFrame(resolved_rows)
        if os.path.exists(RESOLVED_PATH):
            prior = pd.read_csv(RESOLVED_PATH, parse_dates=["date"])
            combined = pd.concat([prior, new_resolved], ignore_index=True)
        else:
            combined = new_resolved
        combined.to_csv(RESOLVED_PATH, index=False)

    pd.DataFrame(still_pending).to_csv(PENDING_PATH, index=False)
    return pd.DataFrame(resolved_rows)


def weekly_rule_review(min_observations: int = 10) -> Dict[str, Dict]:
    """
    Per-rule hit rate among resolved flags: for every rule that was one of the
    triggers on a resolved flag, what fraction of those flags turned out to be
    good_trade. Rules below 50% with enough samples are candidates to down-
    weight - this function reports the numbers; RULES.md's changelog is where
    a human (or a future automated step) records the actual threshold change.
    """
    if not os.path.exists(RESOLVED_PATH):
        return {}
    df = pd.read_csv(RESOLVED_PATH)
    rule_cols = ["flag_volume_spike", "flag_price_gap", "flag_rsi_extreme", "flag_reddit_momentum"]
    report = {}
    for col in rule_cols:
        subset = df[df[col] == True]
        n = len(subset)
        if n >= min_observations:
            report[col] = {
                "n": n,
                "hit_rate": float(subset["good_trade"].mean()),
                "avg_realized_return": float(subset["realized_return"].mean()),
            }
        else:
            report[col] = {"n": n, "hit_rate": None, "avg_realized_return": None,
                            "note": f"below min_observations ({min_observations})"}
    return report
