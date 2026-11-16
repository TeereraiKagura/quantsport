# Phase 3 market intelligence report

Generated 2026-11-15 22:57 UTC from stored odds and stored walk-forward forecasts. All prices are historical and carry no collection time, so every expected value below is **theoretical**: none of it was an executable opportunity. No bets are simulated and no profit is calculated here; that is Phase 4.

## Bookmaker margins

Overround = sum of implied probabilities minus 1, per complete set of prices. "Market maximum" is an aggregate of best prices, not a bookmaker.

| bookmaker | market | snapshot_type | sets | mean_overround_pct | median_overround_pct |
|---|---|---|---|---|---|
| Betfair Exchange | 1X2 | closing | 3260 | 0.72 | 0.64 |
| Market maximum | 1X2 | closing | 3429 | 2.56 | 2.69 |
| Pinnacle | 1X2 | closing | 1288 | 3.3 | 3.3 |
| Coral | 1X2 | closing | 1434 | 5.79 | 5.75 |
| BetVictor | 1X2 | closing | 2623 | 6.01 | 5.84 |
| Bwin | 1X2 | closing | 2655 | 6.03 | 5.92 |
| Bet365 | 1X2 | closing | 3271 | 6.27 | 5.88 |
| BetMGM | 1X2 | closing | 2057 | 6.36 | 6.54 |
| Ladbrokes | 1X2 | closing | 1535 | 6.47 | 6.44 |
| Betfred | 1X2 | closing | 2628 | 6.62 | 6.11 |
| Market average | 1X2 | closing | 3429 | 6.93 | 6.46 |
| Sky Bet | 1X2 | closing | 616 | 8.45 | 6.87 |
| Paddy Power | 1X2 | closing | 616 | 8.77 | 8.17 |
| Betfair Exchange | 1X2 | pre_close | 2550 | 2.03 | 0.9 |
| Market maximum | 1X2 | pre_close | 2675 | 2.83 | 2.89 |
| Pinnacle | 1X2 | pre_close | 1023 | 3.98 | 3.62 |
| Coral | 1X2 | pre_close | 1493 | 5.79 | 5.73 |
| Bet365 | 1X2 | pre_close | 2675 | 5.96 | 5.6 |
| Bwin | 1X2 | pre_close | 2674 | 6.02 | 5.92 |
| BetMGM | 1X2 | pre_close | 2046 | 6.27 | 6.43 |
| Ladbrokes | 1X2 | pre_close | 1531 | 6.47 | 6.45 |
| Betfred | 1X2 | pre_close | 2665 | 6.59 | 6.08 |
| Market average | 1X2 | pre_close | 2675 | 6.83 | 6.7 |
| BetVictor | 1X2 | pre_close | 2632 | 7.67 | 7.36 |
| Paddy Power | 1X2 | pre_close | 617 | 8.23 | 7.97 |
| Sky Bet | 1X2 | pre_close | 617 | 9.1 | 7.78 |
| Betfair Exchange | OU | closing | 2545 | 0.67 | 0.63 |
| Market maximum | OU | closing | 2675 | 3.05 | 3.17 |
| Pinnacle | OU | closing | 1015 | 3.4 | 3.32 |
| Bet365 | OU | closing | 2675 | 5.36 | 5.42 |
| Market average | OU | closing | 2675 | 6.8 | 6.64 |
| Betfair Exchange | OU | pre_close | 2497 | 3.69 | 1.33 |
| Market maximum | OU | pre_close | 2675 | 3.84 | 3.91 |
| Pinnacle | OU | pre_close | 1015 | 3.87 | 3.59 |
| Bet365 | OU | pre_close | 2675 | 5.36 | 5.42 |
| Market average | OU | pre_close | 2674 | 7.03 | 6.95 |

## Price dispersion between bookmakers

Individual bookmakers only; aggregates and the betting exchange are excluded. `best_vs_mean_price_pct` is how far the best price sits above the average price for the same selection. `mean_best_booksum` takes the best price on every outcome; below 1 would be an arbitrage on paper, but these prices were not observed at the same moment and may never have been available together.

| market | snapshot | selections | mean_books_quoting | best_vs_mean_price_pct | matches | mean_best_booksum | pct_matches_booksum_below_1 |
|---|---|---|---|---|---|---|---|
| 1X2 | pre_close | 8025 | 6.7 | 3.78 | 2675 | 1.0331 | 0.1 |
| OU | pre_close | 2030 | 2.0 | 0.95 | 2675 | 1.0473 | 0.1 |
| 1X2 | closing | 8349 | 6.5 | 4.13 | 3429 | 1.0344 | 2.9 |
| OU | closing | 2030 | 2.0 | 1.6 | 2675 | 1.0439 | 1.3 |

## Movement from pre-closing to closing

Change in the margin-free market-average probability. The pre-closing snapshot is taken some days before kick-off; it is not the opening price.

| market | selections | mean_abs_prob_change_pp | pct_moved_over_2pp | pct_moved_over_5pp |
|---|---|---|---|---|
| 1X2 | 8025 | 1.61 | 29.0 | 4.3 |
| OU | 5348 | 2.11 | 41.5 | 7.7 |

