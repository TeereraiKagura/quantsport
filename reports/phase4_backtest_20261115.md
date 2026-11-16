# Phase 4 backtest report

Generated 2026-11-15 23:20 UTC. Historical simulation on stored walk-forward forecasts and historical pre-closing prices. This is a backtest, not live or paper-trading performance. Prices carry no collection time, so whether each bet could really have been placed at the recorded price is not verified; stake limits and account restrictions are not modelled.

Base settings: prices from Bet365 (pre-closing), flat stakes of 0.25% of a 1000-unit starting bankroll, commission 0%, one bet per match and market. ROI = profit / total staked. Intervals are 95% bootstraps resampling whole matches. `skipped_after_ruin` counts qualifying bets that could not be placed because the bankroll had already reached zero; when it is above 0, ROI covers only the bets placed before ruin.

## Coverage

Matches without a forecast (too little history for a team, or too early in the season) or without a price are not bet. Switzerland and Norway have no pre-closing prices and therefore contribute no bets.

| market | split | finished_matches | with_forecast | with_price |
|---|---|---|---|---|
| OU 2.5 | validation (previous season) | 2526 | 1722 | 1458 |
| OU 2.5 | test (current season) | 903 | 801 | 532 |
| 1X2 | validation (previous season) | 2526 | 1722 | 1458 |
| 1X2 | test (current season) | 903 | 801 | 532 |

## Step 1: validation season, threshold grid

The threshold with the highest ROI among those with at least 50 bets is carried to the test. With samples this small that choice is itself noisy. Each verdict is judged alone: with this many grid cells, a few will look "profitable beyond chance" by luck, which is exactly why only the test season counts.

