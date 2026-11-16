"""Walk-forward evaluation report for the Phase 2 models."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from quantsport.data.leagues import LEAGUES, season_label, season_start_year
from quantsport.models import walkforward as wf

ORDER = ["market_close", "dixon_coles", "poisson", "bayesian", "logistic", "base_rate"]


def _md(df: pd.DataFrame) -> str:
    df = df.astype(object).where(df.notna(), "n/a")
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def _verdict(row) -> str:
    if row.model == row.reference:
        return "reference"
    if row.ci95_high < 0:
        return "better than reference"
    if row.ci95_low > 0:
        return "worse than reference"
    return "not distinguishable"


def evaluate(engine: Engine, session: Session | None, league_codes: list[str], today: date,
             seasons_ago: int = 0):
    """Run the walk-forward for each league's current season (seasons_ago=0)
    or an earlier one."""
    preds, actual, tested = [], [], {}
    for code in league_codes:
        league = LEAGUES[code]
        season = season_label(league.season_type, season_start_year(league.season_type, today) - seasons_ago)
        p = wf.run_league(engine, session, code, season)
        preds.append(p)
        actual.append(wf.outcomes(engine, code))
        m = wf.load_matches(engine, code)
        tested[code] = (season, int(((m.status == "finished") & (m.season == season)).sum()))
    return pd.concat(preds, ignore_index=True), pd.concat(actual, ignore_index=True), tested


def render(preds: pd.DataFrame, actual: pd.DataFrame, tested: dict, generated_at: str) -> str:
    pooled = wf.score(preds, actual)
    pooled["verdict"] = pooled.apply(_verdict, axis=1)
    pooled["model"] = pd.Categorical(pooled.model, ORDER, ordered=True)
    pooled = pooled.sort_values(["market", "model"])
    for col in ("log_loss", "brier", "ll_minus_ref", "ci95_low", "ci95_high"):
        pooled[col] = pooled[col].round(4)

    per_league = []
    for code, (season, n_test) in tested.items():
        s = wf.score(preds[preds.league == code], actual, n_boot=1)
        for market, g in s.groupby("market"):
            row = {"league": code, "season": season, "market": market,
                   "finished_matches": n_test, "scored_matches": int(g.n_matches.iloc[0])}
            row.update({m: round(v, 4) for m, v in zip(g.model, g.log_loss)})
            per_league.append(row)
    per_league = pd.DataFrame(per_league)
    cols = [c for c in ["league", "season", "market", "finished_matches", "scored_matches", *ORDER]
            if c in per_league.columns]

    return "\n\n".join([
        "# Phase 2 walk-forward evaluation",
        f"Generated {generated_at} UTC. Every forecast was made by a model refitted only on "
        "matches played before the match date. These are reconstructions made after the "
        "event (kind `walk_forward`), not live predictions, and say nothing yet about "
        "betting profit: no stakes, prices or costs are involved.",
        "## Pooled across leagues",
        "Lower log loss and Brier are better. `ll_minus_ref` is the model's mean log loss "
        "minus the reference's on the same matches; the 95% interval is a paired bootstrap "
        "over matches. A match is scored only if every model produced a forecast for it, "
        "so early-season matches and newly promoted teams are excluded. Over/Under 2.5 "
        "excludes Switzerland and Norway, where no closing price exists to compare with.",
        _md(pooled),
        "## Log loss by league",
        "Samples per league are small; differences here are not individually tested.",
        _md(per_league[cols]),
    ]) + "\n"