## Value screen on walk-forward forecasts

Each forecast is compared with the best pre-closing price: EV = p x price - 1. CLV = price x closing fair probability - 1, i.e. the same bet valued by the closing market instead of by the model. If a model's positive-EV selections do not show better CLV than taking the best price on everything (`all selections`), the apparent value is model error, not edge. Intervals are 95% bootstraps resampling whole matches. Switzerland and Norway are absent: no pre-closing prices exist. The EV thresholds are reporting cuts, not optimised values.

| market | model | subset | selections | matches | mean_ev_pct | mean_clv_pct | clv_ci95_low | clv_ci95_high | pct_beating_close |
|---|---|---|---|---|---|---|---|---|---|
| 1X2 | dixon_coles | all selections | 1596 | 532 | -0.7 | -3.26 | -3.62 | -2.91 | 27.5 |
| 1X2 | dixon_coles | model EV > 0% | 672 | 494 | 20.41 | -2.13 | -2.99 | -1.2 | 33.5 |
| 1X2 | dixon_coles | model EV > 5% | 507 | 401 | 26.25 | -1.9 | -2.96 | -0.85 | 35.5 |
| 1X2 | poisson | all selections | 1596 | 532 | -0.62 | -3.26 | -3.6 | -2.91 | 27.5 |
| 1X2 | poisson | model EV > 0% | 611 | 478 | 21.89 | -2.37 | -3.34 | -1.34 | 33.9 |
| 1X2 | poisson | model EV > 5% | 463 | 377 | 28.18 | -2.05 | -3.2 | -0.84 | 37.1 |
| 1X2 | bayesian | all selections | 1596 | 532 | 3.98 | -3.26 | -3.62 | -2.9 | 27.5 |
| 1X2 | bayesian | model EV > 0% | 662 | 491 | 30.58 | -2.41 | -3.3 | -1.46 | 34.7 |
| 1X2 | bayesian | model EV > 5% | 540 | 420 | 36.96 | -2.23 | -3.27 | -1.11 | 36.7 |
| 1X2 | logistic | all selections | 1596 | 532 | 5.14 | -3.26 | -3.61 | -2.91 | 27.5 |
| 1X2 | logistic | model EV > 0% | 752 | 526 | 38.66 | -3.13 | -3.87 | -2.36 | 29.3 |
| 1X2 | logistic | model EV > 5% | 659 | 495 | 43.77 | -2.96 | -3.78 | -2.11 | 30.3 |
| 1X2 | base_rate | all selections | 1851 | 617 | 23.31 | -3.19 | -3.52 | -2.85 | 27.9 |
| 1X2 | base_rate | model EV > 0% | 923 | 594 | 69.42 | -2.38 | -3.18 | -1.54 | 34.6 |
| 1X2 | base_rate | model EV > 5% | 802 | 546 | 79.51 | -2.23 | -3.14 | -1.27 | 36.2 |
| OU | dixon_coles | all selections | 1064 | 532 | -4.27 | -5.19 | -5.35 | -5.02 | 19.2 |
| OU | dixon_coles | model EV > 0% | 419 | 419 | 17.0 | -5.05 | -5.72 | -4.32 | 19.8 |
| OU | dixon_coles | model EV > 5% | 320 | 320 | 21.46 | -5.09 | -5.92 | -4.23 | 19.1 |
| OU | poisson | all selections | 1064 | 532 | -4.02 | -5.19 | -5.34 | -5.03 | 19.2 |
| OU | poisson | model EV > 0% | 424 | 424 | 16.84 | -5.12 | -5.81 | -4.4 | 19.3 |
| OU | poisson | model EV > 5% | 338 | 338 | 20.54 | -5.15 | -5.98 | -4.28 | 20.1 |
| OU | bayesian | all selections | 1064 | 532 | -3.03 | -5.19 | -5.34 | -5.03 | 19.2 |
| OU | bayesian | model EV > 0% | 414 | 414 | 17.64 | -5.56 | -6.31 | -4.81 | 20.3 |
| OU | bayesian | model EV > 5% | 336 | 336 | 21.1 | -5.46 | -6.32 | -4.57 | 21.4 |
| OU | logistic | all selections | 1064 | 532 | -3.39 | -5.19 | -5.35 | -5.03 | 19.2 |
| OU | logistic | model EV > 0% | 399 | 399 | 14.32 | -5.41 | -6.15 | -4.66 | 20.1 |
| OU | logistic | model EV > 5% | 272 | 272 | 19.88 | -5.2 | -6.17 | -4.23 | 21.7 |
| OU | base_rate | all selections | 1234 | 617 | -1.36 | -5.23 | -5.37 | -5.08 | 19.9 |
| OU | base_rate | model EV > 0% | 448 | 448 | 17.85 | -5.92 | -6.72 | -5.08 | 20.1 |
| OU | base_rate | model EV > 5% | 329 | 329 | 23.38 | -6.04 | -7.0 | -5.01 | 20.4 |
