"""
FinMem-lite: a lightweight version of the memory scoring from FinMem (Yu et
al., arXiv 2311.13743) - see RESEARCH.md section 6 for the full writeup.

The original scores each memory event by recency x relevancy x importance
(exponential recency decay per Ebbinghaus's forgetting curve, embedding
similarity for relevancy, a piecewise importance function) across multiple
memory layers with different decay rates. This is a single-layer
simplification using TF-IDF cosine similarity instead of a trained embedding
model (keeps the dependency footprint to what's already required -
scikit-learn - rather than adding a sentence-transformers model), used to pick
which *resolved* past calls are worth showing the LLM as few-shot examples,
instead of the two generic hardcoded examples in AgentConfig.few_shots.

This replaces guessing with evidence once real data exists: with zero
resolved calls, build_few_shot_examples() returns an empty list and callers
should fall back to the generic defaults.
"""
import os
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd

from ..rules.trade_ledger import RESOLVED_PATH

RECENCY_STABILITY_DAYS = 30.0  # single layer; FinMem uses multiple layers with different stability
IMPORTANCE_SATURATION_RETURN = 0.05  # a 5% realized move scores max importance


def _load_events() -> pd.DataFrame:
    if not os.path.exists(RESOLVED_PATH):
        return pd.DataFrame()
    df = pd.read_csv(RESOLVED_PATH, parse_dates=["date"])
    return df[df["reason"].notna() & (df["reason"].astype(str).str.len() > 0)] if "reason" in df.columns else df


def _recency(event_date, now) -> float:
    age_days = max(0.0, (now - event_date).total_seconds() / 86400.0)
    return float(np.exp(-age_days / RECENCY_STABILITY_DAYS))


def _importance(realized_return: float) -> float:
    return float(min(1.0, abs(realized_return) / IMPORTANCE_SATURATION_RETURN))


def _relevancy(events: pd.DataFrame, query_ticker: str, query_text: str) -> np.ndarray:
    """TF-IDF cosine similarity between query_text and each event's reason
    text; falls back to a flat ticker-match boost if there isn't enough text
    to fit a vectorizer (e.g. only one or two resolved events so far)."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        corpus = list(events["reason"].astype(str)) + [query_text or ""]
        vec = TfidfVectorizer(max_features=2000, ngram_range=(1, 2))
        matrix = vec.fit_transform(corpus).toarray()
        query_vec = matrix[-1]
        doc_vecs = matrix[:-1]
        denom = (np.linalg.norm(query_vec) * np.linalg.norm(doc_vecs, axis=1) + 1e-9)
        sims = (doc_vecs @ query_vec) / denom
    except ValueError:
        sims = np.zeros(len(events))
    ticker_boost = (events["ticker"] == query_ticker).astype(float).to_numpy() * 0.3
    return np.clip(sims + ticker_boost, 0, 1)


def build_few_shot_examples(query_ticker: str, query_text: str = "", k: int = 3,
                             now: Optional[datetime] = None) -> List[str]:
    events = _load_events()
    if events.empty:
        return []
    now = now or datetime.now()

    recency = events["date"].apply(lambda d: _recency(d, now)).to_numpy()
    importance = events["realized_return"].apply(_importance).to_numpy()
    relevancy = _relevancy(events, query_ticker, query_text)

    # Weighted blend (not a strict product) so one weak factor can't zero out
    # an otherwise-relevant memory - a deliberate simplification vs FinMem's
    # product formulation, documented here rather than silently diverging.
    score = (0.4 * recency) + (0.35 * relevancy) + (0.25 * importance)
    events = events.assign(_score=score)
    top = events.sort_values("_score", ascending=False).head(k)

    examples = []
    for _, r in top.iterrows():
        verdict = "correct" if bool(r["correct_direction"]) else "incorrect"
        examples.append(
            f'Input: {r["ticker"]} setup - {r["reason"]} '
            f'Output: {{"direction":"{r["direction"]}","confidence":{float(r["confidence"]):.2f},'
            f'"reason":"{r["reason"]} (actual {int(r.get("horizon_trading_days", 14))}-day return '
            f'{float(r["realized_return"]) * 100:+.1f}%, this call was {verdict})"}}'
        )
    return examples
