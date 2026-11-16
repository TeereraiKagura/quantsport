# QuantSport

Quantitative sports intelligence and prediction research platform for football.
It estimates match probabilities, compares them with bookmaker prices and tests
whether any apparent edge survives honest out-of-sample evaluation.

**Research and paper trading only. No real-money betting. No profitability is
claimed anywhere in this project unless it is backed by a stored, reproducible
result with a sample size and confidence interval.**

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Data infrastructure | Done |
| 2 | Statistical prediction engine | Done |
| 3 | Probability and odds comparison | Done |
| 4 | Backtesting | Done |
| 5 | Machine learning models and ensemble | Done |
| 6 | Risk management | Done |
| 7 | Interactive dashboard | Done |
| 8 | Automation and reporting | Done |

Leagues: Premier League, La Liga, Bundesliga, Serie A, Eredivisie, Super Lig,
Swiss Super League, Eliteserien. Scope: current season and the one before.

## Setup

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
copy .env.example .env
```

## Commands

```
python -m quantsport ingest                 # download results and odds, all leagues
python -m quantsport ingest --leagues E0    # one league
python -m quantsport ingest-fixtures        # upcoming fixtures
python -m quantsport ingest-csv file.csv --league E0 --season 2025/2026
python -m quantsport quality-report         # coverage and validation report
python -m quantsport runs                   # ingestion audit trail
python -m quantsport strengths --league E0  # team attack/defence strengths
python -m quantsport walk-forward           # out-of-sample model evaluation
python -m quantsport predict-upcoming       # store live forecasts for fixtures
python -m quantsport market-report          # margins, dispersion, movement, value screen
python -m quantsport value --min-ev 0.05    # forecasts with positive expected value
python -m quantsport walk-forward --season previous   # validation-season forecasts
python -m quantsport backtest --model dixon_coles --market OU2.5 --split validation
python -m quantsport backtest-report        # validation-then-test backtest, all models
python -m quantsport ml-run                 # tune, walk forward and compare ML models + ensemble
python -m quantsport risk-report            # staking policies, Monte Carlo, correlation
python -m quantsport paper status --name main   # paper-trading portfolio (create/place/settle/status)
python -m quantsport job daily              # backup, data, fixtures, live forecasts, paper bets
python -m quantsport job weekly             # daily steps + monitoring, ML comparison, weekly audit
python -m quantsport audit                  # weekly quantitative audit on its own
python -m quantsport backup                 # database backup
python -m quantsport job-log                # recent job steps
python -m pytest                            # tests
python -m streamlit run src/quantsport/app/dashboard.py   # dashboard
python -m uvicorn quantsport.app.api:app --port 8000      # read-only API, docs at /docs
```

## What Phase 1 guarantees

- Every stored row traces to a source and an ingestion run; every downloaded
  file is archived with its SHA-256.
- Rows that contradict themselves (for example a result flag that disagrees
  with the score) are rejected and logged, not repaired.
- Missing values stay NULL and are measured in the quality report.
- Re-running ingestion is idempotent. A changed record gets a new version and
  the old content is kept.

## Documentation

- [Architecture, schema and milestones](docs/ARCHITECTURE.md)
- [Data sources, coverage and licensing](docs/DATA_SOURCES.md)
- [Model and metric definitions](docs/MODELS.md)
- [Market definitions: margin, EV, CLV, executability](docs/MARKET.md)
- [Backtesting rules, metrics and protocol](docs/BACKTEST.md)
- [Machine learning features, tuning, calibration and ensemble](docs/ML.md)
- [Risk: staking, limits, monitoring, paper trading](docs/RISK.md)
- [Dashboard indicators and API](docs/DASHBOARD.md)
- [Automation, weekly audit, security and reliability](docs/AUTOMATION.md)
