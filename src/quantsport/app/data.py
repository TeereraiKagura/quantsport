"""Data assembly for the dashboard and API. No presentation code here.

Indicator definitions (also in docs/DASHBOARD.md):

    implied_prob   1 / best price
    fair_prob      market-average pre-match odds with the margin removed
    edge           model probability - fair_prob
    ev             model probability * best price - 1
    n_models       models with a stored forecast for this selection
    disagreement   standard deviation of the probability across those models
    model_error    RMS gap between this model and the closing market's fair
                   probability on the validation season
    sigma          sqrt(disagreement^2 + model_error^2)

Status of a selection, in priority order:
    No price            no individual bookmaker price is stored
    High uncertainty    EV > 0, but (probability - sigma) * price - 1 <= 0:
                        the edge is inside the model's own error
    Positive EV         EV > 0 and it survives the uncertainty adjustment
    Negative EV         EV <= 0
Separate flag:
    model_disagreement  disagreement > DISAGREEMENT_FLAG
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from quantsport.market import compare

DISAGREEMENT_FLAG = 0.05  # display cut: models differ by more than 5 points (1 s.d.)
BENCHMARKS = {"base_rate"}

MATCH_SQL = """
SELECT m.id AS match_id, l.code AS league, l.name AS league_name, m.season, m.match_date,
       m.kickoff_utc, m.status, h.name AS home, a.name AS away, m.home_goals, m.away_goals
FROM matches m
JOIN leagues l ON l.id = m.league_id
JOIN teams h ON h.id = m.home_team_id
JOIN teams a ON a.id = m.away_team_id
"""

XG_SQL = """
SELECT p.match_id, mv.id AS mv_id, p.exp_home_goals AS exp_home, p.exp_away_goals AS exp_away
FROM predictions p JOIN model_versions mv ON mv.id = p.model_version_id
WHERE p.kind = :kind AND mv.name = :model AND p.exp_home_goals IS NOT NULL
"""


def matches(engine: Engine) -> pd.DataFrame:
    return pd.read_sql(MATCH_SQL, engine, parse_dates=["match_date", "kickoff_utc"])


def model_errors(engine: Engine, today: date) -> dict[tuple[str, str], float]:
    """RMS(model probability - closing fair probability) per (model, market),
    on validation-season walk-forward forecasts."""
    from quantsport.ml.report import _splits

    a = compare.value_assessments(engine, "walk_forward")
    if a.empty:
        return {}
    _, validation_ids, _ = _splits(engine, today)
    a = a[a.match_id.isin(validation_ids)].dropna(subset=["closing_fair_prob"])
    gap2 = (a.probability - a.closing_fair_prob) ** 2
    return np.sqrt(gap2.groupby([a.model, a.market]).mean()).to_dict()


def selections(engine: Engine, kind: str, today: date) -> pd.DataFrame:
    """One row per (match, model, market, line, selection) with prices and indicators."""
    preds = compare.load_predictions(engine, kind)
    if preds.empty:
        return pd.DataFrame()
    key = compare.SELECTION_KEY
    quotes = compare.load_quotes(engine)
    best = compare.best_prices(quotes, "pre_close")[key + ["best_price", "best_bookmaker", "n_books"]]
    cons = compare.consensus(quotes, "pre_close")[key + ["fair_prob"]]

    real = preds[~preds.model.isin(BENCHMARKS)]
    spread = real.groupby(key).probability.agg(disagreement=lambda s: s.std(ddof=0), n_models="count").reset_index()

    out = preds[["match_id", "model", "market", "line", "selection", "probability", "created_at"]]
    out = out.merge(matches(engine), on="match_id").merge(best, on=key, how="left")
    out = out.merge(cons, on=key, how="left").merge(spread, on=key, how="left")
    out["implied_prob"] = 1.0 / out.best_price
    out["edge"] = out.probability - out.fair_prob
    out["ev"] = out.probability * out.best_price - 1.0

    errors = model_errors(engine, today)
    out["model_error"] = [errors.get((m, mk), np.nan) for m, mk in zip(out.model, out.market)]
    out["sigma"] = np.sqrt(out.disagreement.fillna(0.0) ** 2 + out.model_error.fillna(0.0) ** 2)
    out.loc[out.model_error.isna(), "sigma"] = np.nan  # unknown, not zero

    conservative_ev = (out.probability - out.sigma.fillna(0.0)) * out.best_price - 1.0
    out["status_label"] = np.select(
        [out.best_price.isna(), (out.ev > 0) & (conservative_ev <= 0), out.ev > 0],
        ["No price", "High uncertainty", "Positive EV"], default="Negative EV")
    out["model_disagreement"] = out.disagreement > DISAGREEMENT_FLAG

    xg = pd.read_sql(XG_SQL, engine, params={"kind": kind, "model": "dixon_coles"})
    if len(xg):
        xg = xg.loc[xg.groupby("match_id").mv_id.idxmax(), ["match_id", "exp_home", "exp_away"]]
        out = out.merge(xg, on="match_id", how="left")
    else:
        out["exp_home"] = out["exp_away"] = np.nan
    out["fixture"] = out.home + " v " + out.away
    out["market_label"] = np.where(out.market == "OU", "Over/Under " + out.line.astype(str),
                                   np.where(out.market == "BTTS", "Both teams to score", "Match result"))
    return out


def missing_forecasts(engine: Engine, kind: str, model: str, scope_ids: set | None = None) -> pd.DataFrame:
    """Matches in scope for which the model stored no forecast (insufficient data)."""
    m = matches(engine)
    m = m[m.status == "scheduled"] if kind == "live" else m[m.status == "finished"]
    if scope_ids is not None:
        m = m[m.match_id.isin(scope_ids)]
    preds = compare.load_predictions(engine, kind)
    have = set(preds[preds.model == model].match_id) if len(preds) else set()
    return m[~m.match_id.isin(have)][["match_date", "league", "home", "away"]].sort_values("match_date")


def match_models(sel: pd.DataFrame, match_id: int, market_label: str) -> pd.DataFrame:
    """Every model's probabilities for one match and market (wide: one column per selection)."""
    s = sel[(sel.match_id == match_id) & (sel.market_label == market_label)]
    return s.pivot_table(index="model", columns="selection", values="probability").reset_index()


