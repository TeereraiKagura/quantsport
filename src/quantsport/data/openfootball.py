"""Upcoming fixtures from openfootball/football.json.

openfootball is a public-domain (CC0) fixture and results dataset on GitHub.
It is used here only for match schedules: who plays whom, and when. It has no
odds and no match statistics.

Two things make a schedule file from another source risky, and both are
handled explicitly:

1. Team names differ ("Manchester City FC" vs "Man City"). Names are matched
   on spelling first, and every match is then VERIFIED against the schedule:
   a mapping is kept only if the team's already-played fixtures in this file
   line up with the results already stored. Teams that cannot be verified are
   left unmapped and their fixtures are skipped, never guessed.
2. Dates in a season file can be provisional. `agreement` measures, on
   matches already played, how often this file's date equals the real one.

Kick-off times in the file are local to the league and are converted to UTC.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import pandas as pd

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master"
# league code -> (file stem, time zone of the kick-off times in the file)
LEAGUE_FILES = {
    "E0": ("en.1", "Europe/London"),
    "SP1": ("es.1", "Europe/Madrid"),
    "D1": ("de.1", "Europe/Berlin"),
    "I1": ("it.1", "Europe/Rome"),
    "N1": ("nl.1", "Europe/Amsterdam"),
}
NOISE = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "us", "ssc", "rcd", "cd", "ud", "sv", "vfl", "vfb", "tsg",
         "bv", "bc", "calcio", "club", "de", "futbol", "balompie", "1", "04", "05", "07", "09", "1846", "1899",
         "1907", "1909", "1910", "1913", "sbv", "sad", "and", "hove", "the"}
DATE_TOLERANCE = timedelta(days=3)
UK = ZoneInfo("Europe/London")


def url(file_stem: str, season: str) -> str:
    start = int(season[:4])
    return f"{BASE_URL}/{start}-{(start + 1) % 100:02d}/{file_stem}.json"


def parse(raw: bytes) -> pd.DataFrame:
    """Matches as a frame: match_date, time (HH:MM or None), home, away, played."""
    rows = []
    for m in json.loads(raw.decode("utf-8"))["matches"]:
        rows.append({"match_date": date.fromisoformat(m["date"]), "time": m.get("time"),
                     "home": m["team1"], "away": m["team2"], "played": bool(m.get("score"))})
    return pd.DataFrame(rows)


def normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in NOISE]
    return " ".join(tokens)


def _similarity(a: str, b: str) -> float:
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # A stored short name ("Man City", "Leverkusen") is often a prefix-wise
    # abbreviation or a single distinctive word of the long name.
    ta, tb = na.split(), nb.split()
    short, long_ = (ta, tb) if len(na) <= len(nb) else (tb, ta)
    if all(any(w.startswith(s[:3]) and (w.startswith(s) or s.startswith(w[:len(s)])) for w in long_) for s in short):
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


@dataclass
class Mapping:
    names: dict[str, str] = field(default_factory=dict)  # openfootball name -> stored name
    unmapped: list[str] = field(default_factory=list)
    checked: int = 0  # already-played fixtures of mapped teams compared with stored results
    found: int = 0  # ... whose pairing and venue exist in the stored results within 3 days
    same_date: int = 0  # ... and on exactly the same date

    @property
    def agreement(self) -> dict:
        return {"played_fixtures_checked": self.checked, "pairing_found": self.found,
                "date_identical": self.same_date,
                "date_identical_pct": round(100 * self.same_date / self.checked, 1) if self.checked else None}


def _support(team: str, candidate: str, past: pd.DataFrame, names: dict[str, str], stored: dict) -> tuple[int, int]:
    """(fixtures of `team` whose opponent is mapped, how many of them exist in
    the stored results with `candidate` in the same venue within the tolerance)."""
    total = hits = 0
    for m in past[(past.home == team) | (past.away == team)].itertuples(index=False):
        at_home = m.home == team
        opponent = names.get(m.away if at_home else m.home)
        if opponent is None:
            continue
        total += 1
        key = (candidate, opponent) if at_home else (opponent, candidate)
        if any(abs(d - m.match_date) <= DATE_TOLERANCE for d in stored.get(key, ())):
            hits += 1
    return total, hits


def map_teams(fixtures: pd.DataFrame, results: pd.DataFrame, today: date) -> Mapping:
    """Map this file's team names onto stored team names.

    results: stored finished matches of the same league and season
    (match_date, home, away).
    """
    stored: dict[tuple[str, str], list[date]] = {}
    for r in results.itertuples(index=False):
        stored.setdefault((r.home, r.away), []).append(r.match_date)
    db_teams = sorted(set(results.home) | set(results.away))
    of_teams = sorted(set(fixtures.home) | set(fixtures.away))
    past = fixtures[fixtures.match_date < today]

    # 1. Spelling: propose the best unique candidate for each name.
    names: dict[str, str] = {}
    scores = {t: sorted(((_similarity(t, c), c) for c in db_teams), reverse=True) for t in of_teams}
    for t, ranked in scores.items():
        if ranked and ranked[0][0] >= 0.85 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.05):
            names[t] = ranked[0][1]
    for target in {c for c in names.values() if list(names.values()).count(c) > 1}:
        for t in [t for t, c in names.items() if c == target]:
            del names[t]  # two names claiming one stored team: trust neither yet

    # 2. Schedule: drop spelling matches the played fixtures contradict, then
    #    infer the rest from fixtures against already-mapped opponents.
    for _ in range(4):
        for t in list(names):
            total, hits = _support(t, names[t], past, names, stored)
            if total >= 3 and hits / total < 0.7:
                del names[t]
        changed = False
        for t in of_teams:
            if t in names:
                continue
            free = [c for c in db_teams if c not in names.values()]
            ranked = sorted(((_support(t, c, past, names, stored)[1], c) for c in free), reverse=True)
            if ranked and ranked[0][0] >= 2 and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
                names[t] = ranked[0][1]
                changed = True
        if not changed:
            break

    # 3. Keep only mappings the schedule confirms; measure date agreement.
    out = Mapping()
    for t in of_teams:
        if t in names:
            total, hits = _support(t, names[t], past, names, stored)
            if total >= 2 and hits / total >= 0.7:
                out.names[t] = names[t]
                continue
        out.unmapped.append(t)
    for m in past.itertuples(index=False):
        h, a = out.names.get(m.home), out.names.get(m.away)
        if h is None or a is None:
            continue
        out.checked += 1
        dates = stored.get((h, a), [])
        if any(abs(d - m.match_date) <= DATE_TOLERANCE for d in dates):
            out.found += 1
            out.same_date += int(m.match_date in dates)
    return out


def to_csv(fixtures: pd.DataFrame, mapping: Mapping, league_code: str, tz_name: str,
           start: date, end: date) -> tuple[bytes, int]:
    """Unplayed fixtures between start and end as a football-data style CSV
    (the layout the ingestion pipeline already validates). Kick-off times are
    converted from the league's local time to UK time, which is what that
    layout uses. Returns (csv bytes, fixtures skipped for an unmapped team)."""
    tz = ZoneInfo(tz_name)
    window = fixtures[(fixtures.match_date >= start) & (fixtures.match_date <= end) & ~fixtures.played]
    lines, skipped = ["Div,Date,Time,HomeTeam,AwayTeam"], 0
    for m in window.sort_values("match_date").itertuples(index=False):
        home, away = mapping.names.get(m.home), mapping.names.get(m.away)
        if home is None or away is None:
            skipped += 1
            continue
        day, clock = m.match_date, ""
        if isinstance(m.time, str) and m.time:  # a missing time stays unknown
            local = datetime.combine(m.match_date, datetime.strptime(m.time, "%H:%M").time(), tzinfo=tz)
            uk = local.astimezone(UK)
            day, clock = uk.date(), f"{uk:%H:%M}"
        lines.append(f"{league_code},{day:%d/%m/%Y},{clock},{home},{away}")
    return ("\n".join(lines) + "\n").encode("utf-8"), skipped
