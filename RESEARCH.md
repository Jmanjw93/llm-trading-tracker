# Research notes: what others have found, and what we changed because of it

This is a record of external research (academic papers, GitHub projects) that
actually changed something in this repo, with citations. It exists so a rule
or code change can be traced back to real evidence instead of vibes — same
spirit as `RULES.md`'s changelog, one level up.

**Read this if:** you want to know why a rule exists, why a number was picked,
or whether a claim this repo makes about itself is credible.

---

## 1. Does Reddit/WSB sentiment actually predict returns?

Short answer: **mixed, mostly negative-to-contrarian, and stock-specific.**
This directly affects how much weight `flag_reddit_momentum` (R4) should get.

- A ScienceDirect study on WSB herding attention finds sentiment behaves as a
  **contrarian** predictor — heavier bullish chatter tends to precede *weaker*
  forward returns, not stronger ones. ("Dumb money? Social network attention
  herding, sentiment, and markets")
- An Oxford thesis ("Is there good investment advice on r/wallstreetbets?")
  concludes WSB activity is **not predictive** of future returns for most
  stocks.
- A meme-stock study finds predictive power exists but is **horizon- and
  source-specific**: Google search sentiment forecasts 3–7 days out, Bloomberg
  news sentiment 7–14 days out, Bloomberg Twitter sentiment mostly same-day —
  notably, none of these are *Reddit* sentiment directly.
- An RIT thesis finds Reddit sentiment Granger-causes GME and AMC returns at
  specific lags — i.e. real effects exist, but concentrated in a handful of
  genuinely meme-driven names, not a general-purpose signal.

**What we did about it:** `rules_engine.py`'s R4 was already direction-agnostic
by design — it flags *attention* (`mention_count >= 3`), not a bullish/bearish
call, and the 14-trading-day resolution in `resolve_outcomes()` measures
whatever the realized return actually was, positive or negative. That was the
right call before this research and is now evidence-backed rather than
accidental: if R4 turns out contrarian for our tickers, `weekly_rule_review()`
will show a hit rate below 50% and the existing down-weight process handles it
correctly without any code change. **Do not** "fix" R4 by assuming Reddit
mentions mean "buy" — the literature says that assumption is more often wrong
than right.

Sources:
[Dumb money? (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2405918825000212) ·
[Is there good investment advice on r/wallstreetbets? (Oxford)](https://ora.ox.ac.uk/objects/uuid:6f3c53d3-f0d6-4232-b3cf-bf1696b200f9/files/dsf268587w) ·
[Should You Take Investment Advice From WallStreetBets? (arXiv 2105.02728)](https://arxiv.org/pdf/2105.02728) ·
[Sentiment, social media and meme stock return predictability](https://www.researchgate.net/publication/401274381_Sentiment_social_media_and_meme_stock_return_predictability) ·
[RIT thesis: Correlating WSB sentiment with the market](https://repository.rit.edu/theses/11061/)

---

## 2. FinBERT and sentiment scoring

`reddit_collector.py` currently scores "legitimacy" with pure engagement
metrics (score, upvote ratio) and `rules_engine.py` counts mentions — neither
reads *what the post actually says*. FinBERT (ProsusAI, BERT fine-tuned on the
Financial PhraseBank) is the standard open-source model for this: a free,
small, well-established classifier for bullish/bearish/neutral financial text.

Caveat found in the research itself: the FinBERT authors' own target is
broader than clean prediction, and none of the sources surfaced benchmark
evidence that FinBERT sentiment *reliably improves returns* on its own — it's
a better *text-to-sentiment* tool than the current keyword lists, not a proven
trading edge by itself.

**What we did about it:** not yet implemented. This is a reasonable next step
— replacing `MockLLM`'s `POS`/`NEG` keyword lists and adding a sentiment score
to each Reddit post — but it adds a real dependency (another HF model) and
per the point above isn't evidence of profitability by itself, so it should go
in as a *feature*, evaluated the same way every other rule is (hit rate over
resolved flags), not trusted on priors.

Sources:
[ProsusAI/finbert](https://github.com/ProsusAI/finbert) ·
[FinBERT-LSTM (arXiv 2211.07392)](https://arxiv.org/pdf/2211.07392) ·
[Financial Sentiment Analysis Using FinBERT (arXiv 2306.02136)](https://arxiv.org/html/2306.02136v3)

---

## 3. GitHub ecosystem survey

Searched via `gh search repos "llm trading agent" --sort stars`. Most
relevant by actual substance (not just star count):

| Repo | Why it matters here |
|---|---|
| [`pipiku915/FinMem-LLM-StockTrading`](https://github.com/pipiku915/FinMem-LLM-StockTrading) (972★, [arXiv 2311.13743](https://arxiv.org/abs/2311.13743)) | Published, peer-reviewed-adjacent (ICLR workshop) architecture: a **layered memory** module with importance-weighted decay and an adjustable "cognitive span", instead of our flat TF-IDF retriever. Noted as a future direction below, not implemented this round. |
| [`bettyguo/awesome-llm-trading-agents`](https://github.com/bettyguo/awesome-llm-trading-agents) + its [`docs/methodology.md`](https://github.com/bettyguo/awesome-llm-trading-agents/blob/main/docs/methodology.md) | **The single most load-bearing find of this research pass.** A rigor checklist for evaluating any LLM trading claim, including our own. Summarized and applied in §4 below. |
| [`bettyguo/agent-backtest-lab`](https://github.com/bettyguo/agent-backtest-lab) | Tooling for Deflated/Probabilistic Sharpe Ratio and backtest-overfitting probability — the statistical machinery behind §4's multiple-testing warning. Worth adopting if/when we start reporting Sharpe numbers we actually want to defend. |
| [`HephaestLab/TraderHarness`](https://github.com/HephaestLab/TraderHarness) | "Leakage-resistant backtesting, deterministic replay" for LLM trading agents specifically — same concern as our own `agent.fit(train_window)` leakage guard in `paper_trader.py`, independently arrived at by someone else. Confirms that guard was the right instinct. |

---

## 4. Self-audit: applying the methodology checklist to *this repo*

Running `awesome-llm-trading-agents`'s "five questions" against our own
system, honestly:

| Question | Our answer | Verdict |
|---|---|---|
| Q1. Does the eval window post-date the backbone LLM's training cutoff? | **No, not necessarily.** `HFModel` defaults to `Qwen/Qwen2.5-1.5B-Instruct` with an unpinned revision. Any backtest run on historical dates the model may have seen during pre-training risks measuring memorization, not prediction. | **Unresolved — see action below.** |
| Q2. Trial count / deflated Sharpe? | No. We've already tuned confluence thresholds (R1–R5) once by hand. `RULES.md`'s changelog is a start toward pre-registration discipline but isn't a DSR. | **Partial — be skeptical of our own hit-rate numbers until `agent-backtest-lab`-style correction is applied.** |
| Q3. Baseline includes buy-and-hold? | **Yes** — `backtest.py` already computes and reports `excess_annual_return` against a buy-and-hold benchmark. | **Pass.** |
| Q4. Transaction costs modeled? | **Yes** — fees + slippage + short borrow cost, not just gross returns. | **Pass.** |
| Q5. Universe and horizon large enough to be meaningful? | **No.** 10 tickers, and by Feb 16, 2027 we'll have ~66 trading days of history — well under the suggested floor of 50 names / 250 trading days. | **Fail — see action below.** |

### Actions taken because of this audit

1. **Expanded the default ticker universe** from 10 names to a ~50-name,
   recognizable-index-style list (large-cap Nasdaq-100/S&P names) in
   `scripts/daily_collect.py`, to move toward a statistically defensible
   universe size. See `DEFAULT_TICKERS`.
2. **Added a `revision` parameter to `HFModel`** (`src/agents/llm_interface.py`)
   so a specific model snapshot can be pinned instead of floating on whatever
   `Qwen/Qwen2.5-1.5B-Instruct` currently resolves to on the Hub — required for
   Q9's reproducibility bar and a prerequisite for ever reasoning about Q1
   cleanly (you can't check a cutoff against a model that silently changes).
3. **Added an explicit caveat to `RULES.md` and `PROGRESS.md`**: don't trust
   any backtest run on historical data as evidence the HF-backed strategy
   "works" — the only credible evaluation here is the paper-trading forward
   data collected from today onward, which by construction post-dates
   whatever the model already knew.
4. **Did not yet implement:** FinBERT sentiment scoring, FinMem-style layered
   memory, or DSR/CPCV tooling. These are real, reasonably scoped next steps,
   listed here so they don't get lost, not implemented this round to keep
   this change reviewable.

---

## 5. What Feb 16, 2027 should actually mean

Before this research pass, "collect data until Feb 16, 2027, then add real
money" read as a fixed date. Per §4 Q5, our sample size will likely still be
below the field's own credibility bar on that date. **Recommendation:** treat
Feb 16, 2027 as a scheduled *review* checkpoint — re-run the 5-question audit
above with real numbers — not an automatic go/no-go. This is now also
reflected in `PROGRESS.md`.