| market | model | min_ev | bets | skipped_after_ruin | roi_pct | roi_ci95_low | roi_ci95_high | mean_clv_pct | verdict |
|---|---|---|---|---|---|---|---|---|---|
| OU 2.5 | dixon_coles | 0.0 | 1157 | 0 | -5.97 | -11.55 | -0.41 | -4.86 | losing beyond chance |
| OU 2.5 | dixon_coles | 0.05 | 909 | 0 | -5.39 | -11.74 | 0.74 | -4.71 | not distinguishable from break-even |
| OU 2.5 | dixon_coles | 0.1 | 685 | 0 | -4.94 | -12.31 | 2.38 | -4.56 | not distinguishable from break-even |
| OU 2.5 | dixon_coles | 0.15 | 481 | 0 | -7.1 | -16.0 | 1.92 | -4.61 | not distinguishable from break-even |
| OU 2.5 | poisson | 0.0 | 1158 | 0 | -6.35 | -11.88 | -0.6 | -4.8 | losing beyond chance |
| OU 2.5 | poisson | 0.05 | 887 | 0 | -5.24 | -11.75 | 1.37 | -4.75 | not distinguishable from break-even |
| OU 2.5 | poisson | 0.1 | 672 | 0 | -5.28 | -13.06 | 2.65 | -4.58 | not distinguishable from break-even |
| OU 2.5 | poisson | 0.15 | 473 | 0 | -4.78 | -13.57 | 4.42 | -4.75 | not distinguishable from break-even |
| OU 2.5 | bayesian | 0.0 | 1186 | 0 | -0.13 | -6.03 | 6.08 | -4.98 | not distinguishable from break-even |
| OU 2.5 | bayesian | 0.05 | 914 | 0 | -4.24 | -11.18 | 2.46 | -5.0 | not distinguishable from break-even |
| OU 2.5 | bayesian | 0.1 | 683 | 0 | -8.61 | -16.37 | -0.58 | -4.83 | losing beyond chance |
| OU 2.5 | bayesian | 0.15 | 495 | 0 | -11.52 | -20.92 | -1.82 | -4.77 | losing beyond chance |
| OU 2.5 | logistic | 0.0 | 871 | 0 | -3.9 | -10.96 | 3.49 | -4.78 | not distinguishable from break-even |
| OU 2.5 | logistic | 0.05 | 669 | 0 | -0.51 | -8.78 | 8.23 | -4.76 | not distinguishable from break-even |
| OU 2.5 | logistic | 0.1 | 482 | 0 | 0.18 | -10.35 | 10.33 | -4.75 | not distinguishable from break-even |
| OU 2.5 | logistic | 0.15 | 353 | 0 | 3.02 | -8.73 | 15.34 | -4.66 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | 0.0 | 844 | 0 | -2.35 | -9.95 | 5.4 | -4.69 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | 0.05 | 618 | 0 | 0.17 | -8.93 | 9.4 | -4.44 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | 0.1 | 445 | 0 | 6.57 | -4.74 | 18.07 | -4.01 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | 0.15 | 296 | 0 | 16.62 | 2.32 | 31.57 | -3.63 | profitable beyond chance |
| OU 2.5 | ml_random_forest | 0.0 | 819 | 0 | -2.69 | -10.28 | 4.78 | -4.78 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | 0.05 | 602 | 0 | -0.53 | -9.96 | 8.93 | -4.66 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | 0.1 | 431 | 0 | 0.9 | -10.31 | 12.12 | -4.51 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | 0.15 | 314 | 0 | 5.61 | -8.01 | 19.57 | -4.36 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | 0.0 | 851 | 0 | -2.65 | -10.25 | 4.91 | -4.77 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | 0.05 | 614 | 0 | -2.41 | -11.31 | 7.02 | -4.83 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | 0.1 | 450 | 0 | 2.3 | -8.74 | 13.61 | -4.69 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | 0.15 | 334 | 0 | 2.82 | -10.11 | 16.6 | -4.39 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | 0.0 | 825 | 0 | -2.44 | -10.08 | 5.47 | -4.75 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | 0.05 | 625 | 0 | 0.95 | -8.33 | 10.61 | -4.8 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | 0.1 | 459 | 0 | -1.96 | -12.9 | 9.19 | -4.74 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | 0.15 | 342 | 0 | 2.5 | -10.47 | 15.65 | -4.38 | not distinguishable from break-even |
| OU 2.5 | ensemble | 0.0 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| OU 2.5 | ensemble | 0.05 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| OU 2.5 | ensemble | 0.1 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| OU 2.5 | ensemble | 0.15 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| OU 2.5 | base_rate | 0.0 | 1065 | 0 | -1.86 | -8.77 | 4.81 | -5.12 | not distinguishable from break-even |
| OU 2.5 | base_rate | 0.05 | 751 | 0 | -1.2 | -9.45 | 7.21 | -4.98 | not distinguishable from break-even |
| OU 2.5 | base_rate | 0.1 | 509 | 0 | -2.76 | -13.27 | 7.69 | -4.67 | not distinguishable from break-even |
| OU 2.5 | base_rate | 0.15 | 350 | 0 | 2.11 | -11.38 | 15.85 | -4.34 | not distinguishable from break-even |
| 1X2 | dixon_coles | 0.0 | 1340 | 0 | -6.23 | -14.32 | 1.9 | -5.06 | not distinguishable from break-even |
| 1X2 | dixon_coles | 0.05 | 1135 | 0 | -6.84 | -15.43 | 2.21 | -5.0 | not distinguishable from break-even |
| 1X2 | dixon_coles | 0.1 | 888 | 0 | -10.05 | -19.79 | 0.19 | -4.85 | not distinguishable from break-even |
| 1X2 | dixon_coles | 0.15 | 668 | 0 | -8.97 | -20.67 | 3.34 | -4.73 | not distinguishable from break-even |
| 1X2 | poisson | 0.0 | 1314 | 0 | -13.42 | -21.05 | -5.53 | -5.41 | losing beyond chance |
| 1X2 | poisson | 0.05 | 1045 | 0 | -12.44 | -21.0 | -3.62 | -5.33 | losing beyond chance |
| 1X2 | poisson | 0.1 | 799 | 0 | -12.89 | -23.04 | -2.41 | -5.26 | losing beyond chance |
| 1X2 | poisson | 0.15 | 611 | 0 | -16.0 | -27.95 | -3.3 | -4.97 | losing beyond chance |
| 1X2 | bayesian | 0.0 | 1335 | 0 | -12.76 | -21.18 | -3.93 | -4.75 | losing beyond chance |
| 1X2 | bayesian | 0.05 | 1137 | 0 | -14.98 | -24.33 | -4.84 | -4.68 | losing beyond chance |
| 1X2 | bayesian | 0.1 | 960 | 0 | -19.45 | -29.97 | -8.68 | -4.67 | losing beyond chance |
| 1X2 | bayesian | 0.15 | 805 | 0 | -23.49 | -34.84 | -11.72 | -4.59 | losing beyond chance |
| 1X2 | logistic | 0.0 | 1129 | 0 | -0.68 | -10.19 | 9.32 | -4.81 | not distinguishable from break-even |
| 1X2 | logistic | 0.05 | 1044 | 0 | -1.31 | -11.15 | 9.3 | -4.69 | not distinguishable from break-even |
| 1X2 | logistic | 0.1 | 924 | 0 | -1.25 | -12.62 | 10.26 | -4.53 | not distinguishable from break-even |
| 1X2 | logistic | 0.15 | 821 | 0 | -0.22 | -12.23 | 12.68 | -4.33 | not distinguishable from break-even |
| 1X2 | ml_logistic | 0.0 | 1014 | 0 | -5.63 | -15.32 | 4.55 | -4.75 | not distinguishable from break-even |
| 1X2 | ml_logistic | 0.05 | 869 | 0 | -5.94 | -16.73 | 5.03 | -4.61 | not distinguishable from break-even |
| 1X2 | ml_logistic | 0.1 | 703 | 0 | -8.77 | -20.39 | 3.93 | -4.53 | not distinguishable from break-even |
| 1X2 | ml_logistic | 0.15 | 578 | 0 | -6.65 | -20.59 | 8.31 | -4.41 | not distinguishable from break-even |
| 1X2 | ml_random_forest | 0.0 | 1012 | 0 | -10.9 | -20.94 | -0.62 | -4.66 | losing beyond chance |
| 1X2 | ml_random_forest | 0.05 | 852 | 0 | -9.93 | -21.24 | 2.25 | -4.52 | not distinguishable from break-even |
| 1X2 | ml_random_forest | 0.1 | 688 | 0 | -11.27 | -24.34 | 1.71 | -4.45 | not distinguishable from break-even |
| 1X2 | ml_random_forest | 0.15 | 566 | 0 | -12.76 | -27.43 | 2.96 | -4.59 | not distinguishable from break-even |
| 1X2 | ml_gradient_boosting | 0.0 | 1016 | 0 | -6.54 | -17.03 | 3.91 | -4.88 | not distinguishable from break-even |
| 1X2 | ml_gradient_boosting | 0.05 | 888 | 0 | -4.7 | -16.13 | 6.92 | -4.76 | not distinguishable from break-even |
| 1X2 | ml_gradient_boosting | 0.1 | 727 | 0 | -6.38 | -19.09 | 6.52 | -4.61 | not distinguishable from break-even |
| 1X2 | ml_gradient_boosting | 0.15 | 603 | 0 | -7.29 | -21.37 | 7.6 | -4.51 | not distinguishable from break-even |
| 1X2 | ml_xgboost | 0.0 | 1018 | 0 | -8.86 | -19.05 | 1.64 | -4.82 | not distinguishable from break-even |
| 1X2 | ml_xgboost | 0.05 | 864 | 0 | -8.55 | -19.9 | 2.92 | -4.7 | not distinguishable from break-even |
| 1X2 | ml_xgboost | 0.1 | 719 | 0 | -9.03 | -21.89 | 4.37 | -4.75 | not distinguishable from break-even |
| 1X2 | ml_xgboost | 0.15 | 571 | 0 | -7.76 | -22.29 | 8.29 | -4.7 | not distinguishable from break-even |
| 1X2 | ensemble | 0.0 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| 1X2 | ensemble | 0.05 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| 1X2 | ensemble | 0.1 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| 1X2 | ensemble | 0.15 | 0 | 0 | n/a | n/a | n/a | n/a | no bets |
| 1X2 | base_rate | 0.0 | 1409 | 0 | -14.04 | -23.29 | -4.64 | -4.59 | losing beyond chance |
| 1X2 | base_rate | 0.05 | 1295 | 0 | -16.5 | -26.05 | -6.33 | -4.53 | losing beyond chance |
| 1X2 | base_rate | 0.1 | 1196 | 0 | -15.78 | -26.06 | -4.79 | -4.45 | losing beyond chance |
| 1X2 | base_rate | 0.15 | 1070 | 0 | -19.33 | -30.42 | -8.01 | -4.36 | losing beyond chance |

