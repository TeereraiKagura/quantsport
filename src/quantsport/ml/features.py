"""Point-in-time feature table for the machine-learning models.

Every feature of a match is computed from matches played on earlier dates
only. Matches are processed one date at a time: features for all of a date's
matches are written first, and only then are that date's results added to
the team histories. Bookmaker odds are deliberately not features, so the
models stay independent of the market they are compared with.

Features (h_ = home team, a_ = away team):
    gf5, ga5, gf10, ga10   mean goals for/against, last 5 and 10 matches
    sh10, sha10            mean shots for/against, last 10 (NaN if no shot data)
    sot10, sota10          mean shots on target for/against, last 10
    pts10                  mean points per match, last 10
    h_home_gf5, h_home_ga5 home team's last 5 home matches
    a_away_gf5, a_away_ga5 away team's last 5 away matches
    rest                   days since the team's previous match, capped at 30
    elo_diff               home Elo minus away Elo before the match
    league_gpm             league's mean goals per match before this date

Elo: every team starts at 1500; expected home score
E = 1 / (1 + 10 ** (-(R_home + 60 - R_away) / 400)); after a match each rating
moves by 20 * (actual - expected), with actual = 1, 0.5 or 0.

A row is usable only when both teams have at least MIN_HISTORY earlier matches.
"""

from __future__ import annotations

from collections import defaultdict, deque

import numpy as np
import pandas as pd
from sqlalchemy import Engine

MIN_HISTORY = 5
ELO_START, ELO_K, ELO_HOME = 1500.0, 20.0, 60.0

SQL = """
SELECT m.id AS match_id, l.code AS league, m.season, m.match_date, m.status,
       h.name AS home, a.name AS away, m.home_goals, m.away_goals,
       s.home_shots, s.away_shots, s.home_sot, s.away_sot
FROM matches m
JOIN leagues l ON l.id = m.league_id
JOIN teams h ON h.id = m.home_team_id
JOIN teams a ON a.id = m.away_team_id
LEFT JOIN match_stats s ON s.match_id = m.id
ORDER BY m.match_date, m.id
"""

TEAM_FEATURES = ["gf5", "ga5", "gf10", "ga10", "sh10", "sha10", "sot10", "sota10", "pts10", "rest"]
FEATURES = (
    [f"h_{f}" for f in TEAM_FEATURES] + [f"a_{f}" for f in TEAM_FEATURES]
    + ["h_home_gf5", "h_home_ga5", "a_away_gf5", "a_away_ga5", "elo_diff", "league_gpm"]
)
RESULT_CODES = {"H": 0, "D": 1, "A": 2}


def load_matches(engine: Engine) -> pd.DataFrame:
    df = pd.read_sql(SQL, engine, parse_dates=["match_date"])
    df["match_date"] = df.match_date.dt.date
    return df


def _mean(values) -> float:
    values = [v for v in values if v is not None and not pd.isna(v)]
    return float(np.mean(values)) if values else np.nan


def _team_features(history: deque, venue_history: deque, day) -> dict:
    if len(history) < MIN_HISTORY:
        return {}
    last5, last10 = list(history)[-5:], list(history)
    out = {
        "gf5": _mean(m["gf"] for m in last5), "ga5": _mean(m["ga"] for m in last5),
        "gf10": _mean(m["gf"] for m in last10), "ga10": _mean(m["ga"] for m in last10),
        "sh10": _mean(m["sh"] for m in last10), "sha10": _mean(m["sha"] for m in last10),
        "sot10": _mean(m["sot"] for m in last10), "sota10": _mean(m["sota"] for m in last10),
        "pts10": _mean(m["pts"] for m in last10),
        "rest": float(min((day - history[-1]["date"]).days, 30)),
    }
    venue = list(venue_history)
    enough = len(venue) >= 3
    out["venue_gf5"] = _mean(m["gf"] for m in venue) if enough else np.nan
    out["venue_ga5"] = _mean(m["ga"] for m in venue) if enough else np.nan
    return out


def build_features(matches: pd.DataFrame) -> pd.DataFrame:
    """One row per match (finished or not) with features and, where the match
    is finished, the three targets. Unusable rows have usable = False."""
    rows = []
    for league, lg in matches.groupby("league", sort=False):
        history = defaultdict(lambda: deque(maxlen=10))
        home_hist = defaultdict(lambda: deque(maxlen=5))
        away_hist = defaultdict(lambda: deque(maxlen=5))
        elo = defaultdict(lambda: ELO_START)
        goals_total, matches_total = 0.0, 0
        for day, group in lg.groupby("match_date", sort=True):
            records = list(group.itertuples(index=False))
            for r in records:  # 1. features, from earlier dates only
                h = _team_features(history[r.home], home_hist[r.home], day)
                a = _team_features(history[r.away], away_hist[r.away], day)
                row = {"match_id": r.match_id, "league": league, "season": r.season,
                       "match_date": day, "status": r.status, "usable": bool(h) and bool(a)}
                if row["usable"]:
                    row.update({f"h_{k}": h[k] for k in TEAM_FEATURES})
                    row.update({f"a_{k}": a[k] for k in TEAM_FEATURES})
                    row.update(h_home_gf5=h["venue_gf5"], h_home_ga5=h["venue_ga5"],
                               a_away_gf5=a["venue_gf5"], a_away_ga5=a["venue_ga5"],
                               elo_diff=elo[r.home] - elo[r.away],
                               league_gpm=goals_total / matches_total if matches_total else np.nan)
                if r.status == "finished":
                    hg, ag = int(r.home_goals), int(r.away_goals)
                    row.update(over25=int(hg + ag > 2.5), btts=int(hg > 0 and ag > 0),
                               result=RESULT_CODES["H" if hg > ag else "A" if ag > hg else "D"])
                rows.append(row)
            for r in records:  # 2. only now add this date's results to the histories
                if r.status != "finished":
                    continue
                hg, ag = int(r.home_goals), int(r.away_goals)
                home_pts = 3 if hg > ag else 1 if hg == ag else 0
                away_pts = 3 if ag > hg else 1 if hg == ag else 0
                home_rec = {"date": day, "gf": hg, "ga": ag, "sh": r.home_shots, "sha": r.away_shots,
                            "sot": r.home_sot, "sota": r.away_sot, "pts": home_pts}
                away_rec = {"date": day, "gf": ag, "ga": hg, "sh": r.away_shots, "sha": r.home_shots,
                            "sot": r.away_sot, "sota": r.home_sot, "pts": away_pts}
                history[r.home].append(home_rec)
                history[r.away].append(away_rec)
                home_hist[r.home].append(home_rec)
                away_hist[r.away].append(away_rec)
                expected = 1.0 / (1.0 + 10 ** (-(elo[r.home] + ELO_HOME - elo[r.away]) / 400.0))
                actual = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
                elo[r.home] += ELO_K * (actual - expected)
                elo[r.away] -= ELO_K * (actual - expected)
                goals_total += hg + ag
                matches_total += 1
    out = pd.DataFrame(rows)
    for col in FEATURES + ["over25", "btts", "result"]:
        if col not in out.columns:
            out[col] = np.nan
    return out
