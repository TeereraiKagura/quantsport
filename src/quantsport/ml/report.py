"""Phase 5 run: ML walk-forward, ensemble, and the full model comparison."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from quantsport.backtest.engine import MATCH_SQL, split_season
from quantsport.data.leagues import LEAGUES
from quantsport.db.models import utcnow
from quantsport.market import compare
from quantsport.ml import ensemble, pipeline
from quantsport.ml.features import FEATURES
from quantsport.models import walkforward as wf
from quantsport.models.base import Forecast
from quantsport.models.report import _md, _verdict
from quantsport.models.store import get_model_version, save_forecast

ORDER = ["market_close", "ensemble", "dixon_coles", "poisson", "bayesian", "logistic", "ml_logistic",
         "ml_random_forest", "ml_gradient_boosting", "ml_xgboost", "base_rate"]
KEY_OF = {"over": ("OU", 2.5, "over"), "under": ("OU", 2.5, "under"), "yes": ("BTTS", 0.0, "yes"),
          "no": ("BTTS", 0.0, "no"), "H": ("1X2", 0.0, "H"), "D": ("1X2", 0.0, "D"), "A": ("1X2", 0.0, "A")}


def wide_predictions(engine: Engine) -> pd.DataFrame:
    """Stored walk-forward forecasts, one row per (match, model), a column per selection."""
    p = compare.load_predictions(engine, "walk_forward")
    p = p[((p.market == "OU") & (p.line == 2.5)) | p.market.isin(["BTTS", "1X2"])]
    return p.pivot_table(index=["match_id", "league", "model"], columns="selection",
                         values="probability").reset_index().rename_axis(columns=None)


def _splits(engine: Engine, today: date):
    matches = pd.read_sql(MATCH_SQL, engine, parse_dates=["match_date"])
    previous = matches.league.map(lambda c: split_season(c, today, 1))
    current = matches.league.map(lambda c: split_season(c, today, 0))
    return matches, set(matches[matches.season == previous].match_id), set(matches[matches.season == current].match_id)


def _comparison(wide: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    s = wf.score(wide, actual)
    if s.empty:
        return s
    s["verdict"] = s.apply(_verdict, axis=1)
    rank = {m: i for i, m in enumerate(ORDER)}
    s["_r"] = s.model.map(lambda m: rank.get(m, len(rank)))
    s = s.sort_values(["market", "_r"]).drop(columns="_r")
    for col in ("log_loss", "brier", "ll_minus_ref", "ci95_low", "ci95_high"):
        s[col] = s[col].round(4)
    return s


def run(engine: Engine, session: Session, today: date) -> str:
    result = pipeline.run(engine, session, today)
    matches, val_ids, test_ids = _splits(engine, today)
    actual = pd.concat([wf.outcomes(engine, code) for code in LEAGUES], ignore_index=True)
    wide = wide_predictions(engine)
    wide = wide[wide.model != "ensemble"]  # rebuilt below from current weights

    ens = ensemble.build(wide, actual, val_ids, test_ids)
    if len(ens["forecasts"]):
        league_of = matches.set_index("match_id").league
        first_test = matches[matches.match_id.isin(test_ids)].groupby("league").match_date.min()
        params = {"method": "linear pool, log-loss weights fitted on validation season",
                  "weights": {m: w.to_dict() for m, w in ens["weights"].items()}}
        now, versions = utcnow(), {}
        for row in ens["forecasts"].itertuples(index=False):
            league = league_of[row.match_id]
            if league not in versions:
                n_val = max(w.attrs["validation_matches"] for w in ens["weights"].values())
                versions[league] = get_model_version(session, pipeline._Version("ensemble", params), league,
                                                     first_test[league].date(), n_val)
            probs = {KEY_OF[s]: float(getattr(row, s)) for s in KEY_OF}
            save_forecast(session, row.match_id, versions[league], Forecast(None, None, probs),
                          "walk_forward", now)
        session.commit()
        wide = pd.concat([wide, ens["forecasts"].assign(league=ens["forecasts"].match_id.map(league_of))],
                         ignore_index=True)

    market = pd.concat([wf._market_benchmark(engine, code, matches[matches.league == code])
                        for code in LEAGUES], ignore_index=True)
    everything = pd.concat([wide, market], ignore_index=True)
    validation = _comparison(everything[everything.match_id.isin(val_ids) & (everything.model != "ensemble")], actual)
    test = _comparison(everything[everything.match_id.isin(test_ids)], actual)
    gate = ensemble.gate(wide, actual, val_ids, test_ids)

    feats = result["features"]
    usable = feats[feats.usable & (feats.status == "finished")]
    tuning = result["tuning"]
    weights = pd.DataFrame(ens["weights"]).reset_index(names="component") if ens["weights"] else pd.DataFrame()
    now = utcnow()
    return "\n\n".join([
        "# Phase 5 machine-learning and ensemble report",
        f"Generated {now:%Y-%m-%d %H:%M} UTC. All forecasts are after-the-fact walk-forward "
        "reconstructions. No bets or profit appear here; rerun `backtest-report` for that.",
        "## Data and timeline",
        f"- Features: {len(FEATURES)} point-in-time features per match, pooled across all eight leagues. "
        "Bookmaker odds are not used as features.\n"
        f"- Usable finished matches (both teams with at least 5 earlier matches): {len(usable)} "
        f"of {int((feats.status == 'finished').sum())}.\n"
        f"- Tuning window: {int((usable.match_date < result['start']).sum())} matches before "
        f"{result['start']}. Hyperparameters were chosen there and then frozen.\n"
        f"- Walk-forward: models refitted at the start of each calendar month from {result['start']}. "
        "Forecasts in the previous season are validation; the current season is the test.",
        "## Hyperparameter search (rolling-origin validation inside the tuning window)",
        _md(tuning[tuning.chosen].drop(columns="chosen")),
        "Full grid:", _md(tuning),
        "## Effect of probability calibration",
        "Platt scaling fitted on the most recent 20% of each training window, which the base "
        "model did not see. Stored forecasts are the calibrated ones.",
        _md(pipeline.calibration_effect(result, today)),
        "## Feature importance, Over/Under 2.5",
        "Rise in log loss when a feature is shuffled, measured on validation-period matches "
        "with models fitted only on earlier data. Values near zero or negative mean the "
        "feature carries no usable signal for that model.",
        _md(pipeline.permutation_importances(result, today, "over25").head(12)),
        "## Feature importance, match result (1X2)",
        _md(pipeline.permutation_importances(result, today, "result").head(12)),
        "## Model comparison, validation period (previous season from the forecast start)",
        "Identical matches for every model within a market. Reference is the closing market "
        "where prices exist, otherwise the base rate.",
        _md(validation) if not validation.empty else "_No common matches._",
        "## Model comparison, test season",
        _md(test) if not test.empty else "_No common matches._",
        "## Ensemble weights (fitted on validation only)",
        _md(weights.round(3)) if not weights.empty else "_Not enough validation matches to fit an ensemble._",
        "## Ensemble gate: does it replace the best single model?",
        "The best single model is picked on validation. The ensemble becomes the default "
        "only if its test log loss is lower with a 95% interval that excludes zero. This "
        "gate reads the test season once; it is a decision record, not a tuning step.",
        _md(gate) if not gate.empty else "_No ensemble was built._",
    ]) + "\n"
