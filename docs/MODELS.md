# Statistical models (Phase 2)

Every number the system shows must have a definition. This file is that
definition for the statistical engine. Code lives in `src/quantsport/models/`.

## Data given to a model

Finished matches of one league played **strictly before the prediction date**
(`store.training_set`). A model never sees the match it forecasts, other
matches on the same day, or anything later. A test tampers with all later
results and checks that forecasts do not change.

A model returns no forecast ("insufficient data") when either team has fewer
than `min_matches` = 5 matches in the training data, which mainly affects
newly promoted teams early in a season.

## From expected goals to market probabilities

Each goal model produces a score matrix `M[i, j] = P(home scores i, away
scores j)` for 0 to 15 goals each, renormalised to sum to 1. All markets are
sums over cells of that one matrix:

| Market | Definition |
|---|---|
| Over L goals (L = 0.5, 1.5, 2.5, 3.5) | sum of `M[i, j]` where `i + j > L` |
| Under L | 1 - Over L |
| Both teams to score | sum of `M[i, j]` where `i >= 1` and `j >= 1` |
| Home / Draw / Away | sums where `i > j`, `i = j`, `i < j` |
| Expected home / away / total goals | means of the matrix's marginals |

Because they share one matrix, the probabilities are consistent: each market
sums to 1 and Over 0.5 >= Over 1.5 >= Over 2.5 >= Over 3.5.

## Models

### Poisson regression (`poisson`)

```
home goals ~ Poisson(lam),  log lam = c + h + att[home] + dfn[away]
away goals ~ Poisson(mu),   log mu  = c +     att[away] + dfn[home]
```

`att` = attacking strength, `dfn` = defensive weakness, `h` = home advantage,
fitted as a generalised linear model (statsmodels). Home and away goals are
independent, so `M` is the outer product of two Poisson distributions.

The team effects carry a small ridge penalty (`ridge = 0.001` per
observation; the constant and home advantage are not penalised). Without it
the likelihood has no finite maximum when a team has very few matches and no
goals. The first walk-forward run exposed this: a promoted Turkish side with
one goalless match made the whole league's fit diverge, giving probabilities
near zero for outcomes that then happened. The penalty value is a fixed
stability default, not tuned, and a fit with any coefficient beyond +/-5 is
rejected as "insufficient data". Forecasts from the earlier, unpenalised
version remain in the database under their own model version, because
predictions are never deleted.

### Dixon-Coles (`dixon_coles`)

Same means, plus:

- **Low-score correction.** Cells (0,0), (0,1), (1,0), (1,1) are multiplied by
  `1 - lam*mu*rho`, `1 + lam*rho`, `1 + mu*rho`, `1 - rho` (first index = home
  goals). `rho` is estimated, bounded to [-0.3, 0.3].
- **Time decay.** Each match's log-likelihood has weight `exp(-xi * age in
  days)`. `xi = 0.002` (weight halves after about 347 days). This is a default
  and has **not** been tuned.

Fitted by weighted maximum likelihood (L-BFGS-B) with attack and defence
centred on zero.

### Bayesian team strengths (`bayesian`)

Four multipliers per team, 1.0 = league average: home attack `HA`, home
defensive weakness `HD`, away attack `AA`, away defensive weakness `AD`.

```
home goals ~ Poisson(mH * HA[home] * AD[away])
away goals ~ Poisson(mA * AA[away] * HD[home])
```

`mH`, `mA` are the league's mean home and away goals per match. Each strength
has a Gamma(k, k) prior (mean 1). Holding opponents at their posterior means,
the posterior is Gamma(k + goals, k + expected goals against an average
side), and the updates are iterated to a fixed point. This is a coordinate-wise
approximation, not full posterior sampling. `k = 8` (about six matches of
evidence) is a default and has **not** been tuned. The posterior standard
deviation `sqrt(shape) / rate` of each strength is reported as its
uncertainty. Forecasts plug in posterior means.

`python -m quantsport strengths --league E0` prints these.

### Logistic regression (`logistic`)

Three separate classifiers: Over 2.5 (binary), BTTS (binary), 1X2
(multinomial). Features: each side's mean goals scored and conceded over its
previous 10 matches, computed from earlier matches only. It has no score
matrix, so it gives no expected goals and no other goal lines.

### Benchmarks

- `base_rate`: the league's outcome frequencies in the training data.
- `market_close`: closing market-average odds with the margin removed
  proportionally, `p_i = (1/o_i) / sum_j (1/o_j)`. Used only as a yardstick
  here; the market module proper is Phase 3.

## Stored forecasts

`model_versions` records the model name, parameters, league, data cut-off and
training size. `predictions` and `prediction_probs` hold each forecast with
its creation timestamp. They are insert-only: the application refuses updates
and deletes, and a second forecast from the same model version for the same
match is ignored in favour of the original.

- `kind = live`: written before kick-off; refused once the match has started.
- `kind = walk_forward`: reconstructed afterwards from pre-match data. Kept
  separate and never to be reported as live performance.

The insert-only rule is enforced in the application layer, not by database
permissions.

## Evaluation

`python -m quantsport walk-forward` refits every model before each match day
of the current season and scores the forecasts.

- **Log loss** = `-ln(p)` of the outcome that occurred, averaged over matches.
- **Brier score** = `(p - y)^2` for binary markets; sum over the three
  outcomes for 1X2.
- Models are compared on identical matches: a match is scored only when every
  model produced a forecast.
- The interval on `ll_minus_ref` is a 95% paired bootstrap over matches (5,000
  resamples, fixed seed). An interval containing zero means the data cannot
  tell the model from the reference.

## Known limitations

- Decay rate, prior strength and feature window are untuned defaults. Tuning
  belongs to Phases 4 and 5 and must use validation data, not the test season.
- Only goals are used. Shots and xG are stored but not yet model inputs; xG
  history is too short (2026/27 only).
- No information on injuries, suspensions or lineups.
- Training history is about one and a third seasons per league.
