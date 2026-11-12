# LLM-Driven Daily Trading System

This project implements a **daily trading system** that integrates a Large Language Model (LLM) with market data, news, and fundamentals.
It follows the requested structure: data processing, LLM agent (prompt strategies & fine-tuning stubs), evaluation/backtest, risk management,
and optional advanced components (RAG retrieval + uncertainty-aware position sizing).

> **This is a research and paper-trading scaffold, not a validated money-making strategy.** The original backtest had several bugs (listed below) that meant it had never actually been run end to end on real data. Nothing here guarantees profit, and the paper trading runner places simulated orders against Alpaca's paper endpoint only.

## What changed from the original repo

Fixes (the pipeline would not run at all before these):
- `TradingAgent.fit()` used `Series or Series`, which pandas raises on for any non-empty series — the retriever could never actually be fit on real data.
- `build_prompt()` didn't accept `few_shot_examples`, so the `few_shot` strategy crashed immediately; it's now wired through into the prompt template.
- `add_technical_features()` used a `groupby().apply(..., include_groups=True)` call that current pandas rejects outright.
- `NewsRetriever.fit()` crashed with `ValueError: empty vocabulary` any time a batch of news text was empty or stop-words-only (a normal, frequent case) — now falls back to the lexical matcher instead of raising.
- `run.py` ran the valid and test backtests back to back before renaming either one's equity curve PNG, so the second run silently overwrote the first and the "valid" plot actually held the test data. Equity curve paths are now passed in explicitly, no more rename-after-the-fact race.
- `requirements.txt` was a raw `pip freeze` of the author's entire environment (hundreds of unrelated pinned packages). Replaced with the actual dependencies this repo uses.

Additions (gaps the original never addressed):
- **Benchmark comparison.** Every backtest now also computes a buy-and-hold curve (set `benchmark_ticker`, or it defaults to an equal-weight basket of everything in the data) and reports `excess_annual_return` against it.
- **An enforced drawdown kill switch.** `max_dd` existed in `Config` before but was never checked anywhere. It now actually flattens the book when breached and keeps it flat until `dd_recover_frac` of the drawdown is clawed back.
- **Per-name position caps** (`max_position_weight`) so one loud signal can't dominate the whole risk budget.
- **A real cost model**: flat fees + a separate slippage/impact charge + an annualized short-borrow cost on short exposure only, instead of one flat bps number covering everything.
- **More metrics**: Sortino, Calmar, hit rate, average daily turnover, days spent risk-off — not just CAGR/Sharpe/max drawdown.
- **A full trade blotter CSV** per backtest run (`outputs/blotter_valid_<model>.csv`, `blotter_test_<model>.csv`) with every ticker's direction, confidence, and weight each day, not just an aggregate equity curve.
- **A real local LLM backend** (`HFModel` in `src/agents/llm_interface.py`) that actually loads and runs an instruction-tuned causal model via Transformers and parses its JSON output, replacing the old `NotImplementedError` stub. Defaults to a CPU-sized model (`Qwen/Qwen2.5-1.5B-Instruct`); pass `--hf_model_name` for anything else.
- **A paper trading runner** (`src/live/paper_trader.py`) — see below. The original repo had no path from backtest to any kind of execution at all.

## Project Layout
```
llm_trading_system/
  data/
    data.csv                        # Put your dataset here (date,ticker,open,high,low,close,volume,news,pe,roe,...)
    data_synthetic.csv               # Small generated dataset for smoke-testing the pipeline
    market/                          # Daily collector output: history.csv + one snapshot per day
    reddit/                          # Daily collector output: one JSON per day of candidate posts
    labeled/                         # pending_flags.csv, resolved_flags.csv, bootstrap_scan_*.csv
  src/
    agents/
      trading_agent.py
      rag_retriever.py
      llm_interface.py               # MockLLM, HFModel (real local inference), OpenAIModel (stub)
    utils/
      data_loader.py
      feature_engineering.py
      portfolio.py                   # position sizing, caps, slippage/borrow cost
      metrics.py                     # sharpe/sortino/calmar/hit_rate/turnover
      backtest.py                    # benchmark + drawdown kill switch + blotter
      helper.py
    live/
      paper_trader.py                # daily paper-trading runner (Alpaca)
    collectors/
      market_collector.py            # daily bars + anomaly features (volume z-score, gap, RSI)
      reddit_collector.py            # candidate "legitimate good trade" posts (PRAW + public fallback)
    rules/
      rules_engine.py                # confluence rules, pending/resolved flag tracking, weekly review
    config.py
    run.py
  scripts/
    daily_collect.py                 # orchestrator: collect -> evaluate -> resolve -> commit/push
    bootstrap_reddit_scan.py         # one-time ~2-week historical Reddit scan
  outputs/                          # Backtest outputs (equity curves, logs, blotters) - gitignored
  RULES.md                           # human-readable rules + changelog
  PROGRESS.md                        # day-by-day status tracker
  .env.example                       # Copy to .env for your Alpaca + Reddit keys
  README.md
  requirements.txt
```

