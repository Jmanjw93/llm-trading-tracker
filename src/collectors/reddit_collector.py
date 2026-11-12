"""
Daily Reddit collector for candidate "legitimate good trade" posts.

Primary path: PRAW with your own Reddit API app credentials (REDDIT_CLIENT_ID,
REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT in .env). See README "Reddit API setup"
for how to create one - it needs your own Reddit login, so I can't create it
for you.

Fallback path (used automatically if those env vars aren't set yet): Reddit's
public read-only JSON endpoints (reddit.com/r/<sub>/top.json). No account
needed, but more rate-limited and sometimes blocked - good enough to start
collecting today and swap to PRAW once your app credentials are ready.

"Legitimate" here does not mean verified - it means the post cleared a bar
(flair, score, upvote ratio) that filters out obvious noise. Actual legitimacy
is established later in verify_trades.py by checking what the ticker's price
really did, not by trusting the post.
"""
import os
import re
import time
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional

import requests

SUBREDDITS = ["wallstreetbets", "stocks", "options", "investing"]
CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
GAIN_FLAIRS = {"gain", "gains", "yolo", "dd"}
MIN_SCORE_BY_SUB = {"wallstreetbets": 500, "stocks": 150, "options": 100, "investing": 150}
MIN_UPVOTE_RATIO = 0.85

OUT_DIR = "./data/reddit"


def _extract_tickers(text: str) -> List[str]:
    return sorted(set(CASHTAG_RE.findall(text or "")))


def _is_legitimate(subreddit: str, score: int, upvote_ratio: Optional[float], flair: Optional[str]) -> bool:
    # flair (GAIN_FLAIRS) is logged for later analysis but not required here -
    # score + upvote ratio are the actual noise filter.
    min_score = MIN_SCORE_BY_SUB.get(subreddit, 150)
    ratio_ok = upvote_ratio is None or upvote_ratio >= MIN_UPVOTE_RATIO
    return score >= min_score and ratio_ok


def _collect_via_praw(time_filter: str, limit: int) -> List[Dict]:
    import praw
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "llm-trading-tracker/0.1 (daily research collector)"),
    )
    posts = []
    for sub in SUBREDDITS:
        for post in reddit.subreddit(sub).top(time_filter=time_filter, limit=limit):
            tickers = _extract_tickers((post.title or "") + " " + (post.selftext or ""))
            if not tickers:
                continue
            legit = _is_legitimate(sub, post.score, getattr(post, "upvote_ratio", None), getattr(post, "link_flair_text", None))
            posts.append({
                "id": post.id, "subreddit": sub, "title": post.title,
                "score": post.score, "upvote_ratio": getattr(post, "upvote_ratio", None),
                "flair": getattr(post, "link_flair_text", None),
                "created_utc": datetime.fromtimestamp(post.created_utc, tz=timezone.utc).isoformat(),
                "tickers": tickers, "legitimate_candidate": legit,
                "url": f"https://reddit.com{post.permalink}",
                "source": "praw",
            })
    return posts


def _collect_via_public_json(time_filter: str, limit: int) -> List[Dict]:
    posts = []
    headers = {"User-Agent": "llm-trading-tracker-research/0.1 (by u/research-collector)"}
    for sub in SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/top.json"
        try:
            resp = requests.get(url, params={"t": time_filter, "limit": limit}, headers=headers, timeout=15)
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
        except Exception as e:
            print(f"[reddit_collector] WARNING: public JSON fetch failed for r/{sub}: {e}")
            children = []
        for c in children:
            p = c.get("data", {})
            tickers = _extract_tickers((p.get("title") or "") + " " + (p.get("selftext") or ""))
            if not tickers:
                continue
            legit = _is_legitimate(sub, p.get("score", 0), p.get("upvote_ratio"), p.get("link_flair_text"))
            posts.append({
                "id": p.get("id"), "subreddit": sub, "title": p.get("title"),
                "score": p.get("score", 0), "upvote_ratio": p.get("upvote_ratio"),
                "flair": p.get("link_flair_text"),
                "created_utc": datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc).isoformat(),
                "tickers": tickers, "legitimate_candidate": legit,
                "url": f"https://reddit.com{p.get('permalink', '')}",
                "source": "public_json",
            })
        time.sleep(1)  # be polite to the unauthenticated endpoint
    return posts


def collect(time_filter: str = "day", limit: int = 100) -> List[Dict]:
    has_praw_creds = os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")
    if has_praw_creds:
        try:
            posts = _collect_via_praw(time_filter, limit)
        except Exception as e:
            print(f"[reddit_collector] PRAW failed ({e}), falling back to public JSON.")
            posts = _collect_via_public_json(time_filter, limit)
    else:
        posts = _collect_via_public_json(time_filter, limit)

    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    with open(f"{OUT_DIR}/{today}.json", "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2)
    return posts


def collect_window(days: int, time_filter: str = "week", limit: int = 100) -> List[Dict]:
    """
    One-time bootstrap scan: pull the top posts over `time_filter` (reddit only
    supports coarse windows - hour/day/week/month/year/all, not an arbitrary
    N-day range) as a starting dataset for the last ~2 weeks. Finer-grained daily
    scans happen going forward via the scheduled collect() calls instead.
    """
    return collect(time_filter=time_filter, limit=limit)
