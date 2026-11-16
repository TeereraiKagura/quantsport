"""Walk-forward (expanding window) out-of-sample evaluation and live prediction.

For every match date d in the test season, each model is refitted on finished
matches played strictly before d and then forecasts the matches on d. No
parameter is chosen using the test matches.

Scoring rules (lower is better):
    log loss  = -ln(probability given to the outcome that happened)
    Brier     = sum over outcomes of (probability - indicator)^2
                (binary markets: (p - y)^2 on the 'yes' outcome)

Benchmarks:
    base_rate    - league outcome frequencies in the training data
    market_close - closing "market average" odds with the margin removed by
                   proportional normalisation: p_i = (1/o_i) / sum_j (1/o_j)
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from quantsport.db.models import utcnow
from quantsport.models import default_models
from quantsport.models.store import get_model_version, load_matches, save_forecast, training_set

log = logging.getLogger(__name__)

MIN_TRAIN_MATCHES = 100
MARKETS = {"OU2.5": ["over", "under"], "BTTS": ["yes", "no"], "1X2": ["H", "D", "A"]}
KEYS = {
    "over": ("OU", 2.5, "over"), "under": ("OU", 2.5, "under"),
    "yes": ("BTTS", 0.0, "yes"), "no": ("BTTS", 0.0, "no"),
    "H": ("1X2", 0.0, "H"), "D": ("1X2", 0.0, "D"), "A": ("1X2", 0.0, "A"),
}

MARKET_SQL = """
SELECT q.match_id, q.market, q.selection, q.price
FROM odds_quotes q JOIN matches m ON m.id = q.match_id JOIN leagues l ON l.id = m.league_id
WHERE l.code = :code AND q.bookmaker = 'Market average' AND q.snapshot_type = 'closing'
"""


def run_league(engine: Engine, session: Session | None, league_code: str, test_season: str) -> pd.DataFrame:
    """Forecast every finished match of test_season. One row per (match, model)
    with the probability of each selection. Stores forecasts if a session is given."""
    matches = load_matches(engine, league_code)
    test = matches[(matches.status == "finished") & (matches.season == test_season)]
    models = default_models()
    now = utcnow()
    rows = []
    for day in sorted(test.match_date.unique()):
        train = training_set(matches, day)
        if len(train) < MIN_TRAIN_MATCHES:
            continue
        for model in models:
            model.fit(train, day)
            mv = None
            for m in test[test.match_date == day].itertuples(index=False):
                forecast = model.predict(m.home, m.away)
                if forecast is None:
                    continue
                if session is not None:
                    mv = mv or get_model_version(session, model, league_code, day, len(train))
                    save_forecast(session, m.match_id, mv, forecast, "walk_forward", now)
                rows.append({"match_id": m.match_id, "league": league_code, "model": model.name,
                             **{sel: forecast.probs[key] for sel, key in KEYS.items()}})
        if session is not None:
            session.commit()
    preds = pd.DataFrame(rows)
    return pd.concat([preds, _market_benchmark(engine, league_code, test)], ignore_index=True)


def _market_benchmark(engine: Engine, league_code: str, test: pd.DataFrame) -> pd.DataFrame:
    odds = pd.read_sql(MARKET_SQL, engine, params={"code": league_code})
    odds = odds[odds.match_id.isin(test.match_id)]
    if odds.empty:
        return pd.DataFrame()
    inv = (1.0 / odds.pivot_table(index="match_id", columns="selection", values="price")).reindex(columns=list(KEYS))
    out = pd.DataFrame(index=inv.index)
    for selections in (["over", "under"], ["H", "D", "A"]):  # no BTTS prices in the data
        block = inv[selections]
        out[selections] = block.div(block.sum(axis=1, skipna=False), axis=0)
    out["yes"] = out["no"] = np.nan
    return out.assign(league=league_code, model="market_close").reset_index()


def outcomes(engine: Engine, league_code: str) -> pd.DataFrame:
    m = load_matches(engine, league_code)
    m = m[m.status == "finished"]
    hg, ag = m.home_goals, m.away_goals
    return pd.DataFrame({
        "match_id": m.match_id,
        "OU2.5": np.where(hg + ag > 2.5, "over", "under"),
        "BTTS": np.where((hg > 0) & (ag > 0), "yes", "no"),
        "1X2": np.where(hg > ag, "H", np.where(ag > hg, "A", "D")),
    })


def score(preds: pd.DataFrame, actual: pd.DataFrame, n_boot: int = 5000, seed: int = 12345) -> pd.DataFrame:
    """Score every model on the same matches per market.

    A match counts for a market only if every model (and the market benchmark,
    where prices exist for that market) produced a probability, so all rows of
    one market are directly comparable. The 95% interval is a paired bootstrap
    over matches of (model log loss - reference log loss)."""
    df = preds.merge(actual, on="match_id")
    rng = np.random.default_rng(seed)
    out = []
    for market, selections in MARKETS.items():
        if df.empty or not set(selections) <= set(df.columns):
            continue  # nothing stored for this market
        sub = df.dropna(subset=selections)
        n_models = sub.model.nunique()
        common = sub.groupby("match_id").model.nunique()
        sub = sub[sub.match_id.isin(common[common == n_models].index)]
        if sub.empty:
            continue
        p = sub[selections].to_numpy()
        hit = (sub[market].to_numpy()[:, None] == np.array(selections)[None, :]).astype(float)
        sub = sub.assign(
            logloss=-np.log(np.clip((p * hit).sum(axis=1), 1e-12, 1)),
            brier=((p - hit) ** 2).sum(axis=1) if len(selections) > 2 else (p[:, 0] - hit[:, 0]) ** 2,
        )
        ll = sub.pivot(index="match_id", columns="model", values="logloss")
        br = sub.pivot(index="match_id", columns="model", values="brier")
        reference = "market_close" if "market_close" in ll.columns else "base_rate"
        n = len(ll)
        draws = rng.integers(0, n, size=(n_boot, n))
        for model in ll.columns:
            diff = (ll[model] - ll[reference]).to_numpy()
            lo, hi = np.percentile(diff[draws].mean(axis=1), [2.5, 97.5]) if model != reference else (0.0, 0.0)
            out.append({"market": market, "model": model, "n_matches": n,
                        "log_loss": ll[model].mean(), "brier": br[model].mean(),
                        "reference": reference, "ll_minus_ref": diff.mean(), "ci95_low": lo, "ci95_high": hi})
    return pd.DataFrame(out)


def predict_upcoming(engine: Engine, session: Session, league_code: str, today: date) -> int:
    """Store live forecasts for scheduled matches from today onward. Returns
    the number of new forecasts written."""
    matches = load_matches(engine, league_code)
    upcoming = matches[(matches.status == "scheduled") & (matches.match_date >= today)]
    train = training_set(matches, today)
    if upcoming.empty or len(train) < MIN_TRAIN_MATCHES:
        return 0
    written = 0
    now = utcnow()
    for model in default_models():
        model.fit(train, today)
        mv = None
        for m in upcoming.itertuples(index=False):
            if pd.notna(m.kickoff_utc) and m.kickoff_utc <= now:
                continue
            forecast = model.predict(m.home, m.away)
            if forecast is None:
                continue
            mv = mv or get_model_version(session, model, league_code, today, len(train))
            written += save_forecast(session, m.match_id, mv, forecast, "live", now)
    session.commit()
    return written
