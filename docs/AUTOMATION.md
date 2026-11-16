# Automation, audit and reliability (Phase 8)

Code: `src/quantsport/jobs/`.

## Jobs

```
python -m quantsport job daily
python -m quantsport job weekly
python -m quantsport job-log        # what ran, when, and whether it worked
```

| Step | Daily | Weekly | What it does |
|---|---|---|---|
| `backup` | yes | yes | copies the database to `data/backups/` (newest 14 kept) |
| `historical_data` | yes | yes | downloads results, statistics and closing odds; unchanged files are skipped |
| `fixtures_and_odds` | yes | yes | downloads upcoming fixtures and their pre-match prices |
| `predictions` | yes | yes | stores live forecasts for scheduled matches (statistical and ML) |
| `paper_trading` | yes | yes | settles finished paper bets and places new ones |
| `performance_monitoring` | | yes | refreshes walk-forward forecasts for newly finished matches |
| `ml_models` | | yes | re-tunes, re-runs and re-compares the ML models and ensemble |
| `weekly_audit` | | yes | writes `reports/weekly_audit_<date>.md` |

- **Isolation.** Each step runs on its own. A failure is written to the
  `job_runs` table and to `logs/quantsport.log`, and the remaining steps still
  run. A provider outage therefore fails the two download steps only.
- **Retries.** Downloads retry with exponential backoff and honour
  `Retry-After` on rate-limit responses.
- **Permanence.** Forecasts are insert-only and timestamped. A live forecast
  is refused once its match has kicked off, so no probability can be written
  or altered after the event.
- **Odds collection.** The current provider supplies prices only inside its
  fixtures and results files, without collection times. There is no separate
  odds feed to poll yet.

## Scheduling

Windows Task Scheduler, via a script you run yourself:

```
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Remove
```

It registers a daily task at 06:00 and a weekly task on Mondays at 07:00 for
the current user. The tasks run only while you are logged in. On Linux or a
server, the equivalent cron lines are:

```
0 6 * * *  cd /path/to/QuantSport && .venv/bin/python -m quantsport job daily
0 7 * * 1  cd /path/to/QuantSport && .venv/bin/python -m quantsport job weekly
```

## Weekly quantitative audit

`python -m quantsport audit` (also the last weekly step). An executive
summary, a scorecard, and ten sections. Each section has a status decided by a
stated rule.

| # | Section | What is measured | Status rule |
|---|---|---|---|
| 1 | Data quality | ingestion runs and rejected rows in 7 days; age of newest result per league | Problem if no successful run; Warning if any failed run, rejected row or league stale over 21 days |
| 2 | Model accuracy | default model's log loss minus the closing market's, test season, 95% paired bootstrap | Problem if the interval is above 0; OK if below; Warning if it spans 0 |
| 3 | Probability calibration | expected calibration error over ten bins | Warning above 0.05 |
| 4 | Betting strategy performance | backtest ROI with interval; paper-trading ledger shown separately | Problem if the ROI interval is below 0; OK if above; Warning if it spans 0 |
| 5 | Closing line value | mean CLV with interval | same rule as ROI |
| 6 | Model deterioration | change in (model - market) log loss, last 28 days against the earlier test season, two-sample bootstrap | Warning if the interval is above 0 |
| 7 | Financial risk | maximum drawdown, longest losing streak against chance, simulated probability of loss | Warning if drawdown exceeds 20% or the streak exceeds 1.5 times chance |
| 8 | Backtesting reliability | share of prices without a collection time; share of matches that could be bet | Warning if any price lacks a time or under 80% of matches are bettable |
| 9 | Potential overfitting | validation ROI against test ROI; number of configurations tried | Warning if validation ROI exceeds test ROI by more than 10 points |
| 10 | Recommended improvements | generated from the findings above | none |

**Insufficient observations.** A section gives no verdict below its minimum
sample: 100 scored matches for accuracy, 200 forecasts for calibration, 30
bets for strategy and CLV, 50 matches on each side for deterioration. The
audit states this explicitly instead of reading meaning into small numbers.

The thresholds (0.05, 20%, 1.5 times, 10 points, 21 days) are conventional
cut-offs chosen in advance, not optimised values.

**Verdict.** The executive summary says there is a predictive advantage only
if model accuracy, strategy performance and closing line value are all OK.

## Security and reliability

| Requirement | State |
|---|---|
| API keys | read from environment variables or a git-ignored `.env`; none in code |
| Configuration | environment variables, template in `.env.example` |
| Database backups | `python -m quantsport backup`, and first step of every job; SQLite only (use `pg_dump` for PostgreSQL) |
| Error logging | `logs/quantsport.log`; job steps in `job_runs`; ingestion in `ingestion_runs` |
| Input validation | every CSV row validated; bad rows rejected and listed; API parameters type-checked |
| Rate limits and failures | backoff and retry on downloads; one request per file with a pause between |
| Provider terms | published download links only; no page scraping; raw data not redistributed |
| Authentication | **not implemented.** The dashboard and API have no login and must stay on your own machine. Needed before any multi-user or cloud deployment. |

## Limitations

- Scheduled tasks have not been registered by the project; you run the script.
- Backups stay on the same disk as the database.
- The ML step of the weekly job re-tunes hyperparameters each week on the
  same tuning window, so its result changes only when new data arrives.
- With no fixtures available from the provider, the prediction and paper
  steps currently have nothing to do.
