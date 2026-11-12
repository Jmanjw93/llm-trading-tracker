import pandas as pd
import numpy as np
from typing import List
from .prompt import PROMPT_TEMPLATE

def clean_news_text(text: str) -> str:
    text = text.replace("\n"," ").replace("\t"," ")
    text = " ".join(text.split())
    return text  # safety cap

def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    # Works per ticker
    req = ["ticker","date","close"]
    for c in req:
        if c not in df.columns:
            df[c] = np.nan
    df = df.sort_values(["ticker","date"]).copy()

    def per_ticker(g: pd.DataFrame) -> pd.DataFrame:
        g = g.copy()
        g["ret_1d"] = g["close"].pct_change()
        g["ret_5d"] = g["close"].pct_change(5)
        g["vol_20d"] = g["ret_1d"].rolling(20).std() * np.sqrt(252)
        # RSI(14)
        delta = g["close"].diff()
        up = delta.clip(lower=0).rolling(14).mean()
        down = (-delta.clip(upper=0)).rolling(14).mean()
        rs = up / (down + 1e-9)
        g["rsi_14"] = 100 - 100/(1+rs)
        # fill
        for col in ["ret_1d","ret_5d","vol_20d","rsi_14"]:
            g[col] = g[col].replace([np.inf, -np.inf], np.nan).bfill().ffill()
        return g

    # Avoid groupby().apply(include_groups=...), which was removed in newer
    # pandas and behaves inconsistently across versions anyway; a plain loop
    # keeps the ticker column intact regardless of pandas version.
    parts = [per_ticker(g) for _, g in df.groupby("ticker", sort=False)]
    out = pd.concat(parts, ignore_index=True)
    return out

def build_prompt(
    row: pd.Series,
    context_docs: List[str] = None,
    use_rag: bool = True,
    few_shot_examples: List[str] = None,
    experience_text: str = None,
) -> str:
    if few_shot_examples:
        examples = "\n".join(f"- {ex}" for ex in few_shot_examples)
        few_shot_block = f"Examples of the expected input/output format:\n{examples}\n"
    else:
        few_shot_block = ""

    experience_block = f"{experience_text}\n" if experience_text else ""

    fundamentals = []
    if "pe" in row and not pd.isna(row["pe"]):
        fundamentals.append(f"PE={row['pe']:.2f}")
    if "roe" in row and not pd.isna(row["roe"]):
        fundamentals.append(f"ROE={row['roe']:.2f}")
    fundamentals_str = ", ".join(fundamentals) if fundamentals else "N/A"

    # —— 关键逻辑：可选 context 块 ——
    if use_rag and context_docs:
        ctx = "\n\n".join(context_docs)
        context_block = f"Context (may be noisy, use judgment):\n{ctx}\n"
    else:
        context_block = ""  # 不使用 RAG 时为空

    prompt = PROMPT_TEMPLATE.format(
        experience_block=experience_block,
        few_shot_block=few_shot_block,
        context_block=context_block,
        ticker=row.get("ticker", "N/A"),
        date=row.get("date"),
        close=row.get("close", "N/A"),
        ret_1d=row.get("ret_1d", "N/A"),
        ret_5d=row.get("ret_5d", "N/A"),
        vol_20d=row.get("vol_20d", "N/A"),
        rsi_14=row.get("rsi_14", "N/A"),
        fundamentals=fundamentals_str,
        news=row.get("news", ""),
    )
    return prompt
