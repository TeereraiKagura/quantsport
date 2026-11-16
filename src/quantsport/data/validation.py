"""Semantic validation of parsed matches.

Severity "error" rejects the row (it is not stored). "warning" stores the row
and records the concern. Missing values are never filled in; they stay NULL and
are measured by the data-quality report.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from quantsport.data.leagues import LeagueDef, season_bounds
from quantsport.data.parsing import Issue, ParsedMatch

# Sum of inverse odds across a complete set of outcomes. Real bookmakers sit
# above 1.0; anything outside this window suggests a corrupt price.
OVERROUND_MIN = 0.95
OVERROUND_MAX = 1.25
SELECTIONS = {"1X2": {"H", "D", "A"}, "OU": {"over", "under"}}


def _expected_result(home_goals: int, away_goals: int) -> str:
    return "H" if home_goals > away_goals else "A" if away_goals > home_goals else "D"


def validate_match(pm: ParsedMatch, league: LeagueDef, today: date) -> list[Issue]:
    issues: list[Issue] = []
    ctx = f"{pm.match_date} {pm.home_team} v {pm.away_team}"

    def add(severity: str, code: str, message: str, fld: str | None = None) -> None:
        issues.append(Issue(severity, code, message, pm.row_number, fld, ctx))

    if pm.home_team == pm.away_team:
        add("error", "SAME_TEAMS", "Home and away team are identical")

    has_home, has_away = pm.home_goals is not None, pm.away_goals is not None
    if has_home != has_away:
        add("error", "PARTIAL_SCORE", "Only one of home/away goals is present")
    elif has_home:
        if pm.home_goals < 0 or pm.away_goals < 0:
            add("error", "NEGATIVE_GOALS", "Goals cannot be negative")
        elif pm.result_code and pm.result_code != _expected_result(pm.home_goals, pm.away_goals):
            add("error", "RESULT_MISMATCH",
                f"Result flag '{pm.result_code}' contradicts score {pm.home_goals}-{pm.away_goals}", "FTR")
        if pm.match_date > today:
            add("error", "FUTURE_RESULT", "A final score is recorded for a match dated in the future", "Date")
        if pm.ht_home_goals is not None and pm.ht_away_goals is not None:
            if pm.ht_home_goals > pm.home_goals or pm.ht_away_goals > pm.away_goals:
                add("warning", "HT_EXCEEDS_FT", "Half-time goals exceed full-time goals")
    elif pm.match_date < today:
        add("warning", "RESULT_MISSING", "Match date has passed but no result is recorded")

    lo, hi = season_bounds(league.season_type, pm.season)
    if not lo <= pm.match_date <= hi:
        add("warning", "DATE_OUTSIDE_SEASON", f"Date falls outside season {pm.season}", "Date")

    s = pm.stats
    for side in ("home", "away"):
        shots, sot = s.get(f"{side}_shots"), s.get(f"{side}_sot")
        if shots is not None and sot is not None and sot > shots:
            add("warning", "SOT_EXCEEDS_SHOTS", f"{side} shots on target ({sot}) exceed shots ({shots})")
        for name in ("shots", "sot", "corners", "fouls", "yellow", "red", "xg"):
            v = s.get(f"{side}_{name}")
            if v is not None and v < 0:
                add("warning", "NEGATIVE_STAT", f"{side}_{name} is negative")

    books: dict[tuple, dict[str, float]] = defaultdict(dict)
    for o in pm.odds:
        books[(o.bookmaker, o.is_aggregate, o.market, o.line, o.snapshot_type)][o.selection] = o.price
    for (bookmaker, aggregate, market, line, snapshot), prices in books.items():
        if set(prices) != SELECTIONS[market]:
            continue  # incomplete set: stored as-is, unusable for margin removal
        booksum = sum(1.0 / p for p in prices.values())
        # "Market maximum" picks the best price per outcome across firms, so its
        # booksum is legitimately at or below 1.0.
        too_low = booksum < OVERROUND_MIN and not aggregate
        if too_low or booksum > OVERROUND_MAX:
            add("warning", "OVERROUND_OUT_OF_RANGE",
                f"{bookmaker} {market} {snapshot} booksum {booksum:.3f} outside "
                f"[{OVERROUND_MIN}, {OVERROUND_MAX}]")
    return issues


def split_duplicates(matches: list[ParsedMatch]) -> tuple[list[ParsedMatch], list[Issue]]:
    """Keep the first occurrence of each (date, home, away); report the rest."""
    seen: dict[tuple, int] = {}
    kept: list[ParsedMatch] = []
    issues: list[Issue] = []
    for pm in matches:
        key = (pm.match_date, pm.home_team, pm.away_team)
        if key in seen:
            issues.append(
                Issue("error", "DUPLICATE_ROW", f"Duplicate of row {seen[key]}; later row ignored",
                      pm.row_number, None, f"{pm.match_date} {pm.home_team} v {pm.away_team}")
            )
        else:
            seen[key] = pm.row_number
            kept.append(pm)
    return kept, issues
