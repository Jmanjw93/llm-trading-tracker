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
- [x] Alpaca paper API keys added to `.env` and connection verified (account ACTIVE, $100k equity, $400k buying power/margin) - 2026-11-12
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
- [x] Broker decision for going live: staying on Alpaca (not adding IBKR) - 2026-11-12, see README "Going live"
- [x] `--live` flag + two-factor safety gate (flag + LIVE_TRADING_CONFIRM env var + separate ALPACA_LIVE_* keys) built into `paper_trader.py` - 2026-11-12
- [x] Live Alpaca brokerage account applied for - **under review** as of 2026-11-12, see README "Going live" step 1.
- [ ] Live account funded - do not do this before re-running the RESEARCH.md §4 audit with real numbers
- [x] Fixed real bug: `_AlpacaAccount.fetch_recent_bars` defaulted to the SIP data feed, which the free plan doesn't include (403) - now explicitly requests `feed=IEX` - 2026-11-12, found by actually running against the real paper account, not just compiling
- [x] Fixed real bug: dry-run predictions were being written into the same blotter file as real paper/live predictions, so a test run could have corrupted real calibration data - dry-run now writes to a separate `outputs/dry_run_blotter.csv`, enforced at the source (not just filtered downstream) - 2026-11-12
- [x] Daily paper trading verified against the real Alpaca paper account (not synthetic) - connects, pulls real IEX bars, runs the agent, writes to `outputs/live_blotter.csv` - 2026-11-12
- **Scheduling for `src/live/paper_trader.py` (the actual trade-placing script) could not be auto-created by me** - the permission system blocks me from registering unattended automation that submits orders, even paper ones (two separate attempts: Windows Task Scheduler and WSL cron, both blocked as "Unauthorized Persistence"). This is intentional and correct - it should require a human's own hand on this specific step.
  - [x] Hardened the existing (data-collection-only) Windows Task Scheduler job with `StartWhenAvailable` + `WakeToRun`, so a missed day from the PC being off/asleep auto-catches-up - 2026-11-12
  - [x] Wrote `scripts/run_paper_trader_cron.sh` (WSL cron wrapper, calls the Windows Python via WSL interop) and tested it directly - confirmed working end to end - 2026-11-12
  - [ ] **On you**: install the crontab entry yourself (`crontab -e` inside WSL): `30 17 * * 1-5 /mnt/c/Users/wyetw/llm-trading-system/scripts/run_paper_trader_cron.sh`. Confirmed WSL cron is systemd-managed and currently active, and WSL's clock matches your local CST. Checked 2026-11-12: **not yet installed** (`crontab -l` returns "no crontab for wyetw").
- [ ] Local HF model (`--llm hf`) for live trading signals - **blocked: C: drive has ~189 MB free**, torch/transformers install failed with "No space left on device". Running `--llm mock` (the default) in the meantime. This is a real, broader problem for the machine, not just this project - worth freeing up disk space independent of this repo.
- [x] Corrected outdated PDT guidance in README: the $25k pattern day trader minimum was replaced by FINRA's new intraday margin standards effective 2026-06-04 - verified 2026-11-12 directly against our own account's API response (which now omits the deprecated field)
- [x] Cloud scheduling explored (Claude Code routines) - blocked on GitHub not being connected to the Claude account (`/web-setup` needed) - not pursued further since local WSL cron + Task Scheduler catch-up settings cover the reliability need for now

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
- **2026-11-12**: Decided to stay on Alpaca for live trading rather than add
  an Interactive Brokers adapter, specifically because paper and live share
  the identical API on Alpaca - the whole system already targets it, so going
  live needs zero code changes. IBKR is more respected among serious day
  traders generally, but its API complexity (local TWS/Gateway process) made
  it not worth a second adapter unless Alpaca becomes the actual blocker.
  Built a two-factor safety gate (`--live` flag + `LIVE_TRADING_CONFIRM` env
  var + separate live key names) so this can't be triggered by accident.
- **2026-11-12**: Added real Alpaca paper keys to `.env`, verified the
  connection, and found two real bugs only visible once running against the
  real account instead of synthetic data: the SIP-vs-IEX data feed 403, and
  dry-run/real blotter cross-contamination. Both fixed. Attempted to schedule
  `paper_trader.py` itself (Windows Task Scheduler, then WSL cron) - both
  blocked by the permission system as unattended trade-placing automation,
  which is the correct boundary; hardened the data-collection task's
  reliability settings instead and left the trade-placing cron entry for the
  user to install themselves.
