"""Data-quality report: coverage, missing values and validation issues.

Coverage of a field = finished matches where the field is present / finished
matches, per league and season. Odds coverage counts a match as covered when at
least one non-aggregate bookmaker has a complete set of prices for that market
and snapshot.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine

MATCH_SQL = """
SELECT l.code AS league, l.name AS league_name, m.season, m.id AS match_id, m.status,
       m.match_date, m.kickoff_utc, m.home_goals, m.away_goals, m.ht_home_goals,
       s.home_shots, s.home_sot, s.home_corners, s.home_xg, s.home_possession
FROM matches m
JOIN leagues l ON l.id = m.league_id
LEFT JOIN match_stats s ON s.match_id = m.id
"""

ODDS_SQL = """
SELECT match_id, market, snapshot_type, bookmaker, COUNT(*) AS n
FROM odds_quotes
WHERE is_aggregate = 0
GROUP BY match_id, market, snapshot_type, bookmaker
"""

ISSUE_SQL = """
SELECT l.code AS league, v.severity, v.code, COUNT(*) AS n
FROM validation_issues v
JOIN ingestion_runs r ON r.id = v.run_id
LEFT JOIN leagues l ON l.id = r.league_id
GROUP BY l.code, v.severity, v.code
ORDER BY l.code, v.severity, v.code
"""

COMPLETE = {"1X2": 3, "OU": 2}


def coverage_table(engine: Engine) -> pd.DataFrame:
    matches = pd.read_sql(MATCH_SQL, engine)
    if matches.empty:
        return pd.DataFrame()
    odds = pd.read_sql(ODDS_SQL, engine)
    odds = odds[odds["n"] == odds["market"].map(COMPLETE)]
    for market in ("1X2", "OU"):
        for snapshot in ("pre_close", "closing"):
            covered = set(odds[(odds.market == market) & (odds.snapshot_type == snapshot)].match_id)
            matches[f"{market}_{snapshot}"] = matches.match_id.isin(covered)

    rows = []
    for (league, name, season), g in matches.groupby(["league", "league_name", "season"]):
        fin = g[g.status == "finished"]
        n = len(fin)

        def pct(series: pd.Series) -> float | None:
            return round(100 * series.mean(), 1) if n else None

        rows.append({
            "league": league, "name": name, "season": season,
            "finished": n,
            "scheduled": int((g.status == "scheduled").sum()),
            "awaiting_result": int((g.status == "awaiting_result").sum()),
            "first_date": str(g.match_date.min()), "last_date": str(g.match_date.max()),
            "goals_per_match": round((fin.home_goals + fin.away_goals).mean(), 3) if n else None,
            "kickoff_time_%": pct(fin.kickoff_utc.notna()),
            "half_time_%": pct(fin.ht_home_goals.notna()),
            "shots_%": pct(fin.home_shots.notna()),
            "shots_on_target_%": pct(fin.home_sot.notna()),
            "corners_%": pct(fin.home_corners.notna()),
            "xg_%": pct(fin.home_xg.notna()),
            "possession_%": pct(fin.home_possession.notna()),
            "1X2_pre_close_%": pct(fin["1X2_pre_close"]),
            "1X2_closing_%": pct(fin["1X2_closing"]),
            "OU2.5_pre_close_%": pct(fin["OU_pre_close"]),
            "OU2.5_closing_%": pct(fin["OU_closing"]),
        })
    return pd.DataFrame(rows)


def issue_table(engine: Engine) -> pd.DataFrame:
    return pd.read_sql(ISSUE_SQL, engine)


def _md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_None._"
    df = df.astype(object).where(df.notna(), "n/a")
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def render_report(engine: Engine, generated_at: str) -> str:
    cov = coverage_table(engine)
    if cov.empty:
        return "# Data quality report\n\nNo matches have been ingested yet.\n"
    volume = cov[["league", "name", "season", "finished", "scheduled", "awaiting_result",
                  "first_date", "last_date", "goals_per_match"]]
    stats = cov[["league", "season", "finished", "kickoff_time_%", "half_time_%", "shots_%",
                 "shots_on_target_%", "corners_%", "xg_%", "possession_%"]]
    odds = cov[["league", "season", "finished", "1X2_pre_close_%", "1X2_closing_%",
                "OU2.5_pre_close_%", "OU2.5_closing_%"]]
    return "\n\n".join([
        "# Data quality report",
        f"Generated {generated_at} UTC from the QuantSport database. All figures are "
        "computed from ingested provider data; nothing is estimated or filled in.",
        "## Match volume", _md(volume),
        "## Statistics coverage (% of finished matches with the field present)", _md(stats),
        "## Odds coverage (% of finished matches with a complete set of prices from at "
        "least one individual bookmaker)", _md(odds),
        "## Validation issues by league (error = row rejected)", _md(issue_table(engine)),
    ]) + "\n"
