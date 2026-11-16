"""Tests for the openfootball fixture source. Team names and schedules here are
SYNTHETIC."""

import json
from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from quantsport import config
from quantsport.data import openfootball as of
from quantsport.data.ingest import ingest_bytes, ingest_openfootball
from quantsport.data.leagues import LEAGUES
from quantsport.db import init_db, make_engine
from quantsport.db.models import Match

TODAY = date(2026, 11, 16)
# stored (short) name -> name in the schedule file
NAMES = {"Man City": "Manchester City FC", "Man United": "Manchester United FC", "Leeds": "Leeds United FC",
         "Nott'm Forest": "Nottingham Forest FC", "Wolves": "Wolverhampton Wanderers FC", "Spurs": "Tottenham Hotspur FC"}


def schedule():
    """Double round robin: one round per week; rounds before TODAY are played."""
    teams = list(NAMES)
    rows, day = [], date(2026, 9, 5)
    for h in teams:
        for a in teams:
            if h != a:
                rows.append((day, h, a))
                day += timedelta(days=3)
    return rows


def stored_results(rows, shift=None):
    played = [(d, h, a) for d, h, a in rows if d < TODAY]
    if shift:
        played = [(d + timedelta(days=1) if i in shift else d, h, a) for i, (d, h, a) in enumerate(played)]
    return pd.DataFrame(played, columns=["match_date", "home", "away"])


def file_fixtures(rows, rename=NAMES):
    return pd.DataFrame([{"match_date": d, "time": "15:00", "home": rename[h], "away": rename[a],
                          "played": d < TODAY} for d, h, a in rows])


def test_names_are_matched_and_verified_by_the_schedule():
    rows = schedule()
    mapping = of.map_teams(file_fixtures(rows), stored_results(rows), TODAY)
    assert mapping.names == {v: k for k, v in NAMES.items()} and mapping.unmapped == []
    a = mapping.agreement
    assert a["played_fixtures_checked"] == a["pairing_found"] == a["date_identical"] > 15
    assert a["date_identical_pct"] == 100.0


def test_a_name_with_no_spelling_overlap_is_inferred_from_fixtures():
    # "Spurs" and "Wolves" share nothing with the long names: only the schedule can place them.
    rows = schedule()
    mapping = of.map_teams(file_fixtures(rows), stored_results(rows), TODAY)
    assert mapping.names["Tottenham Hotspur FC"] == "Spurs"
    assert mapping.names["Wolverhampton Wanderers FC"] == "Wolves"


def test_a_plausible_spelling_match_is_rejected_when_the_schedule_contradicts_it():
    """Swap the two Manchester clubs in the file: spelling says one thing, the
    played fixtures say the other, and the fixtures must win."""
    rows = schedule()
    swapped = {**NAMES, "Man City": "Manchester United FC", "Man United": "Manchester City FC"}
    mapping = of.map_teams(file_fixtures(rows, swapped), stored_results(rows), TODAY)
    assert mapping.names["Manchester United FC"] == "Man City"
    assert mapping.names["Manchester City FC"] == "Man United"


def test_unverifiable_team_is_left_unmapped_and_its_fixtures_skipped():
    rows = schedule()
    fixtures = file_fixtures(rows)
    newcomer = pd.DataFrame([{"match_date": TODAY + timedelta(days=5), "time": "15:00",
                              "home": "Brand New Town FC", "away": NAMES["Leeds"], "played": False}])
    fixtures = pd.concat([fixtures, newcomer], ignore_index=True)
    mapping = of.map_teams(fixtures, stored_results(rows), TODAY)
    assert mapping.unmapped == ["Brand New Town FC"]
    body, skipped = of.to_csv(fixtures, mapping, "E0", "Europe/London", TODAY, TODAY + timedelta(days=10))
    assert skipped == 1 and b"Brand New" not in body


