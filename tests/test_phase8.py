"""Phase 8 tests. All data here is SYNTHETIC."""

import sqlite3
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from quantsport import config
from quantsport.db import init_db, make_engine
from quantsport.db.models import JobRun
from quantsport.jobs import audit, backup, pipeline
from quantsport.ml import estimators as est
from quantsport.ml.features import build_features
from quantsport.ml.pipeline import TARGETS, live_probabilities

TODAY = date(2026, 11, 16)


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{(tmp_path / 'data' / 'qs.db').as_posix()}"
    engine = make_engine(url)
    init_db(engine)
    settings = replace(config.get_settings(), database_url=url, raw_dir=tmp_path / "raw",
                       reports_dir=tmp_path / "reports", log_dir=tmp_path / "logs")
    with Session(engine) as session:
        yield engine, session, settings


# ---- job pipeline ----------------------------------------------------------

def test_a_failing_step_is_logged_and_the_rest_still_run(db):
    engine, session, settings = db
    calls = []

    def ok(name):
        return lambda: calls.append(name) or f"{name} done"

    def boom():
        raise ConnectionError("provider unreachable")

    steps = {"backup": ok("backup"), "historical_data": boom, "predictions": ok("predictions")}
    runs = [pipeline.run_step(session, "daily", name, fn) for name, fn in steps.items()]
    assert [r.status for r in runs] == ["ok", "failed", "ok"] and calls == ["backup", "predictions"]
    stored = session.scalars(select(JobRun).order_by(JobRun.id)).all()
    assert [r.step for r in stored] == ["backup", "historical_data", "predictions"]
    assert stored[1].detail == "ConnectionError: provider unreachable"
    assert all(r.finished_at >= r.started_at for r in stored)


def test_job_definitions_cover_every_required_process(db):
    engine, session, settings = db
    daily = pipeline.daily_steps(engine, session, settings, TODAY)
    weekly = pipeline.weekly_steps(engine, session, settings, TODAY)
    assert list(daily) == ["backup", "historical_data", "fixtures_and_odds", "predictions", "paper_trading"]
    assert list(weekly) == list(daily) + ["performance_monitoring", "ml_models", "weekly_audit"]


def test_daily_job_survives_a_provider_outage(db, monkeypatch):
    engine, session, settings = db

    def offline(url, settings):
        raise ConnectionError("no network")

    monkeypatch.setattr("quantsport.data.sources.fetch", offline)
    runs = {r.step: r for r in pipeline.run_job("daily", engine, session, settings, TODAY)}
    assert runs["backup"].status == "ok"
    assert runs["historical_data"].status == "failed" and "downloads failed" in runs["historical_data"].detail
    assert runs["fixtures_and_odds"].status == "failed"
    assert runs["predictions"].status == "ok" and runs["predictions"].detail.startswith("0 statistical")
    assert runs["paper_trading"].detail == "no paper portfolios"


def test_ingest_summary():
    class R:
        def __init__(self, status, new=0, upd=0, error=None):
            self.status, self.matches_inserted, self.matches_updated, self.error = status, new, upd, error

    text = pipeline._ingest_summary([R("success", 10, 2), R("skipped_unchanged"), R("failed", error="x")])
    assert text == "3 files: 1 loaded, 1 unchanged, 1 failed; 10 new matches, 2 updated"
    with pytest.raises(RuntimeError):
        pipeline._ingest_summary([R("failed", error="timeout"), R("failed", error="timeout")])


# ---- backups ---------------------------------------------------------------

def test_backup_is_a_readable_copy_and_old_copies_are_pruned(db):
    engine, session, settings = db
    target = backup.backup_database(settings, keep=2)
    con = sqlite3.connect(target)
    assert con.execute("SELECT COUNT(*) FROM leagues").fetchone()[0] == 8
    con.close()
    for stamp in ("20200101_000000", "20200102_000000", "20200103_000000"):
        (target.parent / f"qs_{stamp}.db").write_bytes(b"old")
    backup.backup_database(settings, keep=2)
    names = sorted(p.name for p in target.parent.glob("qs_*.db"))
    # Both backups ran within one second and share a name, so the two newest
    # files are the fresh backup and the latest of the old ones.
    assert names == ["qs_20200103_000000.db", target.name]


