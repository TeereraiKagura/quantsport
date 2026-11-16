"""League and data-source registry. Adding a league is a one-line change here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class LeagueDef:
    code: str  # football-data.co.uk division / file code
    name: str
    country: str
    season_type: str  # "split" (runs across two calendar years) or "calendar"
    layout: str  # "main" (one file per season) or "extra" (one file, all seasons)


@dataclass(frozen=True)
class SourceDef:
    key: str
    name: str
    url: str | None
    license_note: str


LEAGUES: dict[str, LeagueDef] = {
    lg.code: lg
    for lg in [
        LeagueDef("E0", "Premier League", "England", "split", "main"),
        LeagueDef("SP1", "La Liga", "Spain", "split", "main"),
        LeagueDef("D1", "Bundesliga", "Germany", "split", "main"),
        LeagueDef("I1", "Serie A", "Italy", "split", "main"),
        LeagueDef("N1", "Eredivisie", "Netherlands", "split", "main"),
        LeagueDef("T1", "Super Lig", "Turkey", "split", "main"),
        LeagueDef("SWZ", "Super League", "Switzerland", "split", "extra"),
        LeagueDef("NOR", "Eliteserien", "Norway", "calendar", "extra"),
    ]
}

DATA_SOURCES: dict[str, SourceDef] = {
    s.key: s
    for s in [
        SourceDef(
            "football_data",
            "football-data.co.uk",
            "https://www.football-data.co.uk",
            "Free CSV downloads published for personal analysis; no explicit licence is "
            "stated. Raw files are cached locally and are not redistributed.",
        ),
        SourceDef(
            "openfootball",
            "openfootball/football.json",
            "https://github.com/openfootball/football.json",
            "Public domain (CC0). Used for match schedules only; no odds or statistics.",
        ),
        SourceDef(
            "fixturedownload",
            "fixturedownload.com",
            "https://fixturedownload.com",
            "Fixture feeds collected for personal research; the site's terms were not checked for "
            "permission to collect by program. Schedules only; not redistributed.",
        ),
        SourceDef(
            "csv_upload",
            "User CSV upload",
            None,
            "Licensing is the responsibility of the uploader.",
        ),
        SourceDef(
            "oddalerts",
            "OddAlerts API",
            "https://www.oddalerts.com/football-data-api",
            "Paid REST API (Advanced plan or API day pass). Disabled unless "
            "ODDALERTS_API_TOKEN is set. The website itself is never scraped.",
        ),
    ]
}


def season_start_year(season_type: str, on: date) -> int:
    """Start year of the season in progress on a given date."""
    if season_type == "calendar":
        return on.year
    return on.year if on.month >= 7 else on.year - 1


def season_label(season_type: str, start_year: int) -> str:
    return str(start_year) if season_type == "calendar" else f"{start_year}/{start_year + 1}"


def seasons_in_scope(league: LeagueDef, today: date, seasons_back: int = 1) -> list[str]:
    """Current season plus `seasons_back` previous ones, oldest first."""
    current = season_start_year(league.season_type, today)
    return [
        season_label(league.season_type, y) for y in range(current - seasons_back, current + 1)
    ]


def season_bounds(season_type: str, label: str) -> tuple[date, date]:
    """Generous date window in which a season's matches are expected to fall."""
    start = int(label[:4])
    if season_type == "calendar":
        return date(start, 1, 1), date(start, 12, 31)
    return date(start, 7, 1), date(start + 1, 8, 31)
