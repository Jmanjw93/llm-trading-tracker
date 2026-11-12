"""
Measures every day-to-day prediction the TradingAgent actually makes (not just
the confluence-flagged subset rules_engine.py tracks), and reports whether its
stated confidence is trustworthy.

Why this is separate from rules_engine.py: that module answers "was this
*flagged anomaly* a good trade" (a handful of events). This module answers
"across every single call the LLM made, was its direction right, and was its
confidence calibrated" (every row of outputs/live_blotter.csv or a backtest
blotter) - the actual day-to-day scoreboard the user asked for.

Design follows the same no-lookahead pattern as rules_engine.py and the
TrustTrade paper (see RESEARCH.md section 6): every prediction is logged with
its outcome fields empty, and only filled in once real time has actually
passed and the realized price is already in data/market/history.csv.
"""
import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

LEDGER_DIR = "./data/labeled"
PENDING_PATH = f"{LEDGER_DIR}/ledger_pending.csv"
RESOLVED_PATH = f"{LEDGER_DIR}/ledger_resolved.csv"

NEUTRAL_DEADBAND = 0.01  # a "neutral" call counts as correct if |realized_return| is within 1%


def _direction_correct(direction: str, realized_return: float, deadband: float = NEUTRAL_DEADBAND) -> bool:
    if direction == "bullish":
        return realized_return > 0
    if direction == "bearish":
        return realized_return < 0
    return abs(realized_return) <= deadband  # neutral


def sync_from_blotter(blotter_path: str, horizon_trading_days: int = 14) -> None:
    """
    Reads every (date, ticker, direction, confidence) row from a blotter CSV
    (outputs/live_blotter.csv, or a backtest blotter), adds any rows not
    already tracked to ledger_pending.csv, then attempts to resolve pending
    rows whose horizon has elapsed using data/market/history.csv. Safe to call
    repeatedly - already-tracked rows are skipped, already-resolved rows are
    never re-resolved.
    """
    if not os.path.exists(blotter_path):
        return
    blotter = pd.read_csv(blotter_path, parse_dates=["date"])
    if "dry_run" in blotter.columns:
        # Dry-run rows are synthetic test data (fake prices, fake "today") and
        # must never enter the calibration/memory pipeline alongside real
        # paper or live predictions - they'd silently corrupt both.
        blotter = blotter[blotter["dry_run"] != True]  # noqa: E712 (explicit for CSV-loaded bools/strings)
    if blotter.empty:
        return

    os.makedirs(LEDGER_DIR, exist_ok=True)
    pending = (pd.read_csv(PENDING_PATH, parse_dates=["date"])
               if os.path.exists(PENDING_PATH) else pd.DataFrame(columns=["date", "ticker"]))
    resolved = (pd.read_csv(RESOLVED_PATH, parse_dates=["date"])
                if os.path.exists(RESOLVED_PATH) else pd.DataFrame(columns=["date", "ticker"]))

    tracked_keys = set(zip(pending.get("date", []), pending.get("ticker", []))) | \
                   set(zip(resolved.get("date", []), resolved.get("ticker", [])))

    new_rows = blotter[~blotter.apply(lambda r: (r["date"], r["ticker"]) in tracked_keys, axis=1)].copy()
    if not new_rows.empty:
        new_rows["horizon_trading_days"] = horizon_trading_days
        pending = pd.concat([pending, new_rows], ignore_index=True)
        pending.to_csv(PENDING_PATH, index=False)

    _resolve_pending()


