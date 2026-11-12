from dataclasses import dataclass
from typing import Optional

@dataclass
class Config:
    date_col: str = "date"
    ticker_col: str = "ticker"
    price_cols: tuple = ("open", "high", "low", "close", "volume")
    news_col: str = "news"          # daily news text
    pe_col: str = "pe"              # example fundamental
    roe_col: str = "roe"            # example fundamental

    # Backtest params
    trading_cost_bps: float = 5.0   # flat commission/fee, round-trip, in basis points
    slippage_bps: float = 3.0       # extra cost per unit turnover to approximate bid/ask + market impact
    short_borrow_bps_annual: float = 50.0  # annualized borrow cost charged on short exposure only
    vol_target: float = 0.15        # annualized vol target
    max_dd: float = 0.25            # max drawdown cap; trading is suspended (flat) once breached
    dd_recover_frac: float = 0.5    # must recover this fraction of the drawdown before re-risking
    max_position_weight: float = 0.25  # cap on any single ticker's share of the risk budget
    benchmark_ticker: Optional[str] = None  # if set and present in the data, plot/report buy-and-hold for it
    seed: int = 42
