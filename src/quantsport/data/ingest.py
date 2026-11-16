"""Ingestion pipeline: fetch -> archive raw file -> parse -> validate -> versioned upsert.

Every run is recorded in ingestion_runs. A file whose bytes were already loaded
successfully is skipped. A match whose content is unchanged is left untouched;
a changed match gets a new version and its previous content stays in
match_versions, so history is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from quantsport.config import Settings
from quantsport.data import sources
from quantsport.data.leagues import LEAGUES, LeagueDef
from quantsport.data.parsing import Issue, ParsedMatch, parse_football_data, read_csv_bytes
from quantsport.data.validation import split_duplicates, validate_match
from quantsport.db.models import (
    DataSource,
    IngestionRun,
    League,
    Match,
    MatchStats,
    MatchVersion,
    OddsQuote,
    Team,
    ValidationIssue,
    utcnow,
)

log = logging.getLogger(__name__)


def _payload_hash(payload: dict) -> tuple[str, str]:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return text, hashlib.sha256(text.encode()).hexdigest()


def _status(pm: ParsedMatch, today: date) -> str:
    if pm.home_goals is not None:
        return "finished"
    return "scheduled" if pm.match_date >= today else "awaiting_result"


def _store_issues(session: Session, run: IngestionRun, issues: list[Issue]) -> None:
    if issues:
        session.execute(insert(ValidationIssue), [{"run_id": run.id, **asdict(i)} for i in issues])


def _apply(match: Match, pm: ParsedMatch, today: date) -> None:
    match.season = pm.season
    match.match_date = pm.match_date
    match.kickoff_utc = pm.kickoff_utc
    match.status = _status(pm, today)
    match.home_goals = pm.home_goals
    match.away_goals = pm.away_goals
    match.ht_home_goals = pm.ht_home_goals
    match.ht_away_goals = pm.ht_away_goals
    match.referee = pm.referee


def _write_children(session: Session, match_id: int, pm: ParsedMatch) -> None:
    session.execute(delete(MatchStats).where(MatchStats.match_id == match_id))
    session.execute(delete(OddsQuote).where(OddsQuote.match_id == match_id))
    session.execute(insert(MatchStats), [{"match_id": match_id, **pm.stats}])
    if pm.odds:
        session.execute(insert(OddsQuote), [{"match_id": match_id, **asdict(o)} for o in pm.odds])


def ingest_bytes(
    session: Session,
    raw: bytes,
    *,
    league: LeagueDef,
    source_key: str,
    origin: str,
    today: date,
    season_hint: str | None = None,
    allowed_seasons: set[str] | None = None,
    raw_dir: Path | None = None,
) -> IngestionRun:
    """Load one CSV file for one league. Always returns the recorded run."""
    source = session.scalars(select(DataSource).where(DataSource.key == source_key)).one()
    league_row = session.scalars(select(League).where(League.code == league.code)).one()
    sha = hashlib.sha256(raw).hexdigest()
    run = IngestionRun(source_id=source.id, league_id=league_row.id, origin=origin, file_sha256=sha)
    session.add(run)
    session.commit()

    already = session.scalars(
        select(IngestionRun.id).where(
            IngestionRun.file_sha256 == sha,
            IngestionRun.league_id == league_row.id,
            IngestionRun.status == "success",
        )
    ).first()
    if already:
        run.status, run.finished_at = "skipped_unchanged", utcnow()
        session.commit()
        return run

    try:
        if raw_dir is not None:
            folder = raw_dir / source_key / league.code
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{utcnow():%Y%m%dT%H%M%S}_{sha[:12]}.csv"
            path.write_bytes(raw)
            run.raw_path = str(path)

        parsed = parse_football_data(
            read_csv_bytes(raw), league, season_hint=season_hint, allowed_seasons=allowed_seasons
        )
        issues = list(parsed.issues)
        candidates, dup_issues = split_duplicates(parsed.matches)
        issues += dup_issues
        accepted: list[ParsedMatch] = []
        for pm in candidates:
            found = validate_match(pm, league, today)
            issues += found
            if not any(i.severity == "error" for i in found):
                accepted.append(pm)

        teams = {
            t.name: t.id
            for t in session.scalars(select(Team).where(Team.country == league.country))
        }

        def team_id(name: str) -> int:
            if name not in teams:
                team = Team(name=name, country=league.country)
                session.add(team)
                session.flush()
                teams[name] = team.id
            return teams[name]

        existing = {
            (m.home_team_id, m.away_team_id, m.match_date): m
            for m in session.scalars(select(Match).where(Match.league_id == league_row.id))
        }
        # A scheduled fixture that is later moved keeps its identity: an
        # unplayed match for the same pairing and season is the same match.
        unplayed = {
            (m.home_team_id, m.away_team_id, m.season): m
            for m in existing.values()
            if m.status != "finished"
        }

        for pm in accepted:
            home_id, away_id = team_id(pm.home_team), team_id(pm.away_team)
            text, digest = _payload_hash(pm.payload())
            match = existing.get((home_id, away_id, pm.match_date))
            if match is None:
                match = unplayed.pop((home_id, away_id, pm.season), None)
                if match is not None:
                    existing[(home_id, away_id, pm.match_date)] = match
            if match is None:
                match = Match(
                    league_id=league_row.id, home_team_id=home_id, away_team_id=away_id,
                    source_id=source.id, first_run_id=run.id, last_run_id=run.id,
                    payload_hash=digest, version=1,
                )
                _apply(match, pm, today)
                session.add(match)
                session.flush()
                existing[(home_id, away_id, pm.match_date)] = match
                run.matches_inserted += 1
            elif match.payload_hash == digest:
                run.matches_unchanged += 1
                continue
            else:
                _apply(match, pm, today)
                match.version += 1
                match.payload_hash = digest
                match.last_run_id = run.id
                match.updated_at = utcnow()
                run.matches_updated += 1
            _write_children(session, match.id, pm)
            session.add(
                MatchVersion(match_id=match.id, version=match.version, payload_json=text,
                             payload_hash=digest, run_id=run.id)
            )

        _store_issues(session, run, issues)
        run.rows_read = parsed.rows_read
        run.rows_out_of_scope = parsed.rows_out_of_scope
        run.rows_rejected = len(parsed.matches) - len(accepted) + sum(
            1 for i in parsed.issues if i.severity == "error"
        )
        run.status, run.finished_at = "success", utcnow()
        session.commit()
    except Exception as exc:  # record the failure, keep nothing half-loaded
        session.rollback()
        log.exception("Ingestion failed for %s", origin)
        run = session.get(IngestionRun, run.id)
        run.status, run.finished_at, run.error = "failed", utcnow(), f"{type(exc).__name__}: {exc}"
        session.commit()
    return run


def ingest_football_data(
    session: Session, settings: Settings, league_codes: list[str], today: date, seasons_back: int = 1
) -> list[IngestionRun]:
    """Download and load historical results and odds for the given leagues."""
    runs = []
    for code in league_codes:
        league = LEAGUES[code]
        for remote in sources.football_data_files(league, today, seasons_back):
            try:
                raw = sources.fetch(remote.url, settings)
            except Exception as exc:
                log.error("Could not download %s: %s", remote.url, exc)
                runs.append(_failed_download(session, code, remote.url, exc))
                continue
            run = ingest_bytes(
                session, raw, league=league, source_key="football_data", origin=remote.url,
                today=today, season_hint=remote.season_hint,
                allowed_seasons=remote.allowed_seasons, raw_dir=settings.raw_dir,
            )
            log.info("%s %s: %s (+%d new, %d updated, %d unchanged, %d rejected)", code, remote.url,
                     run.status, run.matches_inserted, run.matches_updated,
                     run.matches_unchanged, run.rows_rejected)
            runs.append(run)
    return runs


def ingest_fixtures(session: Session, settings: Settings, league_codes: list[str], today: date) -> list[IngestionRun]:
    """Load upcoming fixtures. The provider's file covers main-layout leagues only."""
    url = sources.football_data_fixtures_url()
    raw = sources.fetch(url, settings)
    runs = []
    for code in league_codes:
        league = LEAGUES[code]
        if league.layout != "main":
            continue
        runs.append(
            ingest_bytes(session, raw, league=league, source_key="football_data", origin=url,
                         today=today, raw_dir=settings.raw_dir)
        )
    return runs


