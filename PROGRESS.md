# Progress Tracker

**Target date for real money: February 16, 2027.**
Today: 2026-11-12. ~95 calendar days / ~66 trading days remaining.

This file is updated by `scripts/daily_collect.py` on every run (collection
day count, latest flags) and manually whenever rules or scope change. It is
the single source of truth for "where are we" across sessions.

## Status

- [x] Backtest engine fixed and extended (benchmark, drawdown kill switch, position caps, real cost model) - 2026-11-11
- [x] Paper trading runner built (Alpaca, dry-run + sim modes) - 2026-11-11
- [x] Private tracking repo created: `Jmanjw93/llm-trading-tracker` - 2026-11-12
- [x] Market data collector built (`src/collectors/market_collector.py`) - 2026-11-12
- [x] Reddit collector built, public-JSON fallback until PRAW creds are added (`src/collectors/reddit_collector.py`) - 2026-11-12
- [x] Rule engine + labeling pipeline built (`src/rules/rules_engine.py`, `RULES.md`) - 2026-11-12
- [ ] Reddit API credentials (REDDIT_CLIENT_ID/SECRET) added to `.env` - **blocked on you**, see README "Reddit API setup". Confirmed 2026-11-12 that the no-login fallback is blocked (403) from this network, so this isn't optional for real collection.
- [ ] Alpaca paper API keys added to `.env` - optional until real data collection matters more than synthetic
- [x] Windows Task Scheduler job created for `scripts/daily_collect.py` - runs weekdays at 5:00 PM local time - 2026-11-12
- [ ] First weekly rule review (needs 7 collection days first)
- [ ] First resolved flag (needs 14 trading days after first flag)
- [ ] Bootstrap Reddit scan (`scripts/bootstrap_reddit_scan.py`) - not yet run for real; needs working Reddit access first

## Collection log

| Date | Trading day # | Tickers | Flagged | Pending | Resolved | Notes |
|---|---|---|---|---|---|---|
| 2026-11-12 | 1 | 10 | none | 0 | 0 | |

## Decisions

- **2026-11-12**: Created a new private repo (`llm-trading-tracker`) instead of
  pushing to the original `kakuimei/-llm-trading-system` fork, since this is
  now the user's own strategy/data, not a contribution back to that project.
- **2026-11-12**: Confluence threshold (R5) set to 2-of-4 rules as a starting
  point; see RULES.md changelog for the reasoning and future revisions.
- **2026-11-12**: Reddit "legitimate good trade" scan uses reddit's coarse
  `top.json?t=week` window rather than a true 14-trading-day range, since
  Reddit's public listing API only supports hour/day/week/month/year/all, not
  arbitrary date ranges. Daily collection going forward fills in the finer
  granularity day by day.
