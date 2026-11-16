"""Turn a football-data.co.uk style CSV into typed, normalised match records.

Two layouts are supported and auto-detected from the header:
  main  - Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,... (one season per file)
  extra - Country,League,Season,Date,Time,Home,Away,HG,AG,Res,... (all seasons)

Parsing only coerces types and structure. Semantic checks live in validation.py.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from quantsport.data.leagues import LeagueDef, season_label, season_start_year

# football-data.co.uk publishes kick-off times in UK local time (checked against
# known Premier League and Swiss Super League kick-offs).
SOURCE_TZ = ZoneInfo("Europe/London")

EXTRA_TO_MAIN = {"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG", "Res": "FTR"}

INT_STATS = {
    "HS": "home_shots", "AS": "away_shots",
    "HST": "home_sot", "AST": "away_sot",
    "HC": "home_corners", "AC": "away_corners",
    "HF": "home_fouls", "AF": "away_fouls",
    "HY": "home_yellow", "AY": "away_yellow",
    "HR": "home_red", "AR": "away_red",
}
FLOAT_STATS = {"HxG": "home_xg", "AxG": "away_xg"}

# code -> (display name, is_aggregate). Aggregates are not prices anyone can
# bet at a single bookmaker and must never be treated as executable.
BOOKMAKERS: dict[str, tuple[str, bool]] = {
    "B365": ("Bet365", False),
    "BFD": ("Betfred", False),
    "BMGM": ("BetMGM", False),
    "BV": ("BetVictor", False),
    "BW": ("Bwin", False),
    "CL": ("Coral", False),
    "LB": ("Ladbrokes", False),
    "PS": ("Pinnacle", False),
    "P": ("Pinnacle", False),
    "PP": ("Paddy Power", False),
    "SKB": ("Sky Bet", False),
    "WH": ("William Hill", False),
    "VC": ("VC Bet", False),
    "IW": ("Interwetten", False),
    "1XB": ("1xBet", False),
    "BFE": ("Betfair Exchange", False),
    "Max": ("Market maximum", True),
    "Avg": ("Market average", True),
}


@dataclass(frozen=True)
class OddsColumn:
    column: str
    bookmaker: str
    is_aggregate: bool
    market: str
    line: float
    selection: str
    snapshot_type: str


@dataclass(frozen=True)
class Issue:
    severity: str  # error | warning | info
    code: str
    message: str
    row_number: int | None = None
    field: str | None = None
    context: str | None = None


@dataclass
class OddsRecord:
    bookmaker: str
    is_aggregate: bool
    market: str
    line: float
    selection: str
    snapshot_type: str
    price: float


@dataclass
class ParsedMatch:
    row_number: int
    season: str
    match_date: date
    kickoff_utc: datetime | None
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    result_code: str | None  # the source's own H/D/A flag, used only for validation
    ht_home_goals: int | None
    ht_away_goals: int | None
    referee: str | None
    stats: dict[str, int | float | None] = field(default_factory=dict)
    odds: list[OddsRecord] = field(default_factory=list)

    def payload(self) -> dict:
        """Canonical content used for change detection and version history."""
        d = asdict(self)
        d.pop("row_number")
        d["match_date"] = self.match_date.isoformat()
        d["kickoff_utc"] = self.kickoff_utc.isoformat() if self.kickoff_utc else None
        d["odds"] = sorted(
            d["odds"],
            key=lambda o: (o["bookmaker"], o["market"], o["line"], o["snapshot_type"], o["selection"]),
        )
        return d


@dataclass
class ParseResult:
    matches: list[ParsedMatch]
    issues: list[Issue]
    rows_read: int
    rows_out_of_scope: int
    layout: str


def read_csv_bytes(raw: bytes) -> pd.DataFrame:
    """Read every cell as text so nothing is silently coerced."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    # A structurally malformed file raises here and fails the whole run loudly.
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    df = df[[c for c in df.columns if c and not c.startswith("Unnamed")]]
    return df.apply(lambda col: col.str.strip())


def _split_prefix(prefix: str) -> tuple[str, str, bool]:
    """(bookmaker name, snapshot_type, is_known) for an odds-column prefix."""
    if prefix in BOOKMAKERS:
        return prefix, "pre_close", True
    if prefix.endswith("C") and prefix[:-1] in BOOKMAKERS:
        return prefix[:-1], "closing", True
    if prefix.endswith("C") and len(prefix) > 1:
        return prefix[:-1], "closing", False
    return prefix, "pre_close", False


def detect_odds_columns(columns: list[str]) -> tuple[list[OddsColumn], list[str]]:
    """Find 1X2 and over/under 2.5 price columns. Returns (columns, unknown codes)."""
    colset = set(columns)
    found: list[OddsColumn] = []
    unknown: set[str] = set()

    def add(col: str, prefix: str, market: str, line: float, selection: str) -> None:
        code, snapshot, known = _split_prefix(prefix)
        if known:
            name, aggregate = BOOKMAKERS[code]
        else:
            name, aggregate = code, False
            unknown.add(code)
        found.append(OddsColumn(col, name, aggregate, market, line, selection, snapshot))

    for col in columns:
        m = re.fullmatch(r"(.+)([HDA])", col)
        if m and all(m.group(1) + s in colset for s in "HDA"):
            add(col, m.group(1), "1X2", 0.0, m.group(2))
            continue
        m = re.fullmatch(r"(.+)([<>])2\.5", col)
        if m:
            add(col, m.group(1), "OU", 2.5, "over" if m.group(2) == ">" else "under")
    return found, sorted(unknown)


