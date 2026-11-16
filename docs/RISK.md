# Risk management (Phase 6)

Code: `src/quantsport/risk/`. Everything here concerns hypothetical money.

## Stake sizing (`staking.py`)

With model probability `p`, decimal odds `o` and stake base `S`:

| Quantity | Definition |
|---|---|
| Full Kelly fraction | `k(p, o) = max(0, (p*o - 1) / (o - 1))` |
| Disagreement | standard deviation of the probability across the stored models |
| Model error | RMS gap between the model and the closing market's fair probability, measured on the validation season |
| Probability uncertainty | `sigma = sqrt(disagreement^2 + model_error^2)` |
| Conservative probability | `p_c = p - z * sigma` (default `z = 1`) |
| Uncertainty-adjusted stake | `kelly_fraction * k(p_c, o) * S` (default quarter Kelly) |
| Fixed-percentage stake | `stake_pct * S` |

A bet whose conservative probability no longer has positive expected value is
given a stake of zero: its edge is inside the model's own error.

### Stake base: no increases on short-term profit

`S = min(current bankroll, starting bankroll)`. Losses shrink stakes at once;
profits do not raise them. `S` may follow the bankroll upward only when both
hold:

1. at least `min_bets_to_scale` (500) settled bets, and
2. their mean closing line value is positive with a 95% interval above zero.

Profit is deliberately not part of this test. Exposure caps are also taken on
`S`, so they cannot grow on profit either.

### Limits and drawdown control

| Setting | Default | Meaning |
|---|---|---|
| `max_stake_pct` | 2% | one bet |
| `max_match_pct` | 3% | all bets on one match |
| `max_daily_pct` | 10% | all bets on one day |
| `max_open_pct` | 25% | all unsettled bets (paper trading) |
| `drawdown_reduce_pct` | 10% | below peak: stakes halved |
| `drawdown_halt_pct` | 25% | below peak: no new bets |

Limits are applied in that order by scaling stakes down. These defaults are
conventional values, not optimised ones.

## Monitoring (`monitoring.py`)

| Measure | Definition |
|---|---|
| Drawdown | fall of the bankroll from its running peak, as a share of the peak |
| Losing streak | longest and current run of consecutive losing bets |
| Expected longest losing streak | `log(n * p) / log(1 / (1 - p))` for `n` bets at win rate `p`; a streak near this is ordinary variance |
| Daily exposure | total staked on a day / bankroll at the start of that day |
| Concentration | Herfindahl index of stake shares by league, day or market; effective groups = 1 / H |
| Outcome correlation | correlation of outcome indicators (home win, draw, away win, over, under, both teams to score) within a match, from all finished matches |

## Simulation (`simulation.py`)

- **Replay:** the test season's historical bets are staked and settled day by
  day under each policy. A historical simulation, like the backtest.
- **Monte Carlo:** 5,000 alternative histories of the same bets. Each bet
  keeps its price and stake share; outcomes are redrawn with either the
  closing market's fair probability ("market is right") or the model's
  ("model is right"). Bets are drawn independently, which understates tail
  risk because same-match and same-day bets are correlated.

## Paper trading (`paper.py`)

A third ledger, separate from backtests and walk-forward evaluation.

```
python -m quantsport paper create --name main --bankroll 1000
python -m quantsport predict-upcoming      # store live forecasts first
python -m quantsport paper place --name main
python -m quantsport paper settle --name main
python -m quantsport paper status --name main
```

- A paper bet is created only from a **live** forecast and a pre-match price,
  is sized by the risk engine, and is refused once the match has started.
- Each bet records the price's status (`indicative` or `current`). With the
  present data source every price is `indicative`: not verified as obtainable.
- Entry fields are written once; only settlement fields change.
- `status` reports bankroll, open exposure, drawdown, streaks and the stake
  review.

## Limitations

- Paper trading has been tested only with synthetic fixtures. No real upcoming
  fixtures or live prices are available from the current source, so no real
  paper bets exist yet.
- The uncertainty estimate is a heuristic combination of model disagreement
  and validation error, not a posterior distribution.
- No stake limits, account restrictions or price slippage are modelled.
- Risk controls limit losses; they cannot create an edge that the models do
  not have.
