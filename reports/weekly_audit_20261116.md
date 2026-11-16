# Weekly quantitative audit, 16 November 2026

Generated 2026-11-16 00:12 UTC. Backtest, out-of-sample forecast and paper-trading results are reported separately and are never combined.

## Executive summary

- **Verdict:** There is no statistically defensible predictive advantage. Stakes should not be increased and operation should remain paper trading only.
- Problems: Model accuracy, Closing line value.
- Warnings: Betting strategy performance, Backtesting reliability, Potential overfitting.
- Insufficient observations for a verdict: none.

## Scorecard

| # | area | status | key figure |
|---|---|---|---|
| 1 | Data quality | OK | 43 successful and 0 failed ingestion runs in 7 days; newest result 7 days old |
| 2 | Model accuracy | Problem | 1X2 poisson: worse than the closing market; OU ml_random_forest: worse than the closing market |
| 3 | Probability calibration | OK | 1X2: ECE 0.0424; OU: ECE 0.0339 |
| 4 | Betting strategy performance | Warning | backtest ROI -11.2% on 453 bets (95% interval -25.1% to +3.5%): not distinguishable from break-even |
| 5 | Closing line value | Problem | mean CLV -3.37% (95% interval -4.3 to -2.42) on 453 bets |
| 6 | Model deterioration | OK | 1X2: 229 recent matches, OK; OU: 187 recent matches, OK |
| 7 | Financial risk | OK | max drawdown 14.11%, longest losing streak 13 (chance alone gives about 13.1) |
| 8 | Backtesting reliability | Warning | 100% of prices have no collection time; 59% of test-season matches could be bet |
| 9 | Potential overfitting | Warning | largest validation-to-test ROI drop 11.2 points |
| 10 | Recommended improvements | See list | 8 recommendations |

## 1. Data quality

**Status: OK.** 43 successful and 0 failed ingestion runs in 7 days; newest result 7 days old

- Ingestion runs in the last 7 days: 43 successful, 0 failed.
- Rows rejected by validation in the last 7 days: 0.
- Leagues with no result for more than 21 days: none (expected outside the season).

| league | last_match | days_old |
|---|---|---|
| D1 | 2026-11-08 | 8 |
| E0 | 2026-11-08 | 8 |
| I1 | 2026-11-08 | 8 |
| N1 | 2026-11-08 | 8 |
| NOR | 2026-11-09 | 7 |
| SP1 | 2026-11-08 | 8 |
| SWZ | 2026-11-08 | 8 |
| T1 | 2026-11-08 | 8 |

Coverage by league and season:

| league | season | finished | scheduled | shots_% | xg_% | 1X2_closing_% | OU2.5_pre_close_% |
|---|---|---|---|---|---|---|---|
| D1 | 2025/2026 | 306 | 0 | 100.0 | 0.0 | 100.0 | 100.0 |
| D1 | 2026/2027 | 81 | 0 | 100.0 | 100.0 | 100.0 | 100.0 |
| E0 | 2025/2026 | 380 | 0 | 100.0 | 0.0 | 100.0 | 100.0 |
| E0 | 2026/2027 | 100 | 0 | 100.0 | 100.0 | 100.0 | 100.0 |
| I1 | 2025/2026 | 380 | 0 | 100.0 | 0.0 | 100.0 | 100.0 |
| I1 | 2026/2027 | 110 | 0 | 100.0 | 100.0 | 100.0 | 100.0 |
| N1 | 2025/2026 | 306 | 0 | 100.0 | 0.0 | 100.0 | 100.0 |
| N1 | 2026/2027 | 108 | 0 | 100.0 | 100.0 | 100.0 | 100.0 |
| NOR | 2025 | 240 | 0 | 0.0 | 0.0 | 100.0 | 0.0 |
| NOR | 2026 | 208 | 0 | 0.0 | 0.0 | 100.0 | 0.0 |
| SP1 | 2025/2026 | 380 | 0 | 100.0 | 0.0 | 100.0 | 100.0 |
| SP1 | 2026/2027 | 119 | 0 | 100.0 | 100.0 | 100.0 | 100.0 |
| SWZ | 2025/2026 | 228 | 0 | 0.0 | 0.0 | 100.0 | 0.0 |
| SWZ | 2026/2027 | 78 | 0 | 0.0 | 0.0 | 100.0 | 0.0 |
| T1 | 2025/2026 | 306 | 0 | 100.0 | 0.0 | 100.0 | 100.0 |
| T1 | 2026/2027 | 99 | 0 | 100.0 | 100.0 | 100.0 | 100.0 |

## 2. Model accuracy

**Status: Problem.** 1X2 poisson: worse than the closing market; OU ml_random_forest: worse than the closing market

Default model per market against the margin-free closing market on the test season. Difference = model log loss minus market log loss (positive is worse), 95% paired bootstrap interval.

| market | model | test_matches | model_log_loss | market_log_loss | difference | ci95_low | ci95_high | finding |
|---|---|---|---|---|---|---|---|---|
| 1X2 | poisson | 801 | 0.9703 | 0.9462 | 0.0241 | 0.009 | 0.0398 | worse than the closing market |
| OU | ml_random_forest | 532 | 0.6604 | 0.6426 | 0.0178 | 0.0037 | 0.0325 | worse than the closing market |

