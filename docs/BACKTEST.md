# Backtesting (Phase 4)

Code: `src/quantsport/backtest/`. `engine.py` simulates one strategy;
`report.py` runs the validation-then-test protocol for every model.

A backtest result is a historical simulation. It is reported separately from
out-of-sample forecast accuracy (Phase 2) and from live paper trading
(Phase 6 onward), and must never be presented as either.

## What the simulated bettor knows

| Used to choose and size a bet | Used only afterwards |
|---|---|
| Stored walk-forward forecast (model fitted on matches before that day) | Match result (settlement) |
| Pre-closing price at the chosen bookmaker | Closing consensus (CLV) |
| Bankroll at the start of the day | |

A test flips every result and closing price and confirms the chosen bets and
stakes do not change.

## Rules

- **Entry:** bet a selection when `EV = p * price - 1 > min_ev` and the price
  is within `[min_odds, max_odds]`.
- **One bet per match and market:** the selection with the highest EV.
- **Timing:** bets are grouped by match date. A day's stakes are sized from
  the bankroll at the start of that day and settled at its end. Total stakes
  for a day are scaled down if they would exceed the bankroll.
- **Missing prices:** a forecast with no price at the chosen source is not
  bet. Coverage is reported; nothing is filled in.
- **Price source:** one named bookmaker (default Bet365, the only individual
  bookmaker with Over/Under 2.5 prices in every main-league season), or
  `best` across individual bookmakers. `best` is optimistic: it assumes an
  account at every bookmaker and that the prices coexisted.
- **Costs:** `commission` is taken from winnings. Bookmaker margin is already
  inside the prices. Default commission is 0.

## Staking

| Name | Stake |
|---|---|
| `flat` | `stake_pct` x initial bankroll |
| `percent` | `stake_pct` x current bankroll |
| `kelly` | `kelly_fraction x (p*o - 1)/(o - 1)` x current bankroll, capped at `max_stake_pct` |

Kelly staking trusts the model's probability. Phase 2 and 3 showed those
probabilities are worse than the market's, so Kelly results here mostly show
how fast overconfidence loses money. Uncertainty-adjusted staking is Phase 6.

## Metrics

| Metric | Definition |
|---|---|
| Bets, wins, losses | counts of settled bets |
| Staked | sum of stakes |
| Profit | sum of settled profit and loss |
| ROI (yield) | profit / staked |
| ROI interval | 95% bootstrap over matches (5,000 resamples, fixed seed) |
| Win rate | wins / bets |
| Mean odds | average price taken |
| Mean CLV | average of `price x closing fair probability - 1` |
| Max drawdown | largest fall of end-of-day bankroll from its running peak, as a fraction of the peak |
| Verdict | "profitable beyond chance" if the ROI interval is entirely above 0, "losing beyond chance" if entirely below, otherwise "not distinguishable from break-even"; "insufficient sample" under 30 bets |

## Protocol against over-fitting

| Split | Data | Use |
|---|---|---|
| Validation | previous season (2025/26; Norway 2025) | choose the EV threshold from a fixed grid of 0, 5, 10, 15% |
| Test | current season (2026/27; Norway 2026) | each model run once with its chosen threshold |

The protocol uses flat stakes of 0.25% of the starting bankroll. The first run
used 1%, and several losing strategies ran out of money part-way through the
season; their bet counts were cut short and ROI became dependent on the order
of results. The smaller stake avoids that, and every summary now reports
`skipped_after_ruin`, the qualifying bets that could not be placed because
the bankroll had reached zero. This was a correction to how results are
measured, made after seeing a first set of results on both splits.

The threshold with the highest validation ROI and at least 50 bets is carried
forward. Sensitivity runs on the test season are printed for information and
must not be used to choose settings.

## Bias controls

- **Look-ahead:** forecasts come from the insert-only walk-forward store;
  prices are the pre-closing snapshot.
- **Survivorship:** the data contains every team that played, including
  relegated ones. Matches the models could not forecast are counted in
  coverage, not silently dropped.
- **Selection:** the grid is fixed in code and small; the test season is run
  once per model.

## Limitations

- Pre-closing prices have no timestamp. The backtest assumes the recorded
  price was obtainable; that is not verified.
- No stake limits, account restrictions, or price slippage.
- Validation forecasts for the previous season only start once a league has
  100 earlier matches in the database, so the first third of that season is
  missing, and those models were trained on very little history.
- Switzerland and Norway cannot be backtested: no pre-closing prices, and no
  Over/Under prices at all.
- One and a third seasons is a small sample. Wide intervals are expected.

## Commands

```
python -m quantsport walk-forward --season previous   # validation forecasts
python -m quantsport backtest --model dixon_coles --market OU2.5 --split validation --min-ev 0.05
python -m quantsport backtest-report
```