## Quick Start (backtest)
1) Install dependencies (ideally in a virtual environment):
```bash
pip install -r requirements.txt
```

2) Prepare your data as `./data/data.csv` with at least these columns:
```
date,ticker,open,high,low,close,volume,news,pe,roe
```
- `date` format: `YYYY-MM-DD`
- `news` can be a string (headline/summary concatenated per day), or empty — the pipeline no longer crashes on sparse news.

Or smoke-test immediately with the included synthetic dataset:
```bash
python -m src.run --data ./data/data_synthetic.csv --start 2023-01-01 --end 2023-06-30 --strategy rag_uncertainty --llm mock --benchmark_ticker AAA
```

3) Run for real, with a real local model instead of the heuristic mock:
```bash
python -m src.run --data ./data/data.csv --strategy rag_uncertainty --start 2019-01-01 --end 2024-12-31 --llm hf --hf_model_name Qwen/Qwen2.5-1.5B-Instruct
```

Useful overrides (all optional, see `Config` in `src/config.py` for defaults):
```
--trading_cost_bps --slippage_bps --short_borrow_bps --vol_target
--max_position_weight --max_dd --dd_recover_frac --benchmark_ticker
```

Outputs land in `./outputs/`: `results.json` (stats per model), `equity_curve_{valid,test}_<model>.png` (strategy vs. benchmark), `blotter_{valid,test}_<model>.csv` (every decision, every day).

## Paper Trading (no real money)

