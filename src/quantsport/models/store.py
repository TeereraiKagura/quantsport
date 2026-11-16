"""Loading match data for models and storing forecasts permanently."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import pandas as pd
from sqlalchemy import Engine, insert, select
from sqlalchemy.orm import Session

import quantsport
from quantsport.db.models import League, Match, ModelVersion, Prediction, PredictionProb
from quantsport.models.base import Forecast, Model

MATCH_SQL = """
SELECT m.id AS match_id, m.season, m.match_date, m.kickoff_utc, m.status,
       h.name AS home, a.name AS away, m.home_goals, m.away_goals
FROM matches m
JOIN leagues l ON l.id = m.league_id
JOIN teams h ON h.id = m.home_team_id
JOIN teams a ON a.id = m.away_team_id
WHERE l.code = :code
ORDER BY m.match_date, m.id
"""


def load_matches(engine: Engine, league_code: str) -> pd.DataFrame:
    df = pd.read_sql(MATCH_SQL, engine, params={"code": league_code}, parse_dates=["match_date", "kickoff_utc"])
    df["match_date"] = df.match_date.dt.date
    return df


def training_set(matches: pd.DataFrame, before: date) -> pd.DataFrame:
    """Finished matches played strictly before the given date. This is the
    only gate through which models receive data."""
    return matches[(matches.status == "finished") & (matches.match_date < before)]


def get_model_version(session: Session, model: Model, league_code: str, cutoff: date, n_train: int) -> ModelVersion:
    params_json = json.dumps(model.params, sort_keys=True)
    digest = hashlib.sha256(f"{quantsport.__version__}|{model.name}|{params_json}".encode()).hexdigest()
    league_id = session.scalars(select(League.id).where(League.code == league_code)).one()
    mv = session.scalars(
        select(ModelVersion).where(
            ModelVersion.name == model.name, ModelVersion.league_id == league_id,
            ModelVersion.params_hash == digest, ModelVersion.data_cutoff == cutoff,
        )
    ).first()
    if mv is None:
        mv = ModelVersion(name=model.name, league_id=league_id, params_json=params_json,
                          params_hash=digest, data_cutoff=cutoff, n_train=n_train)
        session.add(mv)
        session.flush()
    return mv


def save_forecast(
    session: Session, match_id: int, mv: ModelVersion, forecast: Forecast, kind: str, created_at: datetime
) -> bool:
    """Store a forecast. Returns False if this model version already has one
    for the match (the original is kept). A "live" forecast is refused once
    the match has kicked off."""
    exists = session.scalars(
        select(Prediction.id).where(
            Prediction.match_id == match_id, Prediction.model_version_id == mv.id, Prediction.kind == kind
        )
    ).first()
    if exists:
        return False
    if kind == "live":
        match = session.get(Match, match_id)
        started = (
            created_at >= match.kickoff_utc if match.kickoff_utc else created_at.date() >= match.match_date
        )
        if started or match.status == "finished":
            raise ValueError(f"Match {match_id} has started; a live prediction can no longer be recorded")
    pred = Prediction(match_id=match_id, model_version_id=mv.id, kind=kind, created_at=created_at,
                      exp_home_goals=forecast.exp_home, exp_away_goals=forecast.exp_away)
    session.add(pred)
    session.flush()
    session.execute(insert(PredictionProb), [
        {"prediction_id": pred.id, "market": m, "line": line, "selection": s, "probability": p}
        for (m, line, s), p in forecast.probs.items()
    ])
    return True