## 3. Probability calibration

**Status: OK.** 1X2: ECE 0.0424; OU: ECE 0.0339

Expected calibration error over ten probability bins, test season. ECE above 0.05 is flagged.

| market | model | outcome | forecasts | mean_forecast | observed_frequency | ece | finding |
|---|---|---|---|---|---|---|---|
| 1X2 | poisson | H | 801 | 0.4498 | 0.4519 | 0.0424 | within 5 points |
| OU | ml_random_forest | over | 532 | 0.6043 | 0.6034 | 0.0339 | within 5 points |

## 4. Betting strategy performance

**Status: Warning.** backtest ROI -11.2% on 453 bets (95% interval -25.1% to +3.5%): not distinguishable from break-even

Historical backtest of the default models on the test season, flat stakes, Bet365 pre-closing prices, thresholds chosen on validation. A backtest is not live performance.

| market | model | validation_model_error | chosen_min_ev | validation_roi_pct | test_bets | mean_disagreement | mean_sigma | mean_model_edge |
|---|---|---|---|---|---|---|---|---|
| OU | ml_random_forest | 0.0839 | 0.15 | 5.61 | 103 | 0.0777 | 0.1172 | 0.1051 |
| 1X2 | poisson | 0.0786 | 0.05 | -12.44 | 350 | 0.0494 | 0.0946 | 0.0705 |

Paper trading (separate ledger):

| portfolio | kind | initial_bankroll | open_bets | open_exposure | settled_bets | bankroll | note |
|---|---|---|---|---|---|---|---|
| main | paper trading (no real money) | 1000.0 | 0 | 0.0 | 0 | 1000.0 | no paper bets recorded yet |

Settled paper bets: 0. Paper results are too few for any conclusion.

## 5. Closing line value

**Status: Problem.** mean CLV -3.37% (95% interval -4.3 to -2.42) on 453 bets

CLV = price taken x closing fair probability - 1. Persistently negative CLV means the bets are, on average, worse than the closing price, which is the strongest available sign of no edge.

## 6. Model deterioration

**Status: OK.** 1X2: 229 recent matches, OK; OU: 187 recent matches, OK

Change in (model - market) log loss between the last 28 days and the earlier test season. A positive change with an interval above zero would mean the model is getting worse. With fewer than 50 matches on either side, no statement is made.

| market | model | recent_matches | earlier_matches | change | ci95_low | ci95_high | status |
|---|---|---|---|---|---|---|---|
| 1X2 | poisson | 229 | 572 | -0.0133 | -0.0438 | 0.0171 | OK |
| OU | ml_random_forest | 187 | 345 | -0.0063 | -0.0345 | 0.0235 | OK |

## 7. Financial risk

**Status: OK.** max drawdown 14.11%, longest losing streak 13 (chance alone gives about 13.1)

- Flat-stake backtest: final bankroll 872.9 from 1000, largest daily exposure 6.34%.
- If the closing market's probabilities are right, simulated probability of ending with a loss: 66.7%; mean maximum drawdown 11.47%.
- Open paper exposure: 0.0.
- Flagged when drawdown exceeds 20% or the losing streak exceeds 1.5 times what chance gives.

## 8. Backtesting reliability

**Status: Warning.** 100% of prices have no collection time; 59% of test-season matches could be bet

- Test-season matches: 903 finished, 801 with a forecast, 532 with a price.
- Prices without a collection time cannot be proven to have been obtainable, so every backtest ROI is an upper bound on what was achievable.
- Stake limits, account restrictions and price slippage are not modelled.

## 9. Potential overfitting

**Status: Warning.** largest validation-to-test ROI drop 11.2 points

- Backtest configurations examined on validation: 80 (threshold grid x models x markets). ML hyperparameter settings examined: 45. The more settings are tried, the more of the best validation result is luck.
- A validation ROI more than 10 points above the test ROI is flagged.

| market | model | validation_roi_pct | test_roi_pct | validation_excess_log_loss | test_excess_log_loss |
|---|---|---|---|---|---|
| OU | ml_random_forest | 5.61 | -5.61 | 0.0098 | 0.0178 |
| 1X2 | poisson | -12.44 | -12.87 | 0.0352 | 0.0241 |

## 10. Recommended improvements

**Status: See list.** 8 recommendations

1. No upcoming fixtures are stored, so no live forecasts or paper bets can be made. Connect a fixtures and live-odds source (for example the OddAlerts API).
2. The default models are measurably worse than the closing market. Treat every positive expected value they report as model error until this changes.
3. Closing line value is negative beyond chance. Do not increase stakes, and do not move from paper trading to real money.
4. Obtain timestamped odds. Without them no backtest can show that a price was actually available, and odds movement can only be approximated.
5. Validation results did not carry over to the test season. Do not select strategies on validation ROI from samples this small; extend the history first.
6. Only the current season and the one before are stored. More seasons would give the models and the validation step far more to work with.
7. Platt calibration made ML forecasts worse on both validation and test in the Phase 5 report; consider storing uncalibrated ML probabilities.
8. xG and player availability are not model inputs. xG history is one season long and no licensed source for injuries or lineups is connected.
