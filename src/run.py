# src/run.py
import argparse, json, random
import numpy as np

from .config import Config
from .utils.data_loader import load_data, time_split
from .utils.backtest import run_backtest
from .utils.helper import ensure_dir, save_samples, train_sft_if_needed, train_peft_if_needed
from .agents.trading_agent import TradingAgent, AgentConfig
from .agents.llm_interface import MockLLM, HFModel

def build_runners(args, cfg: Config):
    """
    Returns a list of (name, llm) pairs to backtest and compare.
    - "mock": always included, zero cost, useful as a sanity baseline.
    - "hf": a real local instruct model doing zero/few-shot/RAG prompting, no
      training required. This is the default path for actually getting a
      non-heuristic signal without a GPU training job.
    - "sft" / "peft": only included if --do_train was run (or checkpoints
      already exist from a prior run), loading the fine-tuned checkpoints.
    """
    runners = [("mock", MockLLM())]

    if args.llm in ("hf", "all"):
        runners.append(("hf", HFModel(model_name=args.hf_model_name)))

    if args.do_train or args.use_existing_checkpoints:
        import os
        sft_ckpt = "./outputs/sft_ckpt"
        peft_ckpt = "./outputs/peft_lora_ckpt"

        if args.do_train:
            ensure_dir("./outputs/datasets")
            train_jsonl = "./outputs/datasets/train.jsonl"
            valid_jsonl = "./outputs/datasets/valid.jsonl"
            save_samples(args.train_df, train_jsonl)
            save_samples(args.valid_df, valid_jsonl)
            train_sft_if_needed(train_jsonl, valid_jsonl, args.base_model, sft_ckpt)
            train_peft_if_needed(train_jsonl, valid_jsonl, args.base_model, peft_ckpt)

        if os.path.isdir(sft_ckpt) and os.path.exists(os.path.join(sft_ckpt, "config.json")):
            runners.append(("sft", HFModel(model_name=sft_ckpt)))
        if os.path.isdir(peft_ckpt) and os.path.exists(os.path.join(peft_ckpt, "adapter_config.json")):
            runners.append(("peft", HFModel(model_name=peft_ckpt)))

    return runners

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--base_model', default="mistralai/Mistral-7B-Instruct-v0.3",
                     help="Base model used only for --do_train SFT/PEFT fine-tuning.")
    ap.add_argument('--llm', default='hf', choices=['mock', 'hf', 'all'],
                     help="Which non-trained runner(s) to include alongside mock.")
    ap.add_argument('--hf_model_name', default="Qwen/Qwen2.5-1.5B-Instruct",
                     help="Hub name or local path for the --llm hf runner. Pick something CPU-sized if you have no GPU.")
    ap.add_argument('--do_train', action='store_true', help="Also run SFT + PEFT training and backtest those checkpoints.")
    ap.add_argument('--use_existing_checkpoints', action='store_true',
                     help="Include sft/peft runners if checkpoints already exist under ./outputs, without retraining.")
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--strategy', default='rag_uncertainty',
                     choices=['zero_shot', 'few_shot', 'rag', 'rag_uncertainty'])
    ap.add_argument('--n_samples', type=int, default=5)
    ap.add_argument('--temperature', type=float, default=0.6)

    # Risk / cost overrides, otherwise taken from Config defaults.
    ap.add_argument('--trading_cost_bps', type=float, default=None)
    ap.add_argument('--slippage_bps', type=float, default=None)
    ap.add_argument('--short_borrow_bps', type=float, default=None)
    ap.add_argument('--vol_target', type=float, default=None)
    ap.add_argument('--max_position_weight', type=float, default=None)
    ap.add_argument('--max_dd', type=float, default=None)
    ap.add_argument('--dd_recover_frac', type=float, default=None)
    ap.add_argument('--benchmark_ticker', default=None)

    args = ap.parse_args()

    random.seed(args.seed); np.random.seed(args.seed)
    cfg = Config()
    for field in ["trading_cost_bps", "slippage_bps", "vol_target",
                  "max_position_weight", "max_dd", "dd_recover_frac", "benchmark_ticker"]:
        val = getattr(args, field, None)
        if val is not None:
            setattr(cfg, field, val)
    if args.short_borrow_bps is not None:
        cfg.short_borrow_bps_annual = args.short_borrow_bps

    # 1) Data & split
    df = load_data(args.data, date_col=cfg.date_col, ticker_col=cfg.ticker_col)
    train, valid, test = time_split(df, start=args.start, end=args.end)
    args.train_df, args.valid_df = train, valid
    print("Train df shape:", train.shape)
    print(train.head())

    # 2) Build runners to compare
    runners = build_runners(args, cfg)

    # 3) Backtest each
    ensure_dir("./outputs")
    comparison = {}
    for name, llm in runners:
        print(f"[Backtest] Running strategy={args.strategy} with model={name}")
        agent = TradingAgent(
            llm=llm,
            cfg=AgentConfig(strategy=args.strategy, n_samples=args.n_samples, temperature=args.temperature)
        )
        agent.fit(train)

        backtest_kwargs = dict(
            trading_cost_bps=cfg.trading_cost_bps,
            slippage_bps=cfg.slippage_bps,
            short_borrow_bps_annual=cfg.short_borrow_bps_annual,
            vol_target=cfg.vol_target,
            max_position_weight=cfg.max_position_weight,
            max_dd=cfg.max_dd,
            dd_recover_frac=cfg.dd_recover_frac,
            benchmark_ticker=cfg.benchmark_ticker,
        )
        result_valid = run_backtest(
            valid, agent,
            blotter_path=f"./outputs/blotter_valid_{name}.csv",
            equity_curve_path=f"./outputs/equity_curve_valid_{name}.png",
            **backtest_kwargs,
        )
        result_test = run_backtest(
            test, agent,
            blotter_path=f"./outputs/blotter_test_{name}.csv",
            equity_curve_path=f"./outputs/equity_curve_test_{name}.png",
            **backtest_kwargs,
        )

        comparison[name] = {
            "valid": result_valid["stats"],
            "test": result_test["stats"],
            "equity_valid_png": f"./outputs/equity_curve_valid_{name}.png",
            "equity_test_png": f"./outputs/equity_curve_test_{name}.png",
            "blotter_valid_csv": result_valid["blotter_path"],
            "blotter_test_csv": result_test["blotter_path"],
        }

    with open("./outputs/results.json", "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)

    def fmt(s): return {k: (round(v, 4) if isinstance(v, (int, float)) else v) for k, v in s.items()}
    print("\n=== Comparison (VALID) ===")
    for k, v in comparison.items():
        print(k, fmt(v["valid"]))
    print("\n=== Comparison (TEST) ===")
    for k, v in comparison.items():
        print(k, fmt(v["test"]))
    print("\nSaved: ./outputs/results.json, equity curves, and blotter CSVs under ./outputs/")

if __name__ == "__main__":
    main()
