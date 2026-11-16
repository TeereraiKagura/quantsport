"""Bookmaker comparison and value assessment on stored quotes and forecasts.

Everything here is computed on demand from the stored odds and the stored,
immutable forecasts, so results are reproducible and nothing is duplicated.

Conventions:
- A "set" is one bookmaker's prices for every outcome of a market at one
  snapshot. Only complete sets are used for margins and fair probabilities.
- The "consensus" fair probability comes from the provider's market-average
  odds, margin removed proportionally.
- The "best price" is the highest price among individual bookmakers. Market
  aggregates are never eligible. Betting exchanges are excluded by default:
  their quotes are before commission and the validator found illiquid,
  implausible exchange prices in this data.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine

EXCHANGES = {"Betfair Exchange"}
CONSENSUS = "Market average"
OUTCOMES = {"1X2": 3, "OU": 2}
SET_KEY = ["match_id", "bookmaker", "market", "line", "snapshot_type"]
SELECTION_KEY = ["match_id", "market", "line", "selection"]

QUOTE_SQL = """
SELECT q.match_id, l.code AS league, m.status, q.bookmaker, q.is_aggregate, q.market, q.line,
       q.selection, q.snapshot_type, q.price, q.observed_at
FROM odds_quotes q
JOIN matches m ON m.id = q.match_id
JOIN leagues l ON l.id = m.league_id
"""

PREDICTION_SQL = """
SELECT p.match_id, l.code AS league, mv.name AS model, mv.id AS model_version_id, mv.params_hash,
       p.created_at, pp.market, pp.line, pp.selection, pp.probability
FROM prediction_probs pp
JOIN predictions p ON p.id = pp.prediction_id
JOIN model_versions mv ON mv.id = p.model_version_id
JOIN leagues l ON l.id = mv.league_id
WHERE p.kind = :kind
"""


def load_quotes(engine: Engine, league_codes: list[str] | None = None) -> pd.DataFrame:
    quotes = pd.read_sql(QUOTE_SQL, engine)
    quotes["is_aggregate"] = quotes.is_aggregate.astype(bool)
    return quotes[quotes.league.isin(league_codes)] if league_codes else quotes


def book_sets(quotes: pd.DataFrame) -> pd.DataFrame:
    """Complete sets only, with booksum, overround and proportional fair probability."""
    q = quotes.assign(implied=1.0 / quotes.price)
    grouped = q.groupby(SET_KEY)
    q["n"] = grouped.price.transform("count")
    q["booksum"] = grouped.implied.transform("sum")
    q = q[q.n == q.market.map(OUTCOMES)].drop(columns="n")
    return q.assign(overround=q.booksum - 1.0, fair_prob=q.implied / q.booksum)


def consensus(quotes: pd.DataFrame, snapshot: str) -> pd.DataFrame:
    """Margin-free market-average probability per selection."""
    sets = book_sets(quotes[(quotes.bookmaker == CONSENSUS) & (quotes.snapshot_type == snapshot)])
    return sets[SELECTION_KEY + ["fair_prob", "price"]].rename(columns={"price": "consensus_price"})


def best_prices(quotes: pd.DataFrame, snapshot: str, include_exchanges: bool = False) -> pd.DataFrame:
    """Highest individual-bookmaker price per selection, and how many quoted it."""
    q = quotes[(quotes.snapshot_type == snapshot) & ~quotes.is_aggregate]
    if not include_exchanges:
        q = q[~q.bookmaker.isin(EXCHANGES)]
    grouped = q.groupby(SELECTION_KEY)
    best = q.loc[grouped.price.idxmax(), SELECTION_KEY + ["league", "status", "bookmaker", "price", "observed_at"]]
    best = best.rename(columns={"bookmaker": "best_bookmaker", "price": "best_price"})
    stats = grouped.price.agg(n_books="count", mean_price="mean").reset_index()
    return best.merge(stats, on=SELECTION_KEY)


def cross_book(best: pd.DataFrame) -> pd.DataFrame:
    """Per match and market: booksum when taking the best price on every
    outcome. Below 1.0 is a theoretical arbitrage across bookmakers."""
    b = best.assign(implied=1.0 / best.best_price)
    out = b.groupby(["match_id", "league", "market", "line"]).agg(
        best_booksum=("implied", "sum"), outcomes=("implied", "count")
    ).reset_index()
    return out[out.outcomes == out.market.map(OUTCOMES)].drop(columns="outcomes")


def movement(quotes: pd.DataFrame) -> pd.DataFrame:
    """Change in consensus fair probability from the pre-closing to the
    closing snapshot. The pre-closing snapshot is not a true opening price."""
    pre = consensus(quotes, "pre_close").rename(columns={"fair_prob": "fair_pre", "consensus_price": "price_pre"})
    close = consensus(quotes, "closing").rename(columns={"fair_prob": "fair_close", "consensus_price": "price_close"})
    m = pre.merge(close, on=SELECTION_KEY)
    return m.assign(prob_change=m.fair_close - m.fair_pre, price_change=m.price_close / m.price_pre - 1.0)


def load_predictions(engine: Engine, kind: str) -> pd.DataFrame:
    """Stored forecasts of the given kind, restricted to each model's most
    recent parameter set (older versions stay in the database untouched)."""
    preds = pd.read_sql(PREDICTION_SQL, engine, params={"kind": kind})
    if preds.empty:
        return preds
    latest = preds.loc[preds.groupby("model").model_version_id.idxmax(), ["model", "params_hash"]]
    return preds.merge(latest, on=["model", "params_hash"])


def value_assessments(
    engine: Engine, kind: str = "walk_forward", league_codes: list[str] | None = None,
    price_snapshot: str = "pre_close",
) -> pd.DataFrame:
    """Each forecast probability against the best available price.

    Columns: probability (model), best_price, best_bookmaker, n_books,
    fair_prob (consensus at the price snapshot), ev, edge, and, where a closing
    consensus exists, closing_fair_prob and clv.
    """
    quotes = load_quotes(engine, league_codes)
    preds = load_predictions(engine, kind)
    if preds.empty or quotes.empty:
        return pd.DataFrame()
    best = best_prices(quotes, price_snapshot).drop(columns="league")
    out = preds.merge(best, on=SELECTION_KEY)
    out = out.merge(consensus(quotes, price_snapshot)[SELECTION_KEY + ["fair_prob"]], on=SELECTION_KEY, how="left")
    closing = consensus(quotes, "closing")[SELECTION_KEY + ["fair_prob"]].rename(
        columns={"fair_prob": "closing_fair_prob"})
    out = out.merge(closing, on=SELECTION_KEY, how="left")
    out["ev"] = out.probability * out.best_price - 1.0
    out["edge"] = out.probability - out.fair_prob
    out["clv"] = out.best_price * out.closing_fair_prob - 1.0
    return out
