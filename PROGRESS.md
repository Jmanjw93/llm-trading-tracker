# Progress Tracker

**Target date for real money: February 16, 2027** — as of 2026-11-12, treat this
as a **scheduled review checkpoint, not an automatic go-live date**. See
RESEARCH.md §6: our sample size (50 tickers x ~66 trading days by then) will
likely still be below the field's own bar for a believable "this works" claim.
On that date, re-run the 5-question audit in RESEARCH.md §4 with real numbers
before deciding anything about real capital.

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
- [x] Research pass: surveyed academic WSB-sentiment literature + GitHub LLM-trading ecosystem, self-audited against an external rigor checklist - 2026-11-12, see `RESEARCH.md`
- [ ] FinBERT sentiment scoring (researched, not implemented - RESEARCH.md §2)
- [x] Day-to-day trade measurement: `src/rules/trade_ledger.py` resolves every blotter prediction (not just rule-flagged ones) against realized 14-day return, computes Brier score + a confidence-decile reliability table - 2026-11-12, see RESEARCH.md §5
- [x] FinMem-lite memory store (`src/agents/memory_store.py`): TF-IDF-based recency x relevancy x importance scoring over resolved calls, feeds the best matches in as few-shot examples instead of the two generic hardcoded ones - 2026-11-12, see RESEARCH.md §5
- [x] Experience-summary prompt block (CryptoTrade/TradingGroup pattern): `trade_ledger.summarize_recent_performance()` wired into every prompt via `experience_block` - 2026-11-12
- [ ] True embedding-based relevancy (currently TF-IDF) and multi-layer memory decay (FinMem's full design) - not implemented, see RESEARCH.md §5
- [ ] Re-run the RESEARCH.md §4 five-question audit with real numbers before Feb 16, 2027
- [ ] First calibration report with real (non-fabricated) data - needs 14 trading days of real live_blotter.csv predictions

## Collection log

| Date | Trading day # | Tickers | Flagged | Pending | Resolved | Notes |
|---|---|---|---|---|---|---|
| 2026-11-12 | 35 | 50 | ORLY | 2 | 0 | |

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
- **2026-11-12**: Expanded ticker universe from 10 to ~50 large-cap names and
  added HF model revision pinning, based on an external research pass - see
  `RESEARCH.md`. Also reframed Feb 16, 2027 from a fixed go-live date to a
  review checkpoint, for the same reason (sample size).
- **2026-11-12**: Built the day-to-day measurement/learning loop that was
  previously missing - `trade_ledger.py` (Brier score + calibration table +
  experience summary) and `memory_store.py` (FinMem-lite few-shot selection),
  wired into `paper_trader.py`. Verified against fabricated fixtures, not yet
  real data. See RESEARCH.md §5 and RULES.md "Known limitations" for the
  synthetic-mode history collision caveat this introduced.