def test_date_agreement_counts_rescheduled_matches():
    rows = schedule()
    mapping = of.map_teams(file_fixtures(rows), stored_results(rows, shift={0, 1, 2}), TODAY)
    a = mapping.agreement
    assert a["pairing_found"] == a["played_fixtures_checked"]  # one day off is still the same match
    assert a["date_identical"] == a["played_fixtures_checked"] - 3


def test_local_kickoff_time_is_converted_to_uk_time_and_then_utc():
    fixtures = pd.DataFrame([
        {"match_date": date(2026, 11, 21), "time": "15:30", "home": "A FC", "away": "B FC", "played": False},
        {"match_date": date(2026, 11, 22), "time": None, "home": "B FC", "away": "A FC", "played": False}])
    mapping = of.Mapping(names={"A FC": "Leeds", "B FC": "Wolves"})
    body, skipped = of.to_csv(fixtures, mapping, "D1", "Europe/Berlin", TODAY, date(2026, 11, 30))
    lines = body.decode().splitlines()
    assert lines[1] == "D1,21/11/2026,14:30,Leeds,Wolves"  # 15:30 in Berlin is 14:30 in the UK
    assert lines[2] == "D1,22/11/2026,,Wolves,Leeds" and skipped == 0  # unknown time stays unknown


def test_played_and_out_of_window_fixtures_are_not_exported():
    rows = schedule()
    fixtures = file_fixtures(rows)
    mapping = of.map_teams(fixtures, stored_results(rows), TODAY)
    body, _ = of.to_csv(fixtures, mapping, "E0", "Europe/London", TODAY, TODAY + timedelta(days=7))
    dates = [line.split(",")[1] for line in body.decode().splitlines()[1:]]
    assert dates and all(TODAY <= pd.to_datetime(d, dayfirst=True).date() <= TODAY + timedelta(days=7) for d in dates)


def test_url_and_parse():
    assert of.url("en.1", "2026/2027").endswith("/2026-27/en.1.json")
    raw = json.dumps({"matches": [
        {"date": "2026-11-21", "time": "15:00", "team1": "A", "team2": "B"},
        {"date": "2026-08-15", "team1": "B", "team2": "A", "score": {"ft": [1, 0]}}]}).encode()
    f = of.parse(raw)
    assert f.played.tolist() == [False, True] and f.time.tolist()[0] == "15:00" and pd.isna(f.time.tolist()[1])


def test_end_to_end_ingestion_stores_scheduled_fixtures(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{(tmp_path / 'of.db').as_posix()}")
    init_db(engine)
    rows = schedule()
    results_csv = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n" + "".join(
        f"E0,{d:%d/%m/%Y},15:00,{h},{a},1,0,H\n" for d, h, a in rows if d < TODAY)
    file_json = json.dumps({"matches": [
        {"date": d.isoformat(), "time": "15:00", "team1": NAMES[h], "team2": NAMES[a],
         **({"score": {"ft": [1, 0]}} if d < TODAY else {})} for d, h, a in rows]}).encode()
    monkeypatch.setattr("quantsport.data.sources.fetch", lambda url, settings: file_json)
    settings = config.get_settings()
    with Session(engine) as s:
        ingest_bytes(s, results_csv.encode(), league=LEAGUES["E0"], source_key="csv_upload", origin="r.csv",
                     today=TODAY, season_hint="2026/2027")
        (run, report), (none_run, note) = ingest_openfootball(s, settings, ["E0", "T1"], TODAY, days_ahead=10)
        assert none_run is None and note["note"] == "not covered by openfootball"
        assert run.status == "success" and report["teams_unmapped"] == [] and report["date_identical_pct"] == 100.0
        upcoming = s.scalars(select(Match).where(Match.status == "scheduled")).all()
        expected = [d for d, _, _ in rows if TODAY <= d <= TODAY + timedelta(days=10)]
        assert len(upcoming) == run.matches_inserted == len(expected) > 0
        assert all(m.kickoff_utc is not None and m.season == "2026/2027" for m in upcoming)
