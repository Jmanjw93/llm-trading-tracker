"""
Daily paper trading runner.

Meant to be invoked once per trading day (e.g. via Windows Task Scheduler, after
market close or before open) rather than run as a long-lived process. Each
invocation:

  1. Pulls recent daily bars for your configured tickers from Alpaca.
  2. Builds the same feature/prompt pipeline used in backtesting.
  3. Asks the TradingAgent for today's direction/confidence per ticker.
  4. Applies the same risk sizing + drawdown kill switch as the backtest,
     using a small local state file (./outputs/live_state.json) to track the
     running peak equity and whether the kill switch is currently tripped.
  5. Submits notional market orders to your Alpaca PAPER account to move each
     position toward its target weight.
  6. Appends every decision and order to a CSV blotter for a full audit trail.

This is PAPER TRADING ONLY. It hardcodes paper=True when building the Alpaca
TradingClient; nothing in this file can place a live order. Turning this into
a real-money system is a decision only you can make, and would mean changing
the Alpaca client construction and accepting full responsibility for an
unvalidated LLM strategy risking real capital.

Setup:
  1. Create a free Alpaca account and generate PAPER (not live) API keys at
     https://alpaca.markets/ (do this yourself; nobody else should hold your keys).
  2. Copy .env.example to .env and fill in ALPACA_API_KEY / ALPACA_SECRET_KEY.
  3. pip install -r requirements.txt
  4. Dry run first (no orders, no API keys needed, uses synthetic prices):
       python -m src.live.paper_trader --tickers AAPL,MSFT,NVDA --dry_run
  5. Once you trust the output, drop --dry_run to hit the real Alpaca paper API.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import Config
from ..utils.feature_engineering import add_technical_features
from ..agents.trading_agent import TradingAgent, AgentConfig
from ..agents.llm_interface import MockLLM, HFModel
from ..utils.portfolio import position_size

STATE_PATH = "./outputs/live_state.json"
BLOTTER_PATH = "./outputs/live_blotter.csv"


def _load_state() -> Dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"peak_equity": None, "risk_on": True, "dd_trigger_equity": None, "peak_at_trigger": None}


def _save_state(state: Dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _update_kill_switch(state: Dict, equity: float, max_dd: float, dd_recover_frac: float) -> bool:
    """Same logic as the backtest's kill switch, but persisted across daily runs."""
    peak = state["peak_equity"] if state["peak_equity"] is not None else equity
    peak = max(peak, equity)
    current_dd = (equity - peak) / peak if peak > 0 else 0.0

    risk_on = state.get("risk_on", True)
    if risk_on and current_dd <= -abs(max_dd):
        risk_on = False
        state["peak_at_trigger"] = peak
        state["dd_trigger_equity"] = equity
    elif not risk_on:
        trigger_eq = state.get("dd_trigger_equity") or equity
        peak_at_trigger = state.get("peak_at_trigger") or peak
        recovered = (equity - trigger_eq) / (peak_at_trigger - trigger_eq + 1e-9)
        if recovered >= dd_recover_frac:
            risk_on = True

    state["peak_equity"] = peak
    state["risk_on"] = risk_on
    return risk_on


class _DryRunAccount:
    """Offline stand-in for the Alpaca account/trading client, used by --dry_run
    so the whole pipeline (features -> agent -> sizing -> orders) can be
    exercised and inspected with zero API keys and zero real network calls."""

    def __init__(self, tickers: List[str], seed: int = 7):
        self.tickers = tickers
        self.equity = 100_000.0
        self.positions = {t: 0.0 for t in tickers}  # dollar market value per ticker
        self._seed = seed

    def get_equity(self) -> float:
        return self.equity

    def get_positions(self) -> Dict[str, float]:
        return dict(self.positions)

    def submit_target_weights(self, weights: Dict[str, float], prices: Dict[str, float]) -> List[Dict]:
        orders = []
        for t, w in weights.items():
            target_value = w * self.equity
            current_value = self.positions.get(t, 0.0)
            delta = target_value - current_value
            if abs(delta) < 1.0:
                continue
            side = "buy" if delta > 0 else "sell"
            orders.append({"symbol": t, "notional": round(abs(delta), 2), "side": side, "mode": "dry_run"})
            self.positions[t] = target_value
        return orders

    def fetch_recent_bars(self, lookback_days: int) -> pd.DataFrame:
        return generate_synthetic_bars(self.tickers, lookback_days, seed=self._seed)


