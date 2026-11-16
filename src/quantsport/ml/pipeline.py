"""Machine-learning pipeline: tune, walk forward, calibrate, store.

Timeline (dates derive from today's date; shown for November 2026):

    before 2026-01-01      tuning window. Hyperparameters are chosen here by
                           rolling-origin validation and then frozen.
    2026-01-01 onward      walk-forward forecasts in calendar-month blocks.
                           The model for a month is fitted on every usable
                           match before the first day of that month, pooled
                           across leagues. Features inside the month are still
                           point-in-time (see features.py).

Forecasts in the previous season (January to its end) serve as validation;
forecasts in the current season are the final test. Nothing is tuned on either.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from quantsport.data.leagues import LEAGUES, season_start_year
from quantsport.db.models import utcnow
from quantsport.ml import estimators as est
from quantsport.ml.features import FEATURES, build_features, load_matches
from quantsport.models.base import Forecast
from quantsport.models.store import get_model_version, save_forecast

TARGETS = {
    "over25": [("OU", 2.5, "under"), ("OU", 2.5, "over")],          # class 0, class 1
    "btts": [("BTTS", 0.0, "no"), ("BTTS", 0.0, "yes")],
    "result": [("1X2", 0.0, "H"), ("1X2", 0.0, "D"), ("1X2", 0.0, "A")],
}
MIN_TRAIN_ROWS = 300


class _Version:
    """Identity of a fitted ML model for the model_versions table."""

    def __init__(self, name: str, params: dict):
        self.name, self.params = name, params


def forecast_start(today: date) -> date:
    return date(season_start_year("split", today), 1, 1)


def _xyd(rows: pd.DataFrame, target: str):
    return (rows[FEATURES].to_numpy(dtype=float), rows[target].to_numpy(dtype=int),
            rows.match_date.map(date.toordinal).to_numpy())


def tune(train: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Pick hyperparameters by mean log loss over rolling-origin folds."""
    chosen, table = {}, []
    for target in TARGETS:
        x, y, d = _xyd(train, target)
        folds = list(est.rolling_splits(d))
        for name in est.MODEL_NAMES:
            best = None
            for params in est.grid(name):
                losses = []
                for tr, va in folds:
                    if len(np.unique(y[tr])) < len(np.unique(y)):
                        continue
                    model = est.make(name, params).fit(x[tr], y[tr])
                    losses.append(est.log_loss(model.predict_proba(x[va]), y[va]))
                score = float(np.mean(losses)) if losses else np.inf
                table.append({"target": target, "model": name, "params": params,
                              "folds": len(losses), "cv_log_loss": round(score, 4)})
                if best is None or score < best[1]:
                    best = (params, score)
            chosen[(name, target)] = best[0]
    for row in table:
        row["chosen"] = chosen[(row["model"], row["target"])] == row["params"]
        row["params"] = ", ".join(f"{k}={v}" for k, v in row["params"].items())
    return chosen, pd.DataFrame(table)


def month_blocks(dates: pd.Series, start: date) -> list[tuple[date, date]]:
    """(first day, first day of next month) for every month from `start` that has matches."""
    months = sorted({(d.year, d.month) for d in dates if d >= start})
    return [(date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)) for y, m in months]


def run(engine: Engine, session: Session | None, today: date) -> dict:
    """Tune, walk forward and (if a session is given) store the forecasts.

    Returns the tuning table, the chosen hyperparameters, a frame of forecasts
    (raw and calibrated probabilities per class), and the feature table.
    """
    feats = build_features(load_matches(engine))
    usable = feats[feats.usable]
    finished = usable[usable.status == "finished"]
    start = forecast_start(today)
    tuning_rows = finished[finished.match_date < start]
    if len(tuning_rows) < MIN_TRAIN_ROWS:
        raise RuntimeError(f"Only {len(tuning_rows)} usable matches before {start}; ML models need {MIN_TRAIN_ROWS}")
    chosen, tuning = tune(tuning_rows)

    out = []
    now = utcnow()
    for block_start, block_end in month_blocks(usable.match_date, start):
        train = finished[finished.match_date < block_start]
        block = usable[(usable.match_date >= block_start) & (usable.match_date < block_end)]
        if block.empty or len(train) < MIN_TRAIN_ROWS:
            continue
        xb = block[FEATURES].to_numpy(dtype=float)
        for name in est.MODEL_NAMES:
            probs: dict[tuple, np.ndarray] = {}
            for target, keys in TARGETS.items():
                x, y, d = _xyd(train, target)
                model = est.fit_calibrated(name, chosen[(name, target)], x, y, d)
                cal, raw = model.predict_proba(xb), model.raw_proba(xb)
                for c, key in enumerate(keys):
                    probs[key] = cal[:, c]
                    out.append(pd.DataFrame({"match_id": block.match_id.to_numpy(), "model": name,
                                             "target": target, "klass": c, "raw": raw[:, c], "cal": cal[:, c]}))
            if session is not None:
                params = {"pooled_leagues": True, "features": len(FEATURES), "calibration": "platt",
                          **{t: chosen[(name, t)] for t in TARGETS}}
                versions = {}
                for i, r in enumerate(block.itertuples(index=False)):
                    if r.league not in versions:
                        versions[r.league] = get_model_version(session, _Version(name, params), r.league,
                                                               block_start, len(train))
                    forecast = Forecast(None, None, {key: float(p[i]) for key, p in probs.items()})
                    save_forecast(session, r.match_id, versions[r.league], forecast, "walk_forward", now)
                session.commit()
    return {"tuning": tuning, "chosen": chosen, "forecasts": pd.concat(out, ignore_index=True),
            "features": feats, "start": start}


