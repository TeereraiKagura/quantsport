"""A plain report of the stored live forecasts for upcoming fixtures."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import Engine

from quantsport.app import data
from quantsport.models.report import _md
from quantsport.risk.paper import DEFAULT_MODELS

GOAL_MODEL = "dixon_coles"


def table(engine: Engine, today: date, days_ahead: int = 10) -> pd.DataFrame:
    """One row per upcoming fixture: expected goals, the default model's
    probability for each market, and how far the models disagree."""
    sel = data.selections(engine, "live", today)
    if sel.empty:
        return pd.DataFrame()
    end = pd.Timestamp(today + timedelta(days=days_ahead))
    sel = sel[(sel.status == "scheduled") & (sel.match_date >= pd.Timestamp(today)) & (sel.match_date <= end)]
    if sel.empty:
        return pd.DataFrame()
    wanted = {("OU", 2.5, "over"): ("Over 2.5", DEFAULT_MODELS["OU"]),
              ("BTTS", 0.0, "yes"): ("BTTS yes", "bayesian"),
              ("1X2", 0.0, "H"): ("Home", DEFAULT_MODELS["1X2"]),
              ("1X2", 0.0, "D"): ("Draw", DEFAULT_MODELS["1X2"]),
              ("1X2", 0.0, "A"): ("Away", DEFAULT_MODELS["1X2"])}
    rows = []
    for match_id, g in sel.groupby("match_id"):
        first = g.iloc[0]
        row = {"Date": first.match_date.date(),
               "Kick-off (UTC)": "" if pd.isna(first.kickoff_utc) else f"{first.kickoff_utc:%H:%M}",
               "League": first.league, "Fixture": first.fixture,
               "Exp. goals": "" if pd.isna(first.exp_home) else f"{first.exp_home:.2f} - {first.exp_away:.2f}"}
        spread = []
        for (market, line, selection), (label, model) in wanted.items():
            s = g[(g.market == market) & (g.line == line) & (g.selection == selection)]
            mine = s[s.model == model]
            row[label] = "n/a" if mine.empty else f"{mine.probability.iloc[0]:.0%}"
            if len(s) and pd.notna(s.disagreement.iloc[0]):
                spread.append(s.disagreement.iloc[0])
        row["Max disagreement"] = f"{max(spread):.3f}" if spread else "n/a"
        row["Models"] = int(g.model.nunique())
        row["Price"] = "yes" if g.best_price.notna().any() else "none"
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["Date", "League", "Kick-off (UTC)", "Fixture"])


def render(engine: Engine, today: date, days_ahead: int = 10) -> str:
    t = table(engine, today, days_ahead)
    head = [f"# Forecasts for upcoming fixtures, {today:%d %B %Y}",
            "Live forecasts: every probability below was stored before kick-off and cannot be changed. "
            f"Over 2.5 is from `{DEFAULT_MODELS['OU']}`, the match result from `{DEFAULT_MODELS['1X2']}`, both "
            f"teams to score from `bayesian`, and expected goals from `{GOAL_MODEL}` (the default model per market). "
            "`Max disagreement` is the largest standard deviation across all models for any of these outcomes; "
            "above 0.05 the models materially disagree."]
    if t.empty:
        return "\n\n".join(head + ["_No live forecasts are stored for upcoming fixtures._"]) + "\n"
    priced = int((t.Price == "yes").sum())
    notes = [
        "**These are forecasts, not betting recommendations.** On this season's out-of-sample matches every one "
        "of these models was measurably less accurate than the closing bookmaker odds.",
        f"{len(t)} fixtures; {priced} have a stored bookmaker price. Without a price no expected value can be "
        "calculated.",
        "Fixture dates come from schedule feeds and can change. `ingest-fixturedownload` and "
        "`ingest-openfootball` report, per league, how often the feed's date matched the real one on matches "
        "already played.",
    ]
    return "\n\n".join(head + notes + [_md(t)]) + "\n"
