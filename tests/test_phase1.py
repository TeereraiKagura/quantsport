"""Phase 1 tests. All CSV content below is SYNTHETIC test data, written only to
exercise the parser, validator and versioned storage. It is never used in any
production calculation."""

from datetime import date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quantsport.data.ingest import ingest_bytes
from quantsport.data.leagues import LEAGUES, seasons_in_scope
from quantsport.data.parsing import detect_odds_columns, parse_football_data, read_csv_bytes
from quantsport.data.sources import football_data_files
from quantsport.data.validation import split_duplicates, validate_match
from quantsport.db import init_db, make_engine
from quantsport.db.models import IngestionRun, Match, MatchVersion, OddsQuote, ValidationIssue

E0 = LEAGUES["E0"]
TODAY = date(2026, 11, 16)

HEADER = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,HS,AS,HST,AST,"
          "B365H,B365D,B365A,B365>2.5,B365<2.5,MaxH,MaxD,MaxA,"
          "B365CH,B365CD,B365CA,B365C>2.5,B365C<2.5,B365AHH,B365AHA")
ROW_A = "E0,15/08/2025,20:00,Alpha,Beta,4,2,H,1,0,H,19,10,10,3,1.30,6.00,8.50,1.36,3.20,1.34,6.5,9.5,1.29,6.25,9.00,1.36,3.20,1.83,2.03"
ROW_B = "E0,16/01/2026,15:00,Gamma,Delta,0,0,D,0,0,D,8,7,2,1,2.10,3.40,3.60,2.00,1.80,2.2,3.5,3.8,2.05,3.40,3.75,2.05,1.78,1.90,1.95"