def stored_hyperparameters(session: Session) -> dict | None:
    """Hyperparameters frozen by the most recent `ml-run`, read back from
    model_versions. None if the ML pipeline has never been run."""
    import json

    from sqlalchemy import select

    from quantsport.db.models import ModelVersion

    chosen = {}
    for name in est.MODEL_NAMES:
        mv = session.scalars(select(ModelVersion).where(ModelVersion.name == name)
                             .order_by(ModelVersion.id.desc())).first()
        if mv is None:
            return None
        params = json.loads(mv.params_json)
        for target in TARGETS:
            chosen[(name, target)] = params[target]
    return chosen


def live_probabilities(feats: pd.DataFrame, chosen: dict, today: date) -> list[tuple[str, pd.DataFrame]]:
    """Fit each model on finished matches before today and forecast usable
    scheduled matches from today onward. Returns (model name, matches, probs)
    triples: `matches` has match_id and league; `probs` maps each
    (market, line, selection) to an array aligned with `matches`."""
    usable = feats[feats.usable]
    train = usable[(usable.status == "finished") & (usable.match_date < today)]
    upcoming = usable[(usable.status == "scheduled") & (usable.match_date >= today)]
    if upcoming.empty or len(train) < MIN_TRAIN_ROWS:
        return []
    xu = upcoming[FEATURES].to_numpy(dtype=float)
    out = []
    for name in est.MODEL_NAMES:
        probs = {}
        for target, keys in TARGETS.items():
            x, y, d = _xyd(train, target)
            proba = est.fit_calibrated(name, chosen[(name, target)], x, y, d).predict_proba(xu)
            for c, key in enumerate(keys):
                probs[key] = proba[:, c]
        out.append((name, upcoming[["match_id", "league"]].reset_index(drop=True), probs))
    return out


def predict_upcoming_ml(engine: Engine, session: Session, today: date) -> int:
    """Store live ML forecasts for scheduled matches. Returns how many were written."""
    chosen = stored_hyperparameters(session)
    if chosen is None:
        return 0
    feats = build_features(load_matches(engine))
    n_train = int((feats.usable & (feats.status == "finished") & (feats.match_date < today)).sum())
    now, written = utcnow(), 0
    for name, frame, probs in live_probabilities(feats, chosen, today):
        params = {"pooled_leagues": True, "features": len(FEATURES), "calibration": "platt",
                  **{t: chosen[(name, t)] for t in TARGETS}}
        versions = {}
        for i, (match_id, league) in enumerate(zip(frame.match_id, frame.league)):
            if league not in versions:
                versions[league] = get_model_version(session, _Version(name, params), league, today, n_train)
            forecast = Forecast(None, None, {key: float(p[i]) for key, p in probs.items()})
            try:
                written += save_forecast(session, int(match_id), versions[league], forecast, "live", now)
            except ValueError:
                continue  # the match has kicked off: too late for a live forecast
    session.commit()
    return written


def calibration_effect(result: dict, today: date) -> pd.DataFrame:
    """Log loss of raw versus calibrated probabilities, by split."""
    feats = result["features"]
    fc = result["forecasts"].merge(feats[["match_id", "league", "season", "status", *TARGETS]], on="match_id")
    fc = fc[fc.status == "finished"]
    current = fc.league.map(lambda c: _season(c, today, 0))
    fc["split"] = np.where(fc.season == current, "test", "validation")
    rows = []
    for (split, model, target), g in fc.groupby(["split", "model", "target"]):
        hit = g[g.klass == g[target].astype(int)]
        rows.append({"split": split, "model": model, "target": target, "matches": len(hit),
                     "raw_log_loss": round(float(-np.log(np.clip(hit.raw, 1e-12, 1)).mean()), 4),
                     "calibrated_log_loss": round(float(-np.log(np.clip(hit.cal, 1e-12, 1)).mean()), 4)})
    out = pd.DataFrame(rows)
    out["calibration_helped"] = out.calibrated_log_loss < out.raw_log_loss
    return out.sort_values(["split", "target", "model"], ascending=[False, True, True])


def _season(league_code: str, today: date, seasons_ago: int) -> str:
    from quantsport.backtest.engine import split_season

    return split_season(league_code, today, seasons_ago)


def permutation_importances(result: dict, today: date, target: str = "over25") -> pd.DataFrame:
    """Rise in log loss when one feature is shuffled, measured on the
    validation period with models fitted only on data before it."""
    from sklearn.inspection import permutation_importance

    feats = result["features"]
    usable = feats[feats.usable & (feats.status == "finished")]
    start = result["start"]
    train = usable[usable.match_date < start]
    previous = usable.league.map(lambda c: _season(c, today, 1))
    held = usable[(usable.match_date >= start) & (usable.season == previous)]
    x, y, _ = _xyd(train, target)
    xh, yh, _ = _xyd(held, target)
    table = {}
    for name in est.MODEL_NAMES:
        model = est.make(name, result["chosen"][(name, target)]).fit(x, y)
        imp = permutation_importance(model, xh, yh, scoring="neg_log_loss", n_repeats=10, random_state=0)
        table[name] = imp.importances_mean
    out = pd.DataFrame(table, index=FEATURES)
    out["mean"] = out.mean(axis=1)
    return out.sort_values("mean", ascending=False).round(4).reset_index(names="feature")
