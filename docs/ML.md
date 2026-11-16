# Machine learning and ensemble (Phase 5)

Code: `src/quantsport/ml/`. Run everything with `python -m quantsport ml-run`.

Machine-learning models are not assumed to be better than the statistical
ones. They are scored on the same out-of-sample matches, against the same
closing-market benchmark, and the report says which is ahead.

## Features (`features.py`)

One row per match, 26 features, all computed from matches on **earlier dates
only**. Matches are processed one date at a time: the day's features are
written first, then the day's results are added to team histories. A test
rewrites every result from a cut-off date onward and checks that features up
to and including that date are unchanged.

| Feature (per team, `h_` home / `a_` away) | Definition |
|---|---|
| `gf5`, `ga5`, `gf10`, `ga10` | mean goals for / against over the last 5 and 10 matches |
| `sh10`, `sha10`, `sot10`, `sota10` | mean shots and shots on target for / against, last 10 |
| `pts10` | mean points per match, last 10 |
| `rest` | days since the previous match, capped at 30 |
| `h_home_gf5`, `h_home_ga5` | home team's last 5 home matches |
| `a_away_gf5`, `a_away_ga5` | away team's last 5 away matches |
| `elo_diff` | home Elo minus away Elo (start 1500, K = 20, home advantage 60) |
| `league_gpm` | league's mean goals per match so far |

- Shot features are missing for Switzerland and Norway and stay missing; the
  tree models handle missing values natively and the logistic model imputes
  the training median.
- Bookmaker odds are not features, so forecasts remain independent of the
  market they are compared with.
- A match is usable only when both teams have at least 5 earlier matches.

## Models (`estimators.py`)

| Name | Estimator | Grid searched |
|---|---|---|
| `ml_logistic` | median imputation, scaling, logistic regression | C in 0.01, 0.1, 1 |
| `ml_random_forest` | 300 trees | max depth 3 or 5; min leaf 10 or 30 |
| `ml_gradient_boosting` | histogram gradient boosting, 150 iterations | learning rate 0.03 or 0.1; depth 2 or 3 |
| `ml_xgboost` | XGBoost, 200 trees, 80% row and column sampling | learning rate 0.03 or 0.1; depth 2 or 3 |

Each model is fitted separately for three targets: Over 2.5 (binary), both
teams to score (binary) and match result (three classes). Models are pooled
across all leagues, because one league alone has too few matches.

## Chronology (`pipeline.py`)

| Period | Use |
|---|---|
| before 1 January of the current season's start year | tuning window: hyperparameters chosen by rolling-origin validation, then frozen |
| from that date, previous season | validation forecasts |
| current season | test forecasts |

- **Rolling-origin validation:** three expanding folds cut at date boundaries;
  each validation fold lies strictly after its training data.
- **Walk-forward:** the model for a calendar month is fitted on every usable
  match before the first day of that month.
- **Calibration:** the base model is fitted on the earliest 80% of the
  training window; a logistic map on its log-probabilities (Platt scaling) is
  fitted on the latest 20%, which the base model has not seen. Stored
  forecasts are the calibrated ones. The report shows raw versus calibrated
  log loss so the benefit is measured, not assumed.
- **Versioning:** every fit is recorded in `model_versions` with its
  hyperparameters, data cut-off and training size.
- **Feature importance:** permutation importance (rise in log loss when a
  feature is shuffled), measured on validation-period matches with models
  fitted on earlier data.

## Ensemble (`ensemble.py`)

Linear pool `p = sum_k w_k p_k` over the four statistical and four ML models,
weights non-negative and summing to 1. For each market the weights minimise
log loss on validation-season matches, are frozen, and are applied to the
test season only.

**Gate.** The best single model is chosen on validation. The ensemble becomes
the default engine for a market only if its test-season log loss is lower and
the 95% paired bootstrap interval of the difference excludes zero. Otherwise
the single model stays the default.

## Limitations

- About 1,000 matches in the tuning window and only one and a third seasons
  overall. Grids are deliberately tiny.
- Validation forecasts cover only January to May of the previous season.
- Models are refitted monthly, so they can be up to a month stale (their
  features are always current).
- xG is not used: history exists for 2026/27 only.
- The ensemble covers Over/Under 2.5, both teams to score and 1X2 only.