def test_backup_refuses_non_file_databases():
    settings = replace(config.get_settings(), database_url="postgresql+psycopg://u:p@localhost/qs")
    with pytest.raises(RuntimeError, match="pg_dump"):
        backup.backup_database(settings)


# ---- live ML forecasts -----------------------------------------------------

def test_live_ml_forecasts_use_only_earlier_matches():
    from test_phase5 import simulate

    played = simulate()
    upcoming = played.iloc[-3:].assign(match_id=[9001, 9002, 9003], status="scheduled", home_goals=None,
                                       away_goals=None, match_date=played.match_date.max() + timedelta(days=5))
    feats = build_features(pd.concat([played, upcoming], ignore_index=True))
    today = played.match_date.max() + timedelta(days=1)
    chosen = {(name, target): est.grid(name)[0] for name in est.MODEL_NAMES for target in TARGETS}
    out = live_probabilities(feats, chosen, today)
    assert [name for name, _, _ in out] == est.MODEL_NAMES
    name, matches, probs = out[0]
    assert list(matches.match_id) == [9001, 9002, 9003]
    assert np.allclose(probs[("OU", 2.5, "over")] + probs[("OU", 2.5, "under")], 1)
    assert np.allclose(sum(probs[("1X2", 0.0, s)] for s in "HDA"), 1)
    assert live_probabilities(feats, chosen, played.match_date.min()) == []  # no training data yet


# ---- audit -----------------------------------------------------------------

def test_expected_calibration_error_by_hand():
    p = np.array([0.15, 0.15, 0.15, 0.15, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85])
    hit = np.array([0, 0, 0, 1, 1, 1, 1, 1, 1, 0], dtype=float)
    # bin 0.1-0.2: 4 forecasts, mean 0.15, observed 0.25 -> 0.4 * 0.10
    # bin 0.8-0.9: 6 forecasts, mean 0.85, observed 0.8333 -> 0.6 * 0.0167
    assert audit.expected_calibration_error(p, hit) == pytest.approx(0.4 * 0.10 + 0.6 * (0.85 - 5 / 6))
    assert audit.expected_calibration_error(np.array([0.5, 0.5]), np.array([1.0, 0.0])) == pytest.approx(0.0)


def losses_frame(recent_excess, earlier_excess, n=120):
    rng = np.random.default_rng(0)
    recent = pd.DataFrame({"match_date": pd.Timestamp(TODAY) - pd.to_timedelta(rng.integers(1, 27, n), unit="D"),
                           "ll_model": 0.65 + recent_excess + rng.normal(0, 0.05, n), "ll_market": 0.65})
    earlier = pd.DataFrame({"match_date": pd.Timestamp(TODAY) - pd.to_timedelta(rng.integers(40, 90, n), unit="D"),
                            "ll_model": 0.65 + earlier_excess + rng.normal(0, 0.05, n), "ll_market": 0.65})
    return pd.concat([recent, earlier], ignore_index=True)


def test_deterioration_detects_a_real_decline_and_ignores_none():
    worse = audit.deterioration(losses_frame(0.10, 0.02), TODAY)
    assert worse["status"] == audit.WARN and worse["change"] == pytest.approx(0.08, abs=0.02) and worse["ci95_low"] > 0
    assert audit.deterioration(losses_frame(0.02, 0.02), TODAY)["status"] == audit.OK


def test_deterioration_refuses_small_samples():
    small = audit.deterioration(losses_frame(0.10, 0.02, n=20), TODAY)
    assert small["status"] == audit.NA and "change" not in small


def test_audit_on_an_empty_database_claims_nothing(db):
    engine, session, settings = db
    text = audit.render(engine, session, TODAY)
    for n, title in enumerate(["Data quality", "Model accuracy", "Probability calibration",
                               "Betting strategy performance", "Closing line value", "Model deterioration",
                               "Financial risk", "Backtesting reliability", "Potential overfitting",
                               "Recommended improvements"], 1):
        assert f"## {n}. {title}" in text
    assert "## Executive summary" in text and "## Scorecard" in text
    assert "no statistically defensible predictive advantage" in text
    assert text.count("Insufficient data") >= 6
    assert "profitable" not in text.lower().replace("profitability", "")