def reliability(sel: pd.DataFrame, model: str, market: str, line: float, selection: str, bins: int = 10) -> pd.DataFrame:
    """Calibration table: forecasts grouped into probability bins, with the
    mean forecast and the observed frequency in each bin."""
    from quantsport.backtest.engine import _won

    s = sel[(sel.model == model) & (sel.market == market) & (sel.line == line)
            & (sel.selection == selection) & (sel.status == "finished")].copy()
    if s.empty:
        return pd.DataFrame()
    s["happened"] = _won(market, line, selection, s.home_goals, s.away_goals).astype(float)
    s["bin"] = pd.cut(s.probability, np.linspace(0, 1, bins + 1), include_lowest=True)
    out = s.groupby("bin", observed=True).agg(
        forecasts=("probability", "size"), mean_forecast=("probability", "mean"),
        observed_frequency=("happened", "mean")).reset_index()
    # 95% interval half-width for a proportion: 1.96 * sqrt(f(1-f)/n)
    out["interval"] = 1.96 * np.sqrt(out.observed_frequency * (1 - out.observed_frequency) / out.forecasts)
    out["bin"] = out.bin.astype(str)
    return out


def equity_curve(ledger: pd.DataFrame, initial: float) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame({"match_date": [], "bankroll": []})
    curve = ledger.groupby("match_date", sort=True).bankroll_after.last().reset_index()
    curve.columns = ["match_date", "bankroll"]
    start = pd.DataFrame({"match_date": [curve.match_date.min() - pd.Timedelta(days=1)], "bankroll": [initial]})
    return pd.concat([start, curve], ignore_index=True)
