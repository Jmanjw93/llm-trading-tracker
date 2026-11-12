# Rules: how this system is supposed to get smarter

This is the human-readable version of `src/rules/rules_engine.py`. If you
change one, change the other - they're meant to stay in sync. Every change to
an actual threshold gets a dated entry in the changelog at the bottom, with the
evidence that justified it. No silent tuning.

**Target date for real money: February 16, 2027.** Everything before that date
is data collection and rule validation. The rules below are the current best
guess, not settled fact - they only earn trust by surviving contact with
`weekly_rule_review()`'s actual hit-rate numbers.

## Signal rules (per ticker, per day)

| Rule | Trigger | Rationale |
|---|---|---|
| R1 - Volume spike | Volume z-score (vs. trailing 20-day) > 2.5 | Unusual volume is one of the more reliable "something is happening" signals; 2.5 sigma is a starting point, not a validated constant |
| R2 - Price gap | \|open - prior close\| / prior close > 3% | Large overnight gaps usually mean news priced in outside market hours |
| R3 - RSI extreme | RSI(14) < 25 or > 75 | Oversold/overbought extremes; a classic mean-reversion signal, included because it's cheap to compute and easy to falsify later |
| R4 - Reddit momentum | >= 3 posts today across r/wallstreetbets, r/stocks, r/options, r/investing mention the ticker (cashtag) AND clear the legitimacy bar (score + upvote ratio thresholds per subreddit, see `reddit_collector.py`) | Crowd attention is a noisy but sometimes-real signal; the legitimacy bar exists specifically to filter out low-effort hype posts, not to prove the post was right |

## R5 - Confluence (the actual "smarter" part)

**A ticker is only flagged as an anomaly candidate when at least 2 of
R1-R4 trigger on the same day.** Any single rule alone is treated as noise.
This is deliberate: each rule individually is a weak, cheap heuristic; the
reason to expect anything useful is that *independent* weak signals agreeing
is a stronger filter than any one of them tuned harder. `min_confluence=2` is
a starting parameter in `rules_engine.evaluate()`, open to revision once
there's enough resolved data to check it.

## Labeling: does a flag actually make money?

Every flagged ticker goes into `data/labeled/pending_flags.csv`. After
**14 trading days** (configurable, `horizon_trading_days`), its realized
close-to-close return over that window is computed and the flag moves to
`data/labeled/resolved_flags.csv` with `good_trade = realized_return > 0`.

This resolved file is the actual training signal:
- It is the source for few-shot examples fed into the LLM prompt (replacing
  the two generic hardcoded examples in `AgentConfig.few_shots`) once there
  are enough resolved flags to pick good ones from.
- Once there's a meaningful sample (order of dozens, not a handful), it's
  usable as real SFT/PEFT training data via `sft_train.py` / `peft_train_lora.py`,
  which previously had no real-world data to train on at all.
- It's what `weekly_rule_review()` uses to compute each rule's standalone
  hit rate among resolved flags, so thresholds can be revised with evidence
  instead of intuition.

## Weekly review process

Every 7 collection days, run `weekly_rule_review()` and look at:
- Each rule's hit rate (fraction of resolved flags where that rule
  participated AND the trade turned out positive) once it has >= 10 resolved
  observations.
- A rule sitting below 50% hit rate with >= 10 observations is a candidate to
  down-weight or retire - record the decision below with the actual numbers,
  don't just vibes-adjust it.

## Changelog

- **2026-11-12**: Initial ruleset (R1-R5) established. No resolved flags yet -
  all thresholds above are starting guesses pending real data. Confluence
  minimum set to 2 of 4 rules.