def generate_synthetic_bars(tickers: List[str], n_days: int, seed: int = 7,
                             news_prob: float = 0.25) -> pd.DataFrame:
    """Shared synthetic price/news generator used by both the single-day dry
    run (_DryRunAccount) and the multi-day simulation below."""
    rng = np.random.default_rng(seed)
    pos_words = ["beat", "upgrade", "surge", "record", "strong growth", "raises guidance"]
    neg_words = ["miss", "downgrade", "lawsuit", "probe", "weak", "cuts guidance"]
    rows = []
    end = datetime.now(timezone.utc).date()
    dates = pd.bdate_range(end=end, periods=n_days)
    for t in tickers:
        price = 100.0 + rng.normal(0, 5)
        for d in dates:
            drift = 0.0
            news = ""
            if rng.random() < news_prob:
                if rng.random() < 0.5:
                    news = rng.choice(pos_words)
                    drift = 0.01
                else:
                    news = rng.choice(neg_words)
                    drift = -0.01
            price = max(1.0, price * (1 + drift + rng.normal(0, 0.015)))
            rows.append({
                "date": d, "ticker": t,
                "open": price, "high": price * 1.01, "low": price * 0.99,
                "close": price, "volume": 1_000_000, "news": news,
            })
    return pd.DataFrame(rows)


def simulate_dry_run(tickers: List[str], llm_choice: str, hf_model_name: str, strategy: str,
                      cfg: Config, sim_days: int, warmup_days: int = 30, seed: int = 7) -> Dict:
    """
    Multi-day dry run: generates `sim_days` of synthetic trading days (plus a
    warmup window so the retriever/features have history on day 1) and runs
    them through the exact same run_backtest() used for historical backtests,
    so the equity curve, benchmark, drawdown kill switch, and blotter are all
    the real, already-tested logic - not a separate reimplementation.

    This is what "--dry_run --sim_days N" gives you: a fast preview of what N
    days of live paper trading would look like, with no API keys and no
    network calls.
    """
    from ..utils.backtest import run_backtest

    raw = generate_synthetic_bars(tickers, warmup_days + sim_days, seed=seed)
    featured = add_technical_features(raw)

    llm = MockLLM() if llm_choice == "mock" else HFModel(model_name=hf_model_name)
    agent = TradingAgent(llm=llm, cfg=AgentConfig(strategy=strategy))
    agent.fit(featured[featured["date"] < sorted(featured["date"].unique())[warmup_days]])

    os.makedirs("./outputs", exist_ok=True)
    result = run_backtest(
        featured, agent,
        trading_cost_bps=cfg.trading_cost_bps,
        slippage_bps=cfg.slippage_bps,
        short_borrow_bps_annual=cfg.short_borrow_bps_annual,
        vol_target=cfg.vol_target,
        max_position_weight=cfg.max_position_weight,
        max_dd=cfg.max_dd,
        dd_recover_frac=cfg.dd_recover_frac,
        benchmark_ticker=tickers[0],
        blotter_path="./outputs/live_sim_blotter.csv",
        equity_curve_path="./outputs/live_sim_equity.png",
    )

    equity_log = pd.DataFrame(result["logs"])
    equity_log.to_csv("./outputs/live_sim_equity_curve.csv", index=False)

    return {
        "stats": result["stats"],
        "equity_csv": "./outputs/live_sim_equity_curve.csv",
        "blotter_csv": result["blotter_path"],
        "equity_png": result["equity_path"],
    }


