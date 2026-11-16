# QuantSport architecture

QuantSport is a research and paper-trading system. It asks one question: do
independently estimated probabilities beat bookmaker prices often enough, and
by enough, to be statistically distinguishable from luck? Nothing in the system
places real bets.

## 1. Modules and data flow

```
 providers / CSV upload
          |
   A. DATA ENGINE ---------- raw file archive (hash-addressed)
   fetch -> parse -> validate -> versioned store
          |
          v
      DATABASE  <------------------------------------------+
          |                                                |
   B. STATISTICAL ENGINE      C. ML ENGINE                 |
   Poisson, Dixon-Coles,      Random Forest, XGBoost,      |
   logistic, Bayesian         gradient boosting, logistic  |
          \                      /                         |
           v                    v                          |
        timestamped, immutable predictions ----------------+
                      |
   D. MARKET INTELLIGENCE   margin removal, EV, CLV, price comparison
                      |
   E. RISK ENGINE           fractional Kelly, exposure, drawdown, simulation
                      |
   F. PERFORMANCE ENGINE    Brier, log loss, calibration, ROI, intervals
                      |
        backtester / Streamlit dashboard / weekly audit
```

Rules that hold across every module:

- **Point-in-time discipline.** A model may only read rows whose information
  existed before the prediction timestamp. Features are built from matches that
  kicked off strictly earlier.
- **Missing stays missing.** A NULL means the provider did not supply the value.
  Nothing is imputed at storage time.
- **Append-only history.** Changed records get a new version; predictions, once
  written, are never updated.
- **Three ledgers.** Backtest, out-of-sample and live paper-trading results are
  stored and reported separately.

## 2. Database schema

SQLAlchemy models; SQLite by default, PostgreSQL by setting
`QUANTSPORT_DATABASE_URL`. All timestamps are UTC.

### Implemented in Phase 1 (`src/quantsport/db/models.py`)

| Table | Purpose | Key columns |
|---|---|---|
| `data_sources` | Source attribution | `key`, `name`, `url`, `license_note` |
| `leagues` | Competition registry | `code`, `name`, `country`, `season_type` |
| `teams` | Canonical teams | `name`, `country` (unique together) |
| `team_aliases` | Provider spelling -> team | `team_id`, `source_id`, `alias` |
| `ingestion_runs` | Audit trail, one row per file load | `origin`, `status`, `file_sha256`, `raw_path`, row counters, `error` |
| `matches` | One row per match | `league_id`, `season`, `match_date`, `kickoff_utc`, teams, `status`, goals, `payload_hash`, `version`, `first_run_id`, `last_run_id` |
| `match_stats` | Shots, shots on target, corners, fouls, cards, xG, possession | one row per match, home/away columns |
| `odds_quotes` | One price | `match_id`, `bookmaker`, `is_aggregate`, `market`, `line`, `selection`, `snapshot_type`, `price`, `observed_at` |
| `match_versions` | Full record at every version | `match_id`, `version`, `payload_json`, `payload_hash`, `run_id` |
| `validation_issues` | Every rejected row and warning | `run_id`, `severity`, `code`, `row_number`, `field`, `message` |
| `player_availability` | Injuries, suspensions | defined, empty: no licensed source yet |
| `lineup_entries` | Starting lineups | defined, empty: no licensed source yet |

Added in Phase 2, all insert-only:

| Table | Purpose | Key columns |
|---|---|---|
| `model_versions` | A model fitted on one league up to a cut-off | `name`, `league_id`, `params_json`, `params_hash`, `data_cutoff`, `n_train` |
| `predictions` | One model's forecast for one match | `match_id`, `model_version_id`, `kind` (`live` or `walk_forward`), `created_at`, expected goals |
| `prediction_probs` | Probability per selection | `prediction_id`, `market`, `line`, `selection`, `probability` |

Match identity is `(league, home team, away team, match date)`. An unplayed
fixture that is rescheduled keeps its row and gains a version.

### Planned (added in the phase that needs them)

| Table | Phase | Purpose |
|---|---|---|

## 3. Folder structure

```
QuantSport/
  pyproject.toml          dependencies and entry point
  .env.example            configuration template (no secrets in git)
  docs/                   architecture, data sources, metric definitions
  src/quantsport/
    config.py             environment-driven settings, logging
    cli.py                python -m quantsport <command>
    db/                   models, engine, seeding
    data/                 Module A: leagues, sources, parsing, validation, ingest, quality
    models/               Modules B and C (Phase 2, 5)
    market/               Module D (Phase 3)
    backtest/             Phase 4
    risk/                 Module E (Phase 6)
    performance/          Module F
    app/                  Streamlit dashboard, FastAPI (Phase 7)
    jobs/                 scheduled tasks, weekly audit (Phase 8)
  tests/                  pytest; synthetic rows only, clearly labelled
  data/                   database and raw archive (git-ignored)
  reports/                generated reports
```

Only the directories for implemented phases exist.

## 4. Dependencies

| Phase | Packages |
|---|---|
| 1 (installed) | pandas, numpy, SQLAlchemy, requests, python-dotenv, tzdata, truststore, pytest |
| 2-5 | scipy, statsmodels, scikit-learn, xgboost |
| 7-8 | fastapi, uvicorn, streamlit, plotly |
| optional | psycopg (PostgreSQL) |

## 5. Milestones

| Phase | Deliverable | Exit test |
|---|---|---|
| 1 Data infrastructure | Ingestion, validation, versioning, quality report | Real data for all eight leagues loaded; re-run changes nothing; report generated. **Done.** |
| 2 Statistical engine | Poisson and Dixon-Coles first, then logistic and Bayesian strengths; score-matrix market probabilities | All market probabilities derive from one score matrix and sum to 1; fitted on data before each match only. **Done.** |
| 3 Market comparison | Margin removal, EV, edge, CLV, cross-bookmaker comparison | Hand-checked examples reproduce exactly. **Done.** Value assessments are computed on demand from stored quotes and forecasts, not stored. |
| 4 Backtesting | Walk-forward backtester with staking and intervals | No future data reachable; results reproducible from a seed and config. **Done.** Backtests are recomputed from stored forecasts and prices; bet ledgers are written as CSV, not stored in tables. |
| 5 Machine learning | Tree models and logistic with rolling validation and calibration | Compared with Phase 2 models on identical out-of-sample matches. **Done**, including the validation-weighted ensemble and its gate. |
| 6 Risk | Fractional Kelly with probability uncertainty, exposure limits, simulation | Limits enforced in tests; paper portfolio ledger. **Done.** Tables `portfolios` and `paper_bets` added; bankroll history is derived from the bet ledger, not stored. |
| 7 Dashboard | Streamlit app, CSV upload screen | Every displayed metric links to its definition. **Done**, with a read-only FastAPI service. |
| 8 Automation | Scheduled ingestion, predictions, weekly audit | Audit states when samples are too small for significance. **Done.** Table `job_runs` added; audit reports are written as files, not stored in a table. |