def ingest_openfootball(
    session: Session, settings: Settings, league_codes: list[str], today: date, days_ahead: int = 10
) -> list[tuple[IngestionRun | None, dict]]:
    """Load upcoming fixtures from the public-domain openfootball files.

    Returns, per league, the ingestion run (None if nothing could be loaded)
    and a report: mapped and unmapped teams, date agreement on played
    fixtures, and fixtures skipped.
    """
    from datetime import timedelta

    import pandas as pd

    from quantsport.data import openfootball as of
    from quantsport.data.leagues import season_label, season_start_year

    out = []
    for code in league_codes:
        if code not in of.LEAGUE_FILES:
            out.append((None, {"league": code, "note": "not covered by openfootball"}))
            continue
        league = LEAGUES[code]
        stem, tz_name = of.LEAGUE_FILES[code]
        season = season_label(league.season_type, season_start_year(league.season_type, today))
        address = of.url(stem, season)
        try:
            raw = sources.fetch(address, settings)
        except Exception as exc:
            log.error("Could not download %s: %s", address, exc)
            out.append((None, {"league": code, "note": f"download failed: {exc}"}))
            continue
        fixtures = of.parse(raw)
        results = pd.read_sql(
            select(Match.match_date, Team.name.label("home"), Match.away_team_id)
            .join(Team, Team.id == Match.home_team_id).join(League, League.id == Match.league_id)
            .where(League.code == code, Match.season == season, Match.status == "finished"),
            session.connection())
        away_names = dict(session.execute(select(Team.id, Team.name)).all())
        results["away"] = results.away_team_id.map(away_names)
        results["match_date"] = pd.to_datetime(results.match_date).dt.date
        mapping = of.map_teams(fixtures, results, today)
        body, skipped = of.to_csv(fixtures, mapping, code, tz_name, today, today + timedelta(days=days_ahead))
        report = {"league": code, "teams_mapped": len(mapping.names), "teams_unmapped": mapping.unmapped,
                  "fixtures_skipped_unmapped": skipped, **mapping.agreement}
        if body.count(b"\n") <= 1:
            out.append((None, {**report, "note": "no mappable fixtures in the window"}))
            continue
        run = ingest_bytes(session, body, league=league, source_key="openfootball", origin=address,
                           today=today, raw_dir=settings.raw_dir)
        out.append((run, report))
    return out


def ingest_csv_file(
    session: Session, settings: Settings, path: Path, league_code: str, today: date, season: str | None = None
) -> IngestionRun:
    """Load a user-supplied CSV in either football-data.co.uk layout."""
    return ingest_bytes(
        session, path.read_bytes(), league=LEAGUES[league_code], source_key="csv_upload",
        origin=path.name, today=today, season_hint=season, raw_dir=settings.raw_dir,
    )


def _failed_download(session: Session, league_code: str, url: str, exc: Exception) -> IngestionRun:
    source = session.scalars(select(DataSource).where(DataSource.key == "football_data")).one()
    league_row = session.scalars(select(League).where(League.code == league_code)).one()
    run = IngestionRun(
        source_id=source.id, league_id=league_row.id, origin=url, status="failed",
        finished_at=utcnow(), error=f"download: {exc}",
    )
    session.add(run)
    session.commit()
    return run