def _to_int(value: str) -> int | None:
    f = float(value)
    if f != int(f):
        raise ValueError(value)
    return int(f)


def _parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(value)


def _kickoff_utc(day: date, time_text: str) -> datetime:
    t = datetime.strptime(time_text, "%H:%M").time()
    local = datetime.combine(day, t, tzinfo=SOURCE_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _normalise_season(text: str, season_type: str) -> str:
    start = int(text[:4])
    return season_label(season_type, start)


def parse_football_data(
    df: pd.DataFrame,
    league: LeagueDef,
    *,
    season_hint: str | None = None,
    allowed_seasons: set[str] | None = None,
) -> ParseResult:
    """Parse a football-data.co.uk style frame for one league.

    season_hint     - season label for 'main' files, which carry no season column.
                      If omitted the season is derived from each match date.
    allowed_seasons - if given, rows from other seasons are skipped (out of scope).
    """
    layout = "extra" if "Home" in df.columns and "HomeTeam" not in df.columns else "main"
    if layout == "extra":
        df = df.rename(columns=EXTRA_TO_MAIN)
    required = {"Date", "HomeTeam", "AwayTeam"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    odds_columns, unknown_codes = detect_odds_columns(list(df.columns))
    issues: list[Issue] = [
        Issue("info", "UNKNOWN_BOOKMAKER_CODE", f"Unrecognised bookmaker code '{c}' stored as-is", field=c)
        for c in unknown_codes
    ]
    matches: list[ParsedMatch] = []
    rows_read = out_of_scope = 0

    for idx, row in enumerate(df.to_dict("records")):
        row_number = idx + 2  # 1-based, header is line 1
        if not any(row.values()):
            continue  # trailing blank line
        rows_read += 1
        if "Div" in row and row["Div"] and row["Div"] != league.code:
            out_of_scope += 1
            continue

        def ctx() -> str:
            return f"{row.get('Date')} {row.get('HomeTeam')} v {row.get('AwayTeam')}"

        def reject(code: str, message: str, fld: str | None = None) -> None:
            issues.append(Issue("error", code, message, row_number, fld, ctx()))

        home, away = row["HomeTeam"], row["AwayTeam"]
        if not row["Date"] or not home or not away:
            reject("MISSING_REQUIRED", "Date, home team and away team are required")
            continue
        try:
            match_date = _parse_date(row["Date"])
        except ValueError:
            reject("BAD_DATE", f"Unparseable date '{row['Date']}'", "Date")
            continue

        if layout == "extra" and row.get("Season"):
            try:
                season = _normalise_season(row["Season"], league.season_type)
            except ValueError:
                reject("BAD_SEASON", f"Unparseable season '{row['Season']}'", "Season")
                continue
        elif season_hint:
            season = season_hint
        else:
            season = season_label(league.season_type, season_start_year(league.season_type, match_date))
        if allowed_seasons is not None and season not in allowed_seasons:
            out_of_scope += 1
            continue

        kickoff = None
        if row.get("Time"):
            try:
                kickoff = _kickoff_utc(match_date, row["Time"])
            except ValueError:
                issues.append(
                    Issue("warning", "BAD_TIME", f"Unparseable time '{row['Time']}'; kick-off time left unknown",
                          row_number, "Time", ctx())
                )

        bad_field = None
        ints: dict[str, int | None] = {}
        for col in ("FTHG", "FTAG", "HTHG", "HTAG"):
            text = row.get(col, "")
            try:
                ints[col] = _to_int(text) if text else None
            except ValueError:
                bad_field = col
                break
        if bad_field:
            reject("BAD_GOALS", f"Non-integer goals value '{row[bad_field]}'", bad_field)
            continue

        stats: dict[str, int | float | None] = {}
        for col, name in {**INT_STATS, **FLOAT_STATS}.items():
            text = row.get(col, "")
            if not text:
                stats[name] = None
                continue
            try:
                stats[name] = _to_int(text) if col in INT_STATS else float(text)
            except ValueError:
                stats[name] = None
                issues.append(
                    Issue("warning", "BAD_STAT", f"Unparseable value '{text}' dropped", row_number, col, ctx())
                )

        odds: list[OddsRecord] = []
        for oc in odds_columns:
            text = row.get(oc.column, "")
            if not text:
                continue
            try:
                price = float(text)
            except ValueError:
                price = float("nan")
            if not price > 1.0 or price > 1000:
                issues.append(
                    Issue("warning", "BAD_ODDS", f"Implausible decimal odds '{text}' dropped",
                          row_number, oc.column, ctx())
                )
                continue
            odds.append(
                OddsRecord(oc.bookmaker, oc.is_aggregate, oc.market, oc.line, oc.selection, oc.snapshot_type, price)
            )

        matches.append(
            ParsedMatch(
                row_number=row_number,
                season=season,
                match_date=match_date,
                kickoff_utc=kickoff,
                home_team=home,
                away_team=away,
                home_goals=ints["FTHG"],
                away_goals=ints["FTAG"],
                result_code=row.get("FTR") or None,
                ht_home_goals=ints["HTHG"],
                ht_away_goals=ints["HTAG"],
                referee=row.get("Referee") or None,
                stats=stats,
                odds=odds,
            )
        )

    return ParseResult(matches, issues, rows_read, out_of_scope, layout)