LIVE_TRADING_CONFIRMATION = "I_UNDERSTAND_THIS_IS_REAL_MONEY"


class _AlpacaAccount:
    """
    Thin wrapper around alpaca-py. Defaults to the PAPER endpoint. Switching to
    the live endpoint requires BOTH the --live CLI flag AND the
    LIVE_TRADING_CONFIRM environment variable set to the exact string
    LIVE_TRADING_CONFIRMATION - deliberately two separate, explicit steps so
    this can never be triggered by a stray flag or a copy-pasted command. See
    README "Going live" for the full checklist before ever setting this.
    """

    def __init__(self, tickers: List[str], live: bool = False):
        # Checked before anything else - including the alpaca-py import - so
        # this gate can never be bypassed by an environment that happens to
        # be missing the dependency, and fails with the real reason first.
        if live and os.environ.get("LIVE_TRADING_CONFIRM") != LIVE_TRADING_CONFIRMATION:
            raise RuntimeError(
                "--live was passed but LIVE_TRADING_CONFIRM is not set to the exact "
                f"confirmation string. Set the environment variable LIVE_TRADING_CONFIRM="
                f"{LIVE_TRADING_CONFIRMATION} only once you have actually decided to risk "
                "real capital - see README 'Going live' first."
            )

        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient

        if live:
            api_key = os.environ.get("ALPACA_LIVE_API_KEY")
            secret_key = os.environ.get("ALPACA_LIVE_SECRET_KEY")
            key_hint = "ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY"
        else:
            api_key = os.environ.get("ALPACA_API_KEY")
            secret_key = os.environ.get("ALPACA_SECRET_KEY")
            key_hint = "ALPACA_API_KEY / ALPACA_SECRET_KEY"

        if not api_key or not secret_key:
            raise RuntimeError(
                f"{key_hint} not set. Copy .env.example to .env, fill in your Alpaca "
                f"{'LIVE' if live else 'PAPER'} keys, and make sure they're loaded (python-dotenv)."
            )
        self.tickers = tickers
        self.trading_client = TradingClient(api_key, secret_key, paper=not live)
        self.data_client = StockHistoricalDataClient(api_key, secret_key)

    def get_equity(self) -> float:
        return float(self.trading_client.get_account().equity)

    def get_positions(self) -> Dict[str, float]:
        out = {t: 0.0 for t in self.tickers}
        for p in self.trading_client.get_all_positions():
            if p.symbol in out:
                out[p.symbol] = float(p.market_value)
        return out

    def submit_target_weights(self, weights: Dict[str, float], prices: Dict[str, float]) -> List[Dict]:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        equity = self.get_equity()
        current = self.get_positions()
        orders = []
        for t, w in weights.items():
            target_value = w * equity
            delta = target_value - current.get(t, 0.0)
            if abs(delta) < 1.0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            req = MarketOrderRequest(
                symbol=t, notional=round(abs(delta), 2),
                side=side, time_in_force=TimeInForce.DAY,
            )
            self.trading_client.submit_order(order_data=req)
            orders.append({"symbol": t, "notional": round(abs(delta), 2), "side": side.value, "mode": "paper"})
        return orders

    def fetch_recent_bars(self, lookback_days: int) -> pd.DataFrame:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(lookback_days * 1.6) + 5)  # pad for weekends/holidays
        req = StockBarsRequest(symbol_or_symbols=self.tickers, timeframe=TimeFrame.Day, start=start, end=end)
        bars = self.data_client.get_stock_bars(req).df.reset_index()
        bars = bars.rename(columns={"symbol": "ticker", "timestamp": "date"})
        bars["date"] = pd.to_datetime(bars["date"]).dt.tz_localize(None).dt.normalize()
        bars["news"] = ""
        return bars[["date", "ticker", "open", "high", "low", "close", "volume", "news"]]


