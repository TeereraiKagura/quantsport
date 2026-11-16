"""Scheduled jobs.

daily   back up the database, update historical data, collect fixtures and
        their prices, store live forecasts, settle and place paper bets.
weekly  everything in daily, then refresh the walk-forward forecasts used for
        performance monitoring, re-run the ML comparison, and write the weekly
        quantitative audit.

Each step runs in isolation. A failure is logged to job_runs and to the log
file, and the remaining steps still run, so one provider outage does not stop
the rest of the pipeline.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from typing import Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from quantsport.config import Settings
from quantsport.data import ingest
from quantsport.data.leagues import LEAGUES
from quantsport.db.models import JobRun, Portfolio, utcnow

log = logging.getLogger(__name__)


def run_step(session: Session, job: str, step: str, fn: Callable[[], str]) -> JobRun:
    started = utcnow()
    try:
        detail, status = fn(), "ok"
    except Exception as exc:
        session.rollback()
        log.exception("Job %s step %s failed", job, step)
        detail, status = f"{type(exc).__name__}: {exc}", "failed"
    run = JobRun(job=job, step=step, status=status, detail=str(detail)[:2000], started_at=started,
                 finished_at=utcnow())
    session.add(run)
    session.commit()
    return run


def _ingest_summary(runs) -> str:
    counts = Counter(r.status for r in runs)
    new = sum(r.matches_inserted for r in runs)
    updated = sum(r.matches_updated for r in runs)
    if runs and counts["failed"] == len(runs):
        raise RuntimeError(f"all {len(runs)} downloads failed: {runs[0].error}")
    return (f"{len(runs)} files: {counts['success']} loaded, {counts['skipped_unchanged']} unchanged, "
            f"{counts['failed']} failed; {new} new matches, {updated} updated")


def daily_steps(engine: Engine, session: Session, settings: Settings, today: date) -> dict[str, Callable[[], str]]:
    from quantsport.jobs.backup import backup_database
    from quantsport.ml.pipeline import predict_upcoming_ml
    from quantsport.models.walkforward import predict_upcoming
    from quantsport.risk import paper

    leagues = list(LEAGUES)

    def predictions() -> str:
        stat = sum(predict_upcoming(engine, session, code, today) for code in leagues)
        ml = predict_upcoming_ml(engine, session, today)
        return f"{stat} statistical and {ml} ML live forecasts stored"

    def paper_trading() -> str:
        names = list(session.scalars(select(Portfolio.name)))
        now = utcnow()
        parts = [f"{name}: {paper.settle(engine, session, name, now)} settled, "
                 f"{len(paper.place(engine, session, name, now))} placed" for name in names]
        return "; ".join(parts) or "no paper portfolios"

    return {
        "backup": lambda: f"written {backup_database(settings).name}",
        "historical_data": lambda: _ingest_summary(ingest.ingest_football_data(session, settings, leagues, today)),
        "fixtures_and_odds": lambda: _ingest_summary(ingest.ingest_fixtures(session, settings, leagues, today)),
        "predictions": predictions,
        "paper_trading": paper_trading,
    }


def weekly_steps(engine: Engine, session: Session, settings: Settings, today: date) -> dict[str, Callable[[], str]]:
    from quantsport.jobs import audit
    from quantsport.ml import report as ml_report
    from quantsport.models import report as model_report

    def monitoring() -> str:
        preds, _, tested = model_report.evaluate(engine, session, list(LEAGUES), today)
        return f"walk-forward refreshed: {preds.match_id.nunique()} matches forecast across {len(tested)} leagues"

    def ml_models() -> str:
        settings.reports_dir.mkdir(parents=True, exist_ok=True)
        out = settings.reports_dir / f"phase5_ml_{utcnow():%Y%m%d}.md"
        out.write_text(ml_report.run(engine, session, today), encoding="utf-8")
        return f"written {out.name}"

    def weekly_audit() -> str:
        settings.reports_dir.mkdir(parents=True, exist_ok=True)
        out = settings.reports_dir / f"weekly_audit_{utcnow():%Y%m%d}.md"
        out.write_text(audit.render(engine, session, today), encoding="utf-8")
        return f"written {out.name}"

    return {**daily_steps(engine, session, settings, today),
            "performance_monitoring": monitoring, "ml_models": ml_models, "weekly_audit": weekly_audit}


def run_job(job: str, engine: Engine, session: Session, settings: Settings, today: date) -> list[JobRun]:
    steps = (weekly_steps if job == "weekly" else daily_steps)(engine, session, settings, today)
    return [run_step(session, job, name, fn) for name, fn in steps.items()]