`src/live/paper_trader.py` runs the same agent + risk pipeline once per day against a real (paper) brokerage account via [Alpaca](https://alpaca.markets/). It is intentionally a one-shot script, not a persistent process — schedule it yourself (Windows Task Scheduler, cron, etc.) for however often you want it to rebalance.

**Always dry-run first.** This needs no API keys, hits no network, and uses synthetic prices and a fake local account purely so you can see the full pipeline (features → agent → sizing → "orders") before anything real is involved:
```bash
python -m src.live.paper_trader --tickers AAPL,MSFT,NVDA --dry_run
```

To actually run against your Alpaca **paper** account:
1. Create a free Alpaca account and generate **paper** (not live) API keys at https://alpaca.markets/.
2. Copy `.env.example` to `.env` and fill in `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`. `.env` is gitignored — never commit it.
3. `pip install -r requirements.txt` (pulls in `alpaca-py` and `python-dotenv`).
4. `python -m src.live.paper_trader --tickers AAPL,MSFT,NVDA`

The script hardcodes `paper=True` when constructing the Alpaca `TradingClient` — there is no flag to flip that to live trading. Every run appends to `outputs/live_blotter.csv` (full decision + order log) and persists the drawdown kill switch's state in `outputs/live_state.json` across runs.

**On going from paper to real money:** that is a decision only you can make, not something to flip a flag on. An LLM-driven strategy that hasn't been validated out-of-sample, against a benchmark, across different market regimes, risking actual capital is genuinely risky — treat paper trading as a multi-month validation step, not a formality.

## Data Collection & Rules (building toward Feb 16, 2027)

**Target date for adding real money: February 16, 2027.** Until then, this repo
runs a daily collection loop that gathers market anomalies and Reddit-sourced
candidate trades, checks each one's realized outcome 14 trading days later, and
uses that resolved data to make the rules (and eventually the LLM) actually
evidence-based instead of guessing. The full ruleset lives in `RULES.md` —
read that for *what* the rules are; this section is about running the pipeline.
`PROGRESS.md` is the day-by-day status tracker, and `RESEARCH.md` is an
evidence log of external research (academic papers, GitHub projects) that
actually changed something here, including a self-audit of this repo against
an external rigor checklist for LLM trading claims — read that before trusting
any backtest number this system produces.

**Reddit API setup** (needed for reliable collection — Reddit blocks most
unauthenticated/datacenter traffic to its public JSON endpoints, so the
no-login fallback is a stopgap, not the real path):
1. Log into Reddit, go to https://www.reddit.com/prefs/apps, click "create app".
2. Choose type **script**, leave the redirect URI as `http://localhost:8080`.
3. Copy the client ID (under the app name) and client secret into `.env`:
   `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`.
4. No further login/password needed — this is read-only.

**Bootstrap scan** (run once, seeds `data/labeled/` with an initial batch from
the past ~2 weeks of Reddit activity, cross-checked against real price data):
```bash
python scripts/bootstrap_reddit_scan.py
```

**Daily collection** (market data + Reddit + rule evaluation + outcome
resolution + commit/push to this repo):
```bash
python scripts/daily_collect.py
```

**Daily scheduling (Windows Task Scheduler).** A task named `LLM Trading Daily
Collection` runs this once per weekday at 5:00 PM local time. To recreate it
(e.g. on a new machine):
```powershell
schtasks /Create /TN "LLM Trading Daily Collection" /TR "\"C:\Python314\python.exe\" \"C:\Users\wyetw\llm-trading-system\scripts\daily_collect.py\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 17:00 /F
```
This only runs while your PC is on and awake at that time — it is not a
server-hosted job. Check `PROGRESS.md`'s collection log periodically to make
sure days aren't being silently missed.

**How this feeds back into the LLM:** `data/labeled/resolved_flags.csv` is the
ground-truth dataset — each row is a confluence-flagged ticker and whether it
was actually profitable 14 trading days later. Once there's a meaningful
sample, pull the best resolved examples into `AgentConfig.few_shots` (replacing
the two generic hardcoded examples in `trading_agent.py`), and/or use the file
as real training data for `sft_train.py` / `peft_train_lora.py`, which
previously had no real-world data to train on at all.

## What's Implemented
- **Data processing & feature engineering**: Missing value handling, returns/volatility/RSI features, prompt-ready features.
- **LLM TradingAgent**: Zero-shot / Few-shot / RAG strategies + uncertainty sampling. `MockLLM` for offline runs, `HFModel` for real local inference.
- **RAG Retriever**: TF-IDF (if available) or fallback lexical similarity for news context; degrades gracefully on empty news.
- **Risk Management & Portfolio**: Confidence-weighted sizing, volatility targeting, per-name concentration caps, an enforced max-drawdown kill switch, fees + slippage + short borrow cost.
- **Backtest Framework**: Time-based split, run & evaluate (CAGR, Sharpe, Sortino, Calmar, hit rate, turnover, max drawdown) against a benchmark, save equity curve plot and full trade blotter.
- **Paper Trading**: Daily Alpaca paper-account runner sharing the same agent/risk code as the backtest.

## Replace the LLM
- `HFModel` in `src/agents/llm_interface.py` is implemented for real — pass `--llm hf --hf_model_name <hub name or local path>`.
- `OpenAIModel` is still a stub (`raise NotImplementedError`) if you'd rather call the OpenAI API; implement `generate()` there and add your own key handling.

## Fine-Tuning / PEFT
- `sft_train.py` / `peft_train_lora.py` remain as training entry points; `run.py --do_train` will invoke them and then backtest the resulting checkpoints alongside `mock`.
- `FineTunedStubModel` in `llm_interface.py` demonstrates simple rule-based biasing — replace with real PEFT/SFT/RLHF output once you have a trained checkpoint.

## Notes
- The dataset schema can vary; `data_loader` tries to be robust and will warn if some columns are missing.
- For true research, iterate on: prompt templates, retrieval windows, uncertainty calibration, portfolio construction, and validating the HF model's signal against the benchmark before ever pointing this at paper trading.