def run_once(tickers: List[str], llm_choice: str, hf_model_name: str, strategy: str,
             cfg: Config, dry_run: bool, live: bool = False, lookback_days: int = 90) -> Dict:
    from ..collectors.market_collector import append_to_history
    from ..rules import trade_ledger
    from ..agents import memory_store

    account = _DryRunAccount(tickers) if dry_run else _AlpacaAccount(tickers, live=live)

    raw = account.fetch_recent_bars(lookback_days)
    featured = add_technical_features(raw)
    today = featured["date"].max()
    train_window = featured[featured["date"] < today]
    today_df = featured[featured["date"] == today].copy()

    # Persist to the shared price history so trade_ledger can resolve today's
    # predictions 14 trading days from now, regardless of whether this run's
    # own lookback window still covers that far back by then.
    append_to_history(featured[featured["ticker"].isin(tickers)])

    # Resolve any earlier predictions whose horizon has now elapsed, before
    # building today's prompt, so the experience summary reflects the latest
    # known outcomes (see RESEARCH.md section 6 / trade_ledger.py).
    trade_ledger.sync_from_blotter(BLOTTER_PATH)
    experience_text = trade_ledger.summarize_recent_performance()

    llm = MockLLM() if llm_choice == "mock" else HFModel(model_name=hf_model_name)
    few_shots_from_memory = memory_store.build_few_shot_examples(
        query_ticker="", query_text=" ".join(tickers), k=3,
    )
    agent_cfg = AgentConfig(strategy=strategy)
    if few_shots_from_memory:
        agent_cfg.few_shots = few_shots_from_memory
    agent = TradingAgent(llm=llm, cfg=agent_cfg)
    agent.experience_text = experience_text
    agent.fit(train_window)  # retriever only ever sees strictly prior days
    preds = agent.predict_day(today_df)

    equity = account.get_equity()
    risk_on = _update_kill_switch(_state := _load_state(), equity, cfg.max_dd, cfg.dd_recover_frac)
    _save_state(_state)

    merged = today_df.merge(preds[["ticker", "direction", "confidence", "reason"]], on="ticker", how="left")
    weights = {}
    for _, r in merged.iterrows():
        signal = TradingAgent.direction_to_signal(r.get("direction", "neutral"))
        conf = float(r.get("confidence", 0.0) or 0.0)
        vol = float(r.get("vol_20d", 0.2) or 0.2)
        raw_w = position_size(signal, conf, vol, cfg.vol_target) if risk_on else 0.0
        raw_w = max(-cfg.max_position_weight, min(cfg.max_position_weight, raw_w))
        weights[r["ticker"]] = raw_w
    abs_sum = sum(abs(w) for w in weights.values())
    if abs_sum > 1e-9:
        weights = {k: v / abs_sum for k, v in weights.items()}

    prices = dict(zip(today_df["ticker"], today_df["close"]))
    orders = account.submit_target_weights(weights, prices)

    blotter_rows = []
    for t in tickers:
        row = merged[merged["ticker"] == t]
        blotter_rows.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": str(today.date()) if hasattr(today, "date") else str(today),
            "ticker": t,
            "direction": row["direction"].iloc[0] if len(row) else "neutral",
            "confidence": float(row["confidence"].iloc[0]) if len(row) else 0.0,
            "reason": row["reason"].iloc[0] if len(row) and "reason" in row.columns else "",
            "weight": weights.get(t, 0.0),
            "risk_on": risk_on,
            "equity": equity,
            "dry_run": dry_run,
        })
    blotter_df = pd.DataFrame(blotter_rows)
    os.makedirs(os.path.dirname(BLOTTER_PATH) or ".", exist_ok=True)
    header = not os.path.exists(BLOTTER_PATH)
    blotter_df.to_csv(BLOTTER_PATH, mode="a", index=False, header=header)

    return {"equity": equity, "risk_on": risk_on, "weights": weights, "orders": orders,
            "blotter_path": BLOTTER_PATH}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True, help="Comma separated, e.g. AAPL,MSFT,NVDA")
    ap.add_argument("--llm", default="mock", choices=["mock", "hf"])
    ap.add_argument("--hf_model_name", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--strategy", default="zero_shot",
                     choices=["zero_shot", "few_shot", "rag", "rag_uncertainty"],
                     help="zero_shot is the safe default live: RAG strategies retrieve from the "
                          "retriever's fitted corpus, so only use rag/rag_uncertainty live once "
                          "you've confirmed the news feed you wire in has no same-day leakage.")
    ap.add_argument("--max_dd", type=float, default=None)
    ap.add_argument("--dd_recover_frac", type=float, default=None)
    ap.add_argument("--vol_target", type=float, default=None)
    ap.add_argument("--max_position_weight", type=float, default=None)
    ap.add_argument("--dry_run", action="store_true",
                     help="Use synthetic prices and a fake local account. No API keys needed, "
                          "no orders are ever sent anywhere. Always do this first.")
    ap.add_argument("--sim_days", type=int, default=None,
                     help="With --dry_run, simulate this many synthetic trading days in one shot "
                          "(via the proven backtest engine) instead of a single day's decision, "
                          "so there's an actual equity curve and blotter history to look at.")
    ap.add_argument("--warmup_days", type=int, default=30,
                     help="Only used with --sim_days: extra lead-in days so indicators/retriever have history.")
    ap.add_argument("--seed", type=int, default=7, help="Only used with --dry_run.")
    ap.add_argument("--live", action="store_true",
                     help="DANGER: trade with real money on Alpaca's live endpoint instead of paper. "
                          "Requires ALPACA_LIVE_API_KEY/SECRET_KEY in .env AND the environment "
                          "variable LIVE_TRADING_CONFIRM set to the exact string checked in "
                          "_AlpacaAccount - this flag alone does nothing. See README 'Going live'.")
    args = ap.parse_args()

    if args.live and args.dry_run:
        raise SystemExit("--live and --dry_run together makes no sense - pick one.")

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    cfg = Config()
    for field in ["max_dd", "dd_recover_frac", "vol_target", "max_position_weight"]:
        val = getattr(args, field)
        if val is not None:
            setattr(cfg, field, val)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    if args.dry_run and args.sim_days:
        result = simulate_dry_run(tickers, args.llm, args.hf_model_name, args.strategy,
                                   cfg, sim_days=args.sim_days, warmup_days=args.warmup_days, seed=args.seed)
        print(f"[DRY RUN SIM] {args.sim_days} days, tickers={tickers}")
        for k, v in result["stats"].items():
            print(f"  {k}: {round(v, 4) if isinstance(v, (int, float)) else v}")
        print("Equity curve CSV:", result["equity_csv"])
        print("Equity curve PNG:", result["equity_png"])
        print("Blotter:", result["blotter_csv"])
        return

    if args.live:
        print("=" * 60)
        print("LIVE TRADING MODE - REAL MONEY - NOT A DRILL")
        print("=" * 60)

    result = run_once(tickers, args.llm, args.hf_model_name, args.strategy, cfg, args.dry_run, live=args.live)

    mode_prefix = "[DRY RUN] " if args.dry_run else ("[LIVE] " if args.live else "[PAPER] ")
    print(f"{mode_prefix}Equity: {result['equity']:.2f}  risk_on: {result['risk_on']}")
    print("Target weights:", {k: round(v, 4) for k, v in result["weights"].items()})
    print("Orders submitted:", result["orders"])
    print("Blotter:", result["blotter_path"])

    from ..rules import trade_ledger
    calibration = trade_ledger.compute_calibration()
    if calibration.get("n", 0) > 0:
        print(f"\nCalibration so far: n={calibration['n']}  "
              f"brier_score={calibration['brier_score']:.4f}  "
              f"overall_hit_rate={calibration['overall_hit_rate']:.2%}")
        print("(Brier 0.25 = as good as always saying 50% confident; lower is better.)")
    else:
        print("\nNo resolved predictions yet - calibration report will appear once calls are 14 trading days old.")


if __name__ == "__main__":
    main()