def csv(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def parse(raw: bytes, **kw):
    return parse_football_data(read_csv_bytes(raw), E0, season_hint="2025/2026", **kw)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as s:
        yield s


def load(session, raw, **kw):
    return ingest_bytes(session, raw, league=E0, source_key="csv_upload", origin="test.csv",
                        today=TODAY, season_hint="2025/2026", **kw)


# ---- parsing ---------------------------------------------------------------

def test_odds_columns_exclude_asian_handicap_and_stats():
    cols, unknown = detect_odds_columns(HEADER.split(","))
    names = {c.column for c in cols}
    assert "B365AHH" not in names and "HS" not in names and "FTR" not in names
    assert {"B365H", "B365CA", "B365>2.5", "B365C<2.5", "MaxD"} <= names
    closing = next(c for c in cols if c.column == "B365CH")
    assert (closing.bookmaker, closing.snapshot_type, closing.market) == ("Bet365", "closing", "1X2")
    assert next(c for c in cols if c.column == "MaxH").is_aggregate
    assert unknown == []


def test_kickoff_converted_from_uk_time_to_utc():
    a, b = parse(csv(ROW_A, ROW_B)).matches
    assert a.kickoff_utc == datetime(2025, 8, 15, 19, 0)  # BST = UTC+1
    assert b.kickoff_utc == datetime(2026, 1, 16, 15, 0)  # GMT = UTC


def test_missing_values_stay_missing():
    row = "E0,15/08/2025,,Alpha,Beta,1,1,D,,,,,,,,,,,,,,,,,,,,,,"
    pm = parse(csv(row)).matches[0]
    assert pm.kickoff_utc is None and pm.ht_home_goals is None
    assert pm.stats["home_shots"] is None and pm.odds == []


def test_bad_odds_dropped_with_warning():
    res = parse(csv(ROW_A.replace(",1.30,", ",0.90,", 1)))
    assert not any(o.selection == "H" and o.snapshot_type == "pre_close" and o.bookmaker == "Bet365"
                   for o in res.matches[0].odds)
    assert [i.code for i in res.issues] == ["BAD_ODDS"]


def test_extra_layout_and_season_filter():
    raw = ("Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,,\n"
           "Norway,Eliteserien,2019,01/04/2019,18:00,Aa,Bb,1,0,H,2.0,3.5,3.8,,\n"
           "Norway,Eliteserien,2026,01/04/2026,18:00,Aa,Bb,2,2,D,2.0,3.5,3.8,,\n").encode()
    res = parse_football_data(read_csv_bytes(raw), LEAGUES["NOR"], allowed_seasons={"2025", "2026"})
    assert res.layout == "extra" and res.rows_out_of_scope == 1
    assert [(m.season, m.home_goals) for m in res.matches] == [("2026", 2)]
    assert {o.snapshot_type for o in res.matches[0].odds} == {"closing"}


def test_seasons_and_download_links():
    assert seasons_in_scope(E0, TODAY) == ["2025/2026", "2026/2027"]
    assert seasons_in_scope(LEAGUES["NOR"], TODAY) == ["2025", "2026"]
    assert seasons_in_scope(E0, date(2026, 3, 1)) == ["2024/2025", "2025/2026"]
    urls = [f.url for f in football_data_files(E0, TODAY)]
    assert urls == ["https://www.football-data.co.uk/mmz4281/2526/E0.csv",
                    "https://www.football-data.co.uk/mmz4281/2627/E0.csv"]


# ---- validation ------------------------------------------------------------

def codes(raw: bytes) -> list[str]:
    res = parse(raw)
    return [i.code for pm in res.matches for i in validate_match(pm, E0, TODAY)]


def test_result_flag_must_match_score():
    assert codes(csv(ROW_A.replace(",4,2,H,", ",4,2,A,"))) == ["RESULT_MISMATCH"]


def test_clean_row_has_no_issues():
    assert codes(csv(ROW_A, ROW_B)) == []


def test_shots_on_target_and_overround_warnings():
    bad = ROW_A.replace(",19,10,10,3,", ",5,10,10,3,").replace("1.29,6.25,9.00", "3.00,6.25,9.00")
    assert sorted(codes(csv(bad))) == ["OVERROUND_OUT_OF_RANGE", "SOT_EXCEEDS_SHOTS"]


def test_future_result_rejected_and_past_fixture_flagged():
    future = ROW_A.replace("15/08/2025", "15/12/2026")
    assert "FUTURE_RESULT" in codes(csv(future))
    unplayed = "E0,01/11/2026,15:00,Alpha,Beta,,,,,,,,,,,,,,,,,,,,,,,,,"
    res = parse_football_data(read_csv_bytes(csv(unplayed)), E0)
    assert [i.code for i in validate_match(res.matches[0], E0, TODAY)] == ["RESULT_MISSING"]


def test_duplicate_rows_detected():
    kept, issues = split_duplicates(parse(csv(ROW_A, ROW_B, ROW_A)).matches)
    assert len(kept) == 2 and [i.code for i in issues] == ["DUPLICATE_ROW"]


# ---- storage, idempotency, versioning -------------------------------------

def test_ingest_stores_matches_odds_and_attribution(session):
    run = load(session, csv(ROW_A, ROW_B))
    assert (run.status, run.matches_inserted, run.rows_rejected) == ("success", 2, 0)
    m = session.scalars(select(Match).order_by(Match.match_date)).first()
    assert (m.home_goals, m.away_goals, m.status, m.version, m.first_run_id) == (4, 2, "finished", 1, run.id)
    assert session.scalar(select(func.count()).select_from(OddsQuote).where(OddsQuote.match_id == m.id)) == 13
    assert session.scalar(select(func.count()).select_from(MatchVersion)) == 2


def test_same_file_is_skipped_and_same_content_is_unchanged(session):
    load(session, csv(ROW_A, ROW_B))
    assert load(session, csv(ROW_A, ROW_B)).status == "skipped_unchanged"
    run = load(session, csv(ROW_B, ROW_A))  # different bytes, same matches
    assert (run.matches_inserted, run.matches_updated, run.matches_unchanged) == (0, 0, 2)
    assert session.scalar(select(func.count()).select_from(Match)) == 2


def test_changed_match_gets_new_version_and_keeps_history(session):
    load(session, csv(ROW_A))
    run = load(session, csv(ROW_A.replace(",19,10,10,3,", ",20,10,10,3,")))
    assert run.matches_updated == 1
    m = session.scalars(select(Match)).one()
    session.refresh(m)
    assert m.version == 2 and m.last_run_id == run.id
    versions = session.scalars(select(MatchVersion).order_by(MatchVersion.version)).all()
    assert [v.version for v in versions] == [1, 2]
    assert '"home_shots":19' in versions[0].payload_json and '"home_shots":20' in versions[1].payload_json


def test_rejected_rows_are_not_stored_but_are_logged(session):
    run = load(session, csv(ROW_A.replace(",4,2,H,", ",4,2,D,"), ROW_B))
    assert (run.matches_inserted, run.rows_rejected) == (1, 1)
    issue = session.scalars(select(ValidationIssue)).one()
    assert (issue.severity, issue.code, issue.row_number) == ("error", "RESULT_MISMATCH", 2)


def test_fixture_becomes_result_without_duplicating(session):
    fixture = "E0,21/11/2026,15:00,Alpha,Beta,,,,,,,,,,,2.0,3.5,3.8,1.9,1.9,,,,,,,,,,"
    result = "E0,22/11/2026,15:00,Alpha,Beta,1,0,H,0,0,D,9,4,3,1,2.0,3.5,3.8,1.9,1.9,,,,2.1,3.4,3.7,1.95,1.85,,"
    kw = dict(league=E0, source_key="csv_upload", origin="f.csv")
    ingest_bytes(session, csv(fixture), today=TODAY, **kw)
    assert session.scalars(select(Match)).one().status == "scheduled"
    ingest_bytes(session, csv(result), today=date(2026, 11, 23), **kw)
    m = session.scalars(select(Match)).one()
    session.refresh(m)
    assert (m.status, m.version, m.match_date, m.season) == ("finished", 2, date(2026, 11, 22), "2026/2027")


def test_malformed_file_fails_the_run_cleanly(session):
    run = load(session, b"not,a,football,file\n1,2,3,4\n")
    assert run.status == "failed" and "required columns" in run.error
    assert session.scalar(select(func.count()).select_from(Match)) == 0
    assert session.scalar(select(func.count()).select_from(IngestionRun)) == 1
