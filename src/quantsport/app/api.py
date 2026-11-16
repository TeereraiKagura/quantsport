"""Read-only HTTP API. Interactive documentation is served at /docs.

Run:  python -m uvicorn quantsport.app.api:app --port 8000
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Literal

import pandas as pd
from fastapi import FastAPI, Query

from quantsport.app import data
from quantsport.config import get_settings
from quantsport.data.leagues import LEAGUES
from quantsport.db import init_db, make_engine

app = FastAPI(
    title="QuantSport API",
    version="0.1.0",
    description="Read-only access to stored matches, forecasts and value assessments. Research and paper "
                "trading only. Expected value is theoretical: stored prices were never verified as obtainable.",
)


@lru_cache
def get_engine():
    engine = make_engine(get_settings().database_url)
    init_db(engine)
    return engine


def _records(df: pd.DataFrame, limit: int) -> list[dict]:
    return json.loads(df.head(limit).to_json(orient="records", date_format="iso"))


@app.get("/health")
def health() -> dict:
    """Service status and how many matches and forecasts are stored."""
    engine = get_engine()
    counts = pd.read_sql("SELECT (SELECT COUNT(*) FROM matches) AS matches, "
                         "(SELECT COUNT(*) FROM predictions) AS predictions", engine).iloc[0]
    return {"status": "ok", "matches": int(counts.matches), "predictions": int(counts.predictions)}


@app.get("/leagues")
def leagues() -> list[dict]:
    """Tracked competitions."""
    return [{"code": lg.code, "name": lg.name, "country": lg.country} for lg in LEAGUES.values()]


@app.get("/matches")
def matches(league: str | None = None, status: Literal["finished", "scheduled", "awaiting_result"] | None = None,
            limit: int = Query(200, le=2000)) -> list[dict]:
    """Stored matches, most recent first."""
    m = data.matches(get_engine())
    if league:
        m = m[m.league == league]
    if status:
        m = m[m.status == status]
    return _records(m.sort_values("match_date", ascending=False), limit)


@app.get("/selections")
def selections(kind: Literal["live", "walk_forward"] = "live", model: str | None = None, league: str | None = None,
               min_ev: float | None = None, min_odds: float | None = None,
               limit: int = Query(200, le=5000)) -> list[dict]:
    """Forecast probabilities with best price, implied and fair probability, edge, expected value,
    model disagreement, uncertainty and status. `live` forecasts were stored before kick-off;
    `walk_forward` ones are after-the-fact reconstructions."""
    s = data.selections(get_engine(), kind, date.today())
    if s.empty:
        return []
    if model:
        s = s[s.model == model]
    if league:
        s = s[s.league == league]
    if min_ev is not None:
        s = s[s.ev >= min_ev]
    if min_odds is not None:
        s = s[s.best_price >= min_odds]
    cols = ["match_id", "match_date", "league", "home", "away", "model", "market", "line", "selection",
            "probability", "exp_home", "exp_away", "best_price", "best_bookmaker", "implied_prob", "fair_prob",
            "edge", "ev", "n_models", "disagreement", "sigma", "model_disagreement", "status_label"]
    return _records(s.sort_values("match_date", ascending=False)[cols], limit)
