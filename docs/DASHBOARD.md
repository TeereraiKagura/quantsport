# Dashboard and API (Phase 7)

## Running

```
python -m streamlit run src/quantsport/app/dashboard.py     # dashboard, http://localhost:8501
python -m uvicorn quantsport.app.api:app --port 8000        # API, docs at http://localhost:8000/docs
```

Code: `src/quantsport/app/`. `data.py` assembles every table and indicator
(and is unit-tested); `dashboard.py` only presents them; `api.py` exposes the
same data read-only.

## Pages

| Page | Contents |
|---|---|
| Fixtures and value | Upcoming fixtures with live forecasts, or a historical reconstruction from walk-forward forecasts. Filters: model, league, market, team, date range, minimum EV, minimum odds, status. Per-match chart of every model's probabilities. |
| Model comparison | Log loss and Brier score for every model against the closing market, test and validation seasons, plus a calibration chart. |
| Backtesting | Choose model, market, season, leagues, EV threshold, odds range, price source, staking and commission; shows the summary, equity curve and a downloadable bet ledger. |
| Risk and paper trading | Paper portfolio status and stake review; the latest risk report. |
| Data | Coverage, validation issues, ingestion runs, and CSV upload. |
| Definitions | The project's definition documents, readable in the app. |

## Indicators on the fixtures page

No arbitrary confidence score is shown. Each indicator is a defined quantity.

| Column | Definition |
|---|---|
| Model prob. | the selected model's stored probability |
| Exp. home / away goals | expected goals from the Dixon-Coles forecast for the match |
| Best odds, Bookmaker | highest pre-match price among individual bookmakers (aggregates and the exchange excluded) |
| Implied prob. | `1 / best odds` |
| Market fair prob. | market-average pre-match odds with the margin removed proportionally |
| Edge | model probability minus market fair probability |
| EV | `model probability x best odds - 1` |
| Models | number of models with a stored forecast for the selection |
| Disagreement | standard deviation of the probability across those models |
| Uncertainty (sigma) | `sqrt(disagreement^2 + model_error^2)`; `model_error` is the RMS gap between the model and the closing market on the validation season. Shown as n/a when no validation history exists: unknown is not treated as zero. |

### Status

| Status | Rule |
|---|---|
| No price | no individual bookmaker price is stored for the selection |
| High uncertainty | EV > 0, but `(probability - sigma) x odds - 1 <= 0`: the edge is inside the model's own error |
| Positive EV | EV > 0 and still positive after subtracting one sigma |
| Negative EV | EV <= 0 |

`Models disagree` is a separate flag, set when disagreement exceeds 0.05
(five percentage points of standard deviation). That value is a display cut,
not a tuned parameter.

**Insufficient data** is listed under the table: matches for which the
selected model stored no forecast, because a team had too few earlier matches.

Status is shown as text as well as colour.

## What "upcoming" needs

The upcoming view shows forecasts stored before kick-off (`predict-upcoming`)
for fixtures loaded by `ingest-fixtures`. When the provider lists no fixtures
for the tracked leagues, the page says so instead of showing anything
invented. The historical view is always labelled as a reconstruction.

## API

Read-only. `GET /health`, `/leagues`, `/matches`, `/selections`. Interactive
documentation is generated at `/docs`. There is no authentication yet; do not
expose it beyond your own machine.

## Limitations

- All expected value is theoretical: stored prices carry no collection time.
- The dashboard caches loaded data for ten minutes.
- No user accounts or authentication.