## Step 2: test season, each model run once with its validation-chosen threshold

| market | model | chosen_min_ev | validation_roi_pct | bets | skipped_after_ruin | wins | losses | staked | profit | roi_pct | roi_ci95_low | roi_ci95_high | win_rate_pct | mean_odds | mean_clv_pct | max_drawdown_pct | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| OU 2.5 | dixon_coles | 0.1 | -4.94 | 242 | 0.0 | 106.0 | 136.0 | 605.0 | -47.32 | -7.82 | -21.39 | 5.85 | 43.8 | 2.271 | -4.96 | 6.71 | not distinguishable from break-even |
| OU 2.5 | poisson | 0.15 | -4.78 | 175 | 0.0 | 73.0 | 102.0 | 437.5 | -33.23 | -7.59 | -24.54 | 9.06 | 41.7 | 2.383 | -4.45 | 4.69 | not distinguishable from break-even |
| OU 2.5 | bayesian | 0.0 | -0.13 | 414 | 0.0 | 190.0 | 224.0 | 1035.0 | -51.8 | -5.0 | -15.41 | 5.7 | 45.9 | 2.285 | -5.56 | 10.16 | not distinguishable from break-even |
| OU 2.5 | logistic | 0.15 | 3.02 | 132 | 0.0 | 43.0 | 89.0 | 330.0 | -67.23 | -20.37 | -39.5 | 0.37 | 32.6 | 2.733 | -4.52 | 9.18 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | 0.15 | 16.62 | 151 | 0.0 | 75.0 | 76.0 | 377.5 | -11.47 | -3.04 | -19.44 | 13.26 | 49.7 | 2.189 | -3.66 | 2.6 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | 0.15 | 5.61 | 103 | 0.0 | 44.0 | 59.0 | 257.5 | -14.45 | -5.61 | -27.33 | 16.18 | 42.7 | 2.513 | -2.81 | 5.0 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | 0.15 | 2.82 | 140 | 0.0 | 54.0 | 86.0 | 350.0 | -52.95 | -15.13 | -34.05 | 3.66 | 38.6 | 2.431 | -4.13 | 7.04 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | 0.15 | 2.5 | 138 | 0.0 | 52.0 | 86.0 | 345.0 | -49.6 | -14.38 | -33.44 | 5.09 | 37.7 | 2.497 | -4.32 | 6.99 | not distinguishable from break-even |
| OU 2.5 | ensemble | n/a | n/a | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | no threshold had enough validation bets |
| OU 2.5 | base_rate | 0.15 | 2.11 | 154 | 0.0 | 47.0 | 107.0 | 385.0 | -41.18 | -10.69 | -31.81 | 11.83 | 30.5 | 3.108 | -5.38 | 5.84 | not distinguishable from break-even |
| 1X2 | dixon_coles | 0.0 | -6.23 | 463 | 0.0 | 136.0 | 327.0 | 1157.5 | -154.8 | -13.37 | -27.69 | 0.97 | 29.4 | 4.015 | -3.71 | 16.46 | not distinguishable from break-even |
| 1X2 | poisson | 0.05 | -12.44 | 350 | 0.0 | 99.0 | 251.0 | 875.0 | -112.65 | -12.87 | -28.94 | 4.54 | 28.3 | 4.414 | -3.54 | 11.93 | not distinguishable from break-even |
| 1X2 | bayesian | 0.0 | -12.76 | 477 | 0.0 | 136.0 | 341.0 | 1192.5 | -137.78 | -11.55 | -25.65 | 3.04 | 28.5 | 4.582 | -3.57 | 15.68 | not distinguishable from break-even |
| 1X2 | logistic | 0.15 | -0.22 | 376 | 0.0 | 81.0 | 295.0 | 940.0 | -238.9 | -25.41 | -41.22 | -9.05 | 21.5 | 4.814 | -4.29 | 26.02 | losing beyond chance |
| 1X2 | ml_logistic | 0.0 | -5.63 | 487 | 0.0 | 119.0 | 368.0 | 1217.5 | -310.05 | -25.47 | -38.71 | -11.66 | 24.4 | 4.441 | -4.23 | 31.69 | losing beyond chance |
| 1X2 | ml_random_forest | 0.05 | -9.93 | 427 | 0.0 | 114.0 | 313.0 | 1067.5 | -121.95 | -11.42 | -27.21 | 5.36 | 26.7 | 5.016 | -4.08 | 13.06 | not distinguishable from break-even |
| 1X2 | ml_gradient_boosting | 0.05 | -4.7 | 424 | 0.0 | 105.0 | 319.0 | 1060.0 | -241.15 | -22.75 | -37.26 | -7.54 | 24.8 | 4.734 | -4.05 | 24.87 | losing beyond chance |
| 1X2 | ml_xgboost | 0.15 | -7.76 | 275 | 0.0 | 57.0 | 218.0 | 687.5 | -146.68 | -21.33 | -40.99 | 0.19 | 20.7 | 5.757 | -3.31 | 14.67 | not distinguishable from break-even |
| 1X2 | ensemble | n/a | n/a | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | no threshold had enough validation bets |
| 1X2 | base_rate | 0.0 | -14.04 | 581 | 0.0 | 136.0 | 445.0 | 1452.5 | -145.55 | -10.02 | -24.09 | 5.41 | 23.4 | 5.201 | -3.99 | 15.74 | not distinguishable from break-even |

