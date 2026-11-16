"""Upcoming fixtures from the fixturedownload.com JSON feeds.

One feed per league and season, with kick-off times in UTC and results filled
in as matches are played. Used only for schedules: who plays whom, and when.
No odds, no statistics.

Team names differ from the stored ones ("Internazionale" vs "Inter"), so the
feed goes through the same spelling-then-schedule verification as the
openfootball files (see `openfootball.map_teams`): a team is mapped only if
its already-played fixtures in the feed line up with stored results.

Collected under the project's personal-research data policy
(docs/DATA_SOURCES.md): the site's terms were not checked for permission to
collect by program. One request per league per run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

BASE_URL = "https://fixturedownload.com/feed/json"
# league code -> feed name. Switzerland and Norway have no feed.
LEAGUE_FEEDS = {
    "E0": "epl",
    "SP1": "la-liga",
    "D1": "bundesliga",
    "I1": "serie-a",
    "N1": "eredivisie",
    "T1": "super-lig",
}
UK = ZoneInfo("Europe/London")
TIMEZONE = "Europe/London"  # parse() returns UK local dates and times, the stored results' convention


def url(feed: str, season: str) -> str:
    return f"{BASE_URL}/{feed}-{int(season[:4])}"


def parse(raw: bytes) -> pd.DataFrame:
    """Matches as a frame: match_date, time (HH:MM), home, away, played.
    Dates and times are converted from UTC to UK local time."""
    rows = []
    for m in json.loads(raw.decode("utf-8-sig")):
        kickoff = datetime.strptime(m["DateUtc"], "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(UK)
        rows.append({"match_date": kickoff.date(), "time": f"{kickoff:%H:%M}",
                     "home": m["HomeTeam"], "away": m["AwayTeam"],
                     "played": m.get("HomeTeamScore") is not None and m.get("AwayTeamScore") is not None})
    return pd.DataFrame(rows)
