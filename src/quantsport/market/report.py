"""Market intelligence report: margins, price dispersion, movement, value screen."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from quantsport.market import compare
from quantsport.models.report import _md

MODEL_ORDER = ["dixon_coles", "poisson", "bayesian", "logistic", "base_rate"]


def margins(quotes: pd.DataFrame) -> pd.DataFrame:
    sets = compare.book_sets(quotes).drop_duplicates(compare.SET_KEY)
    out = sets.groupby(["bookmaker", "market", "snapshot_type"]).overround.agg(
        sets="count", mean_overround_pct=lambda s: 100 * s.mean(), median_overround_pct=lambda s: 100 * s.median()
    ).reset_index()
    return out.sort_values(["market", "snapshot_type", "mean_overround_pct"]).round(2)


def dispersion(quotes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for snapshot in ("pre_close", "closing"):
        best = compare.best_prices(quotes, snapshot)
        if best.empty:
            continue
        cross = compare.cross_book(best)
        best = best[best.n_books >= 2]
        for market, g in best.groupby("market"):
            c = cross[cross.market == market]
            rows.append({
                "market": market, "snapshot": snapshot, "selections": len(g),
                "mean_books_quoting": round(g.n_books.mean(), 1),
                "best_vs_mean_price_pct": round(100 * (g.best_price / g.mean_price - 1).mean(), 2),
                "matches": len(c),
                "mean_best_booksum": round(c.best_booksum.mean(), 4),
                "pct_matches_booksum_below_1": round(100 * (c.best_booksum < 1).mean(), 1),
            })
    return pd.DataFrame(rows)


def movement_summary(quotes: pd.DataFrame) -> pd.DataFrame:
    m = compare.movement(quotes)
    rows = []
    for market, g in m.groupby("market"):
        rows.append({
            "market": market, "selections": len(g),
            "mean_abs_prob_change_pp": round(100 * g.prob_change.abs().mean(), 2),
            "pct_moved_over_2pp": round(100 * (g.prob_change.abs() > 0.02).mean(), 1),
            "pct_moved_over_5pp": round(100 * (g.prob_change.abs() > 0.05).mean(), 1),
        })
    return pd.DataFrame(rows)


def _clustered_mean_ci(values: pd.Series, clusters: pd.Series, rng, n_boot: int = 5000):
    """Mean with a 95% bootstrap interval that resamples whole matches, since
    selections within one match are not independent."""
    per = pd.DataFrame({"v": values, "c": clusters}).groupby("c").v.agg(["sum", "count"]).to_numpy()
    draws = rng.integers(0, len(per), size=(n_boot, len(per)))
    means = per[draws, 0].sum(axis=1) / per[draws, 1].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return values.mean(), lo, hi


def value_screen(assess: pd.DataFrame, thresholds=(0.0, 0.05), seed: int = 12345) -> pd.DataFrame:
    """For each model and market: how often it flags positive EV at the best
    pre-closing price, and whether the closing market agreed (CLV)."""
    rng = np.random.default_rng(seed)
    a = assess.dropna(subset=["clv"])
    a = a[((a.market == "OU") & (a.line == 2.5)) | (a.market == "1X2")]
    rows = []
    for (market, model), g in a.groupby(["market", "model"]):
        base, base_lo, base_hi = _clustered_mean_ci(g.clv, g.match_id, rng)
        rows.append({"market": market, "model": model, "subset": "all selections", "selections": len(g),
                     "matches": g.match_id.nunique(), "mean_ev_pct": round(100 * g.ev.mean(), 2),
                     "mean_clv_pct": round(100 * base, 2), "clv_ci95_low": round(100 * base_lo, 2),
                     "clv_ci95_high": round(100 * base_hi, 2),
                     "pct_beating_close": round(100 * (g.clv > 0).mean(), 1)})
        for t in thresholds:
            f = g[g.ev > t]
            if len(f) < 2 or f.match_id.nunique() < 2:
                continue
            mean, lo, hi = _clustered_mean_ci(f.clv, f.match_id, rng)
            rows.append({"market": market, "model": model, "subset": f"model EV > {t:.0%}", "selections": len(f),
                         "matches": f.match_id.nunique(), "mean_ev_pct": round(100 * f.ev.mean(), 2),
                         "mean_clv_pct": round(100 * mean, 2), "clv_ci95_low": round(100 * lo, 2),
                         "clv_ci95_high": round(100 * hi, 2),
                         "pct_beating_close": round(100 * (f.clv > 0).mean(), 1)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    rank = {name: i for i, name in enumerate(MODEL_ORDER)}
    out["_rank"] = out.model.map(lambda name: rank.get(name, len(rank)))
    return out.sort_values(["market", "_rank", "model", "subset"]).drop(columns="_rank")


def render(engine: Engine, generated_at: str) -> str:
    quotes = compare.load_quotes(engine)
    assess = compare.value_assessments(engine, "walk_forward")
    screen = value_screen(assess) if not assess.empty else pd.DataFrame()
    return "\n\n".join([
        "# Phase 3 market intelligence report",
        f"Generated {generated_at} UTC from stored odds and stored walk-forward forecasts. "
        "All prices are historical and carry no collection time, so every expected value "
        "below is **theoretical**: none of it was an executable opportunity. No bets are "
        "simulated and no profit is calculated here; that is Phase 4.",
        "## Bookmaker margins",
        "Overround = sum of implied probabilities minus 1, per complete set of prices. "
        "\"Market maximum\" is an aggregate of best prices, not a bookmaker.",
        _md(margins(quotes)),
        "## Price dispersion between bookmakers",
        "Individual bookmakers only; aggregates and the betting exchange are excluded. "
        "`best_vs_mean_price_pct` is how far the best price sits above the average price "
        "for the same selection. `mean_best_booksum` takes the best price on every outcome; "
        "below 1 would be an arbitrage on paper, but these prices were not observed at the "
        "same moment and may never have been available together.",
        _md(dispersion(quotes)),
        "## Movement from pre-closing to closing",
        "Change in the margin-free market-average probability. The pre-closing snapshot is "
        "taken some days before kick-off; it is not the opening price.",
        _md(movement_summary(quotes)),
        "## Value screen on walk-forward forecasts",
        "Each forecast is compared with the best pre-closing price: EV = p x price - 1. "
        "CLV = price x closing fair probability - 1, i.e. the same bet valued by the closing "
        "market instead of by the model. If a model's positive-EV selections do not show "
        "better CLV than taking the best price on everything (`all selections`), the "
        "apparent value is model error, not edge. Intervals are 95% bootstraps resampling "
        "whole matches. Switzerland and Norway are absent: no pre-closing prices exist. "
        "The EV thresholds are reporting cuts, not optimised values.",
        _md(screen) if not screen.empty else "_No stored forecasts with matching prices._",
    ]) + "\n"