## Sensitivity on the test season (information only, not for choosing settings)

| market | model | variant | bets | skipped_after_ruin | roi_pct | roi_ci95_low | roi_ci95_high | max_drawdown_pct | final_bankroll | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| OU 2.5 | dixon_coles | best price across bookmakers | 242 | 0 | -7.82 | -21.39 | 5.85 | 6.71 | 952.68 | not distinguishable from break-even |
| OU 2.5 | dixon_coles | flat 1% of starting bankroll | 242 | 0 | -7.82 | -21.39 | 5.85 | 26.74 | 810.7 | not distinguishable from break-even |
| OU 2.5 | dixon_coles | 1% of current bankroll | 242 | 0 | -8.86 | -22.44 | 5.15 | 24.3 | 813.37 | not distinguishable from break-even |
| OU 2.5 | dixon_coles | quarter Kelly, 5% cap | 242 | 0 | -9.63 | -23.7 | 4.93 | 67.78 | 431.38 | not distinguishable from break-even |
| OU 2.5 | dixon_coles | bet every match (no EV filter) | 532 | 0 | -4.08 | -13.29 | 4.61 | 9.15 | 945.75 | not distinguishable from break-even |
| OU 2.5 | poisson | best price across bookmakers | 175 | 0 | -7.59 | -24.54 | 9.06 | 4.69 | 966.77 | not distinguishable from break-even |
| OU 2.5 | poisson | flat 1% of starting bankroll | 175 | 0 | -7.59 | -24.54 | 9.06 | 18.34 | 867.1 | not distinguishable from break-even |
| OU 2.5 | poisson | 1% of current bankroll | 175 | 0 | -8.34 | -25.28 | 8.42 | 17.79 | 863.33 | not distinguishable from break-even |
| OU 2.5 | poisson | quarter Kelly, 5% cap | 175 | 0 | -10.81 | -28.31 | 6.73 | 63.92 | 429.72 | not distinguishable from break-even |
| OU 2.5 | poisson | bet every match (no EV filter) | 532 | 0 | -6.36 | -15.24 | 2.51 | 11.2 | 915.42 | not distinguishable from break-even |
| OU 2.5 | bayesian | best price across bookmakers | 414 | 0 | -5.0 | -15.41 | 5.7 | 10.16 | 948.2 | not distinguishable from break-even |
| OU 2.5 | bayesian | flat 1% of starting bankroll | 414 | 0 | -5.0 | -15.41 | 5.7 | 38.6 | 792.8 | not distinguishable from break-even |
| OU 2.5 | bayesian | 1% of current bankroll | 414 | 0 | -6.14 | -16.66 | 4.6 | 35.31 | 787.95 | not distinguishable from break-even |
| OU 2.5 | bayesian | quarter Kelly, 5% cap | 414 | 0 | -11.67 | -24.89 | 1.67 | 82.41 | 232.69 | not distinguishable from break-even |
| OU 2.5 | bayesian | bet every match (no EV filter) | 532 | 0 | -6.48 | -15.92 | 2.58 | 13.76 | 913.85 | not distinguishable from break-even |
| OU 2.5 | logistic | best price across bookmakers | 132 | 0 | -20.37 | -39.5 | 0.37 | 9.18 | 932.78 | not distinguishable from break-even |
| OU 2.5 | logistic | flat 1% of starting bankroll | 132 | 0 | -20.37 | -39.5 | 0.37 | 34.9 | 731.1 | not distinguishable from break-even |
| OU 2.5 | logistic | 1% of current bankroll | 132 | 0 | -21.51 | -40.63 | -0.94 | 31.74 | 755.61 | losing beyond chance |
| OU 2.5 | logistic | quarter Kelly, 5% cap | 132 | 0 | -23.31 | -44.92 | -0.08 | 79.99 | 274.8 | losing beyond chance |
| OU 2.5 | logistic | bet every match (no EV filter) | 532 | 0 | -11.08 | -19.83 | -2.64 | 19.36 | 852.58 | losing beyond chance |
| OU 2.5 | ml_logistic | best price across bookmakers | 151 | 0 | -3.04 | -19.44 | 13.26 | 2.6 | 988.53 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | flat 1% of starting bankroll | 151 | 0 | -3.04 | -19.44 | 13.26 | 9.95 | 954.1 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | 1% of current bankroll | 151 | 0 | -3.46 | -19.73 | 12.86 | 10.59 | 948.1 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | quarter Kelly, 5% cap | 151 | 0 | -1.62 | -17.69 | 14.41 | 35.59 | 886.76 | not distinguishable from break-even |
| OU 2.5 | ml_logistic | bet every match (no EV filter) | 532 | 0 | -9.49 | -17.58 | -1.29 | 13.88 | 873.73 | losing beyond chance |
| OU 2.5 | ml_random_forest | best price across bookmakers | 103 | 0 | -5.61 | -27.33 | 16.18 | 5.0 | 985.55 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | flat 1% of starting bankroll | 103 | 0 | -5.61 | -27.33 | 16.18 | 19.3 | 942.2 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | 1% of current bankroll | 103 | 0 | -6.5 | -28.16 | 15.58 | 18.59 | 936.26 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | quarter Kelly, 5% cap | 103 | 0 | -2.71 | -24.74 | 19.66 | 48.17 | 895.19 | not distinguishable from break-even |
| OU 2.5 | ml_random_forest | bet every match (no EV filter) | 532 | 0 | -6.62 | -15.2 | 2.11 | 10.26 | 911.95 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | best price across bookmakers | 140 | 0 | -15.13 | -34.05 | 3.66 | 7.04 | 947.05 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | flat 1% of starting bankroll | 140 | 0 | -15.13 | -34.05 | 3.66 | 27.65 | 788.2 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | 1% of current bankroll | 140 | 0 | -16.13 | -35.05 | 2.66 | 25.09 | 803.63 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | quarter Kelly, 5% cap | 140 | 0 | -17.28 | -37.41 | 2.73 | 71.57 | 379.17 | not distinguishable from break-even |
| OU 2.5 | ml_gradient_boosting | bet every match (no EV filter) | 532 | 0 | -6.45 | -15.02 | 2.43 | 10.57 | 914.28 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | best price across bookmakers | 138 | 0 | -14.38 | -33.44 | 5.09 | 6.99 | 950.4 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | flat 1% of starting bankroll | 138 | 0 | -14.38 | -33.44 | 5.09 | 27.18 | 801.6 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | 1% of current bankroll | 138 | 0 | -15.47 | -34.58 | 4.1 | 24.97 | 812.98 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | quarter Kelly, 5% cap | 138 | 0 | -18.3 | -38.01 | 2.88 | 72.18 | 381.04 | not distinguishable from break-even |
| OU 2.5 | ml_xgboost | bet every match (no EV filter) | 532 | 0 | -6.37 | -14.93 | 2.12 | 9.51 | 915.23 | not distinguishable from break-even |
| OU 2.5 | base_rate | best price across bookmakers | 154 | 0 | -10.69 | -31.81 | 11.83 | 5.84 | 958.83 | not distinguishable from break-even |
| OU 2.5 | base_rate | flat 1% of starting bankroll | 154 | 0 | -10.69 | -31.81 | 11.83 | 23.31 | 835.3 | not distinguishable from break-even |
| OU 2.5 | base_rate | 1% of current bankroll | 154 | 0 | -12.4 | -33.43 | 10.18 | 21.61 | 835.86 | not distinguishable from break-even |
| OU 2.5 | base_rate | quarter Kelly, 5% cap | 154 | 0 | -22.32 | -43.89 | 1.48 | 73.02 | 327.44 | not distinguishable from break-even |
| OU 2.5 | base_rate | bet every match (no EV filter) | 617 | 0 | -14.58 | -23.26 | -5.87 | 22.75 | 775.08 | losing beyond chance |
| 1X2 | dixon_coles | best price across bookmakers | 494 | 0 | -12.46 | -25.64 | 1.38 | 15.74 | 846.1 | not distinguishable from break-even |
| 1X2 | dixon_coles | flat 1% of starting bankroll | 463 | 0 | -13.37 | -27.69 | 0.97 | 65.83 | 380.8 | not distinguishable from break-even |
| 1X2 | dixon_coles | 1% of current bankroll | 463 | 0 | -15.82 | -29.94 | -1.35 | 50.15 | 513.45 | losing beyond chance |
| 1X2 | dixon_coles | quarter Kelly, 5% cap | 463 | 0 | -15.69 | -32.31 | 2.16 | 75.66 | 243.39 | not distinguishable from break-even |
| 1X2 | dixon_coles | bet every match (no EV filter) | 532 | 0 | -9.95 | -22.76 | 3.8 | 16.67 | 867.65 | not distinguishable from break-even |
| 1X2 | poisson | best price across bookmakers | 377 | 0 | -12.42 | -28.02 | 4.19 | 12.47 | 882.98 | not distinguishable from break-even |
| 1X2 | poisson | flat 1% of starting bankroll | 350 | 0 | -12.87 | -28.94 | 4.54 | 46.66 | 549.4 | not distinguishable from break-even |
| 1X2 | poisson | 1% of current bankroll | 350 | 0 | -13.86 | -29.94 | 3.64 | 41.38 | 603.73 | not distinguishable from break-even |
| 1X2 | poisson | quarter Kelly, 5% cap | 350 | 0 | -13.34 | -31.05 | 5.89 | 71.96 | 290.95 | not distinguishable from break-even |
| 1X2 | poisson | bet every match (no EV filter) | 532 | 0 | -11.43 | -23.77 | 1.56 | 16.19 | 847.95 | not distinguishable from break-even |
| 1X2 | bayesian | best price across bookmakers | 491 | 0 | -10.68 | -24.2 | 3.27 | 15.59 | 868.93 | not distinguishable from break-even |
| 1X2 | bayesian | flat 1% of starting bankroll | 477 | 0 | -11.55 | -25.65 | 3.04 | 58.83 | 448.9 | not distinguishable from break-even |
| 1X2 | bayesian | 1% of current bankroll | 477 | 0 | -11.32 | -25.66 | 3.53 | 49.94 | 542.75 | not distinguishable from break-even |
| 1X2 | bayesian | quarter Kelly, 5% cap | 477 | 0 | -18.02 | -36.63 | 2.71 | 90.0 | 108.51 | not distinguishable from break-even |
| 1X2 | bayesian | bet every match (no EV filter) | 532 | 0 | -8.83 | -22.01 | 5.05 | 14.68 | 882.62 | not distinguishable from break-even |
| 1X2 | logistic | best price across bookmakers | 405 | 0 | -26.43 | -41.51 | -10.42 | 28.85 | 732.42 | losing beyond chance |
| 1X2 | logistic | flat 1% of starting bankroll | 376 | 0 | -25.85 | -41.74 | -9.44 | 96.36 | 40.58 | losing beyond chance |
| 1X2 | logistic | 1% of current bankroll | 376 | 0 | -23.59 | -40.87 | -5.55 | 68.23 | 354.21 | losing beyond chance |
| 1X2 | logistic | quarter Kelly, 5% cap | 376 | 0 | -17.11 | -39.52 | 6.2 | 98.6 | 18.74 | not distinguishable from break-even |
| 1X2 | logistic | bet every match (no EV filter) | 532 | 0 | -22.13 | -34.36 | -9.15 | 31.4 | 705.72 | losing beyond chance |
| 1X2 | ml_logistic | best price across bookmakers | 504 | 0 | -24.64 | -37.94 | -10.77 | 31.73 | 689.55 | losing beyond chance |
| 1X2 | ml_logistic | flat 1% of starting bankroll | 385 | 102 | -30.89 | -45.71 | -15.53 | 100.0 | 0.0 | losing beyond chance |
| 1X2 | ml_logistic | 1% of current bankroll | 487 | 0 | -27.88 | -41.34 | -13.63 | 74.42 | 266.01 | losing beyond chance |
| 1X2 | ml_logistic | quarter Kelly, 5% cap | 487 | 0 | -25.99 | -44.81 | -5.62 | 95.03 | 52.94 | losing beyond chance |
| 1X2 | ml_logistic | bet every match (no EV filter) | 532 | 0 | -23.35 | -35.46 | -10.22 | 31.74 | 689.4 | losing beyond chance |
| 1X2 | ml_random_forest | best price across bookmakers | 448 | 0 | -12.06 | -27.27 | 4.38 | 14.36 | 864.92 | not distinguishable from break-even |
| 1X2 | ml_random_forest | flat 1% of starting bankroll | 427 | 0 | -11.42 | -27.21 | 5.36 | 50.75 | 512.2 | not distinguishable from break-even |
| 1X2 | ml_random_forest | 1% of current bankroll | 427 | 0 | -12.24 | -27.98 | 4.59 | 43.51 | 587.51 | not distinguishable from break-even |
| 1X2 | ml_random_forest | quarter Kelly, 5% cap | 427 | 0 | -18.09 | -35.81 | 1.46 | 85.3 | 155.77 | not distinguishable from break-even |
| 1X2 | ml_random_forest | bet every match (no EV filter) | 532 | 0 | -16.11 | -29.72 | -1.73 | 22.2 | 785.78 | losing beyond chance |
| 1X2 | ml_gradient_boosting | best price across bookmakers | 451 | 0 | -24.02 | -37.68 | -9.74 | 27.8 | 729.18 | losing beyond chance |
| 1X2 | ml_gradient_boosting | flat 1% of starting bankroll | 424 | 0 | -23.2 | -38.01 | -7.67 | 94.97 | 52.3 | losing beyond chance |
| 1X2 | ml_gradient_boosting | 1% of current bankroll | 424 | 0 | -25.79 | -40.38 | -10.56 | 65.52 | 358.56 | losing beyond chance |
| 1X2 | ml_gradient_boosting | quarter Kelly, 5% cap | 424 | 0 | -30.41 | -47.65 | -11.11 | 95.51 | 47.44 | losing beyond chance |
| 1X2 | ml_gradient_boosting | bet every match (no EV filter) | 532 | 0 | -19.57 | -32.01 | -6.31 | 27.23 | 739.72 | losing beyond chance |
| 1X2 | ml_xgboost | best price across bookmakers | 301 | 0 | -23.43 | -41.79 | -4.35 | 17.63 | 823.68 | losing beyond chance |
| 1X2 | ml_xgboost | flat 1% of starting bankroll | 275 | 0 | -21.33 | -40.99 | 0.19 | 58.67 | 413.3 | not distinguishable from break-even |
| 1X2 | ml_xgboost | 1% of current bankroll | 275 | 0 | -24.65 | -43.47 | -3.74 | 46.33 | 536.74 | losing beyond chance |
| 1X2 | ml_xgboost | quarter Kelly, 5% cap | 275 | 0 | -29.39 | -49.13 | -6.32 | 89.71 | 102.94 | losing beyond chance |
| 1X2 | ml_xgboost | bet every match (no EV filter) | 532 | 0 | -19.02 | -31.4 | -5.31 | 26.03 | 747.08 | losing beyond chance |
| 1X2 | base_rate | best price across bookmakers | 594 | 0 | -7.32 | -21.89 | 7.78 | 13.24 | 891.3 | not distinguishable from break-even |
| 1X2 | base_rate | flat 1% of starting bankroll | 581 | 0 | -10.02 | -24.09 | 5.41 | 60.45 | 417.8 | not distinguishable from break-even |
| 1X2 | base_rate | 1% of current bankroll | 581 | 0 | -9.96 | -23.98 | 5.3 | 50.98 | 511.83 | not distinguishable from break-even |
| 1X2 | base_rate | quarter Kelly, 5% cap | 581 | 0 | -17.56 | -41.1 | 8.23 | 99.43 | 6.51 | not distinguishable from break-even |
| 1X2 | base_rate | bet every match (no EV filter) | 617 | 0 | -9.71 | -23.25 | 4.72 | 15.81 | 850.15 | not distinguishable from break-even |