def _resolve_pending() -> None:
    if not os.path.exists(PENDING_PATH) or not os.path.exists("./data/market/history.csv"):
        return
    pending = pd.read_csv(PENDING_PATH, parse_dates=["date"])
    history = pd.read_csv("./data/market/history.csv", parse_dates=["date"])
    if pending.empty:
        return

    resolved_rows = []
    still_pending = []
    for _, row in pending.iterrows():
        tdf = history[history["ticker"] == row["ticker"]].sort_values("date")
        after = tdf[tdf["date"] > row["date"]]
        horizon = int(row.get("horizon_trading_days", 14))
        if len(after) < horizon:
            still_pending.append(row)
            continue
        entry_rows = tdf[tdf["date"] == row["date"]]
        if entry_rows.empty:
            still_pending.append(row)  # price history doesn't go back far enough for this entry date
            continue
        entry_price = float(entry_rows["close"].iloc[0])
        exit_price = float(after.iloc[horizon - 1]["close"])
        realized_return = (exit_price - entry_price) / entry_price

        out = row.to_dict()
        out["realized_return"] = realized_return
        out["correct_direction"] = _direction_correct(row["direction"], realized_return)
        resolved_rows.append(out)

    os.makedirs(LEDGER_DIR, exist_ok=True)
    if resolved_rows:
        new_resolved = pd.DataFrame(resolved_rows)
        existing = (pd.read_csv(RESOLVED_PATH, parse_dates=["date"])
                    if os.path.exists(RESOLVED_PATH) else pd.DataFrame())
        pd.concat([existing, new_resolved], ignore_index=True).to_csv(RESOLVED_PATH, index=False)

    pd.DataFrame(still_pending).to_csv(PENDING_PATH, index=False)


def compute_calibration(bins: int = 10) -> Dict:
    """
    Brier score (mean squared error between stated confidence and a 0/1
    correctness outcome - lower is better, 0.25 is what you'd get from always
    saying "50% confident") plus a per-confidence-decile reliability table:
    for calls in that confidence range, what fraction were actually correct.
    A well-calibrated model has bin avg_confidence ~= bin hit_rate; per the
    research in RESEARCH.md section 6, do not assume this holds without
    checking - many LLMs are overconfident even when directionally decent.
    """
    if not os.path.exists(RESOLVED_PATH):
        return {"n": 0}
    df = pd.read_csv(RESOLVED_PATH)
    if df.empty:
        return {"n": 0}

    outcome = df["correct_direction"].astype(float)
    confidence = df["confidence"].astype(float).clip(0, 1)
    brier = float(np.mean((confidence - outcome) ** 2))

    bin_edges = np.linspace(0, 1, bins + 1)
    df = df.assign(_bin=pd.cut(confidence, bin_edges, include_lowest=True))
    table = []
    for interval, group in df.groupby("_bin", observed=True):
        if len(group) == 0:
            continue
        table.append({
            "confidence_range": str(interval),
            "n": int(len(group)),
            "avg_confidence": float(group["confidence"].mean()),
            "hit_rate": float(group["correct_direction"].mean()),
        })

    return {
        "n": int(len(df)),
        "brier_score": brier,
        "overall_hit_rate": float(outcome.mean()),
        "reliability_table": table,
    }


def summarize_recent_performance(n: int = 10) -> Optional[str]:
    """
    Short text block for the LLM prompt's experience_block (see
    src/utils/prompt.py), following the "experience summary" pattern used by
    CryptoTrade and TradingGroup (RESEARCH.md section 6): a plain-language
    readout of recent track record, not a vague instruction to "do better."
    Returns None until there's at least one resolved call to report.
    """
    if not os.path.exists(RESOLVED_PATH):
        return None
    df = pd.read_csv(RESOLVED_PATH, parse_dates=["date"]).sort_values("date").tail(n)
    if df.empty:
        return None

    correct = int(df["correct_direction"].sum())
    total = len(df)
    avg_ret = float(df["realized_return"].mean())
    high_conf = df[df["confidence"] > 0.7]
    high_conf_note = ""
    if len(high_conf) >= 3:
        high_conf_note = (f" High-confidence calls (>0.7) were correct "
                           f"{int(high_conf['correct_direction'].sum())}/{len(high_conf)} times.")

    return (f"Recent track record (last {total} resolved calls): {correct}/{total} correct, "
            f"average realized return {avg_ret * 100:.2f}%.{high_conf_note} "
            f"Do not assume past direction repeats - use this to calibrate confidence, not to chase.")
