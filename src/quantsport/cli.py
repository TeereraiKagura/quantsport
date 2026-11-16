"""Command line entry point: python -m quantsport <command>."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from quantsport.config import configure_logging, get_settings
from quantsport.data import ingest, quality
from quantsport.data.leagues import LEAGUES
from quantsport.db import init_db, make_engine, make_session_factory
from quantsport.db.models import IngestionRun, utcnow


def _print_runs(runs: list[IngestionRun]) -> None:
    for r in runs:
        print(f"run {r.id:>4} {r.status:<18} read={r.rows_read} out_of_scope={r.rows_out_of_scope} "
              f"new={r.matches_inserted} updated={r.matches_updated} unchanged={r.matches_unchanged} "
              f"rejected={r.rows_rejected} {r.origin}" + (f"  ERROR: {r.error}" if r.error else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantsport")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create tables and seed leagues")

    p = sub.add_parser("ingest", help="download historical results and odds")
    p.add_argument("--leagues", nargs="+", default=list(LEAGUES), choices=list(LEAGUES))
    p.add_argument("--seasons-back", type=int, default=1, help="previous seasons to include")

    p = sub.add_parser("ingest-fixtures", help="download upcoming fixtures")
    p.add_argument("--leagues", nargs="+", default=list(LEAGUES), choices=list(LEAGUES))

    p = sub.add_parser("ingest-csv", help="load a local CSV file")
    p.add_argument("path", type=Path)
    p.add_argument("--league", required=True, choices=list(LEAGUES))
    p.add_argument("--season", help="e.g. 2025/2026; needed for single-season files")

    p = sub.add_parser("walk-forward", help="out-of-sample evaluation of the statistical models")
    p.add_argument("--leagues", nargs="+", default=list(LEAGUES), choices=list(LEAGUES))
    p.add_argument("--no-store", action="store_true", help="do not save the forecasts")
    p.add_argument("--season", default="current", choices=["current", "previous"])

    p = sub.add_parser("predict-upcoming", help="store live forecasts for scheduled matches")
    p.add_argument("--leagues", nargs="+", default=list(LEAGUES), choices=list(LEAGUES))

    p = sub.add_parser("strengths", help="team strengths from data up to today")
    p.add_argument("--league", required=True, choices=list(LEAGUES))
    p.add_argument("--model", default="bayesian", choices=["bayesian", "poisson", "dixon_coles"])

    sub.add_parser("market-report", help="margins, price dispersion, movement and value screen")

    p = sub.add_parser("value", help="list forecasts with positive expected value at the best price")
    p.add_argument("--kind", default="live", choices=["live", "walk_forward"])
    p.add_argument("--leagues", nargs="+", default=list(LEAGUES), choices=list(LEAGUES))
    p.add_argument("--min-ev", type=float, default=0.0)
    p.add_argument("--min-odds", type=float, default=1.0)
    p.add_argument("--limit", type=int, default=40)

    p = sub.add_parser("backtest", help="simulate one betting strategy on historical data")
    p.add_argument("--model", default="dixon_coles")
    p.add_argument("--market", default="OU2.5", choices=["OU2.5", "1X2"])
    p.add_argument("--split", default="validation", choices=["validation", "test"],
                   help="validation = previous season, test = current season")
    p.add_argument("--leagues", nargs="+", choices=list(LEAGUES))
    p.add_argument("--min-ev", type=float, default=0.05)
    p.add_argument("--min-odds", type=float, default=1.0)
    p.add_argument("--max-odds", type=float, default=1000.0)
    p.add_argument("--price-source", default="Bet365", help="bookmaker name, or 'best'")
    p.add_argument("--staking", default="flat", choices=["flat", "percent", "kelly"])
    p.add_argument("--stake-pct", type=float, default=0.01)
    p.add_argument("--kelly-fraction", type=float, default=0.25)
    p.add_argument("--bankroll", type=float, default=1000.0)
    p.add_argument("--commission", type=float, default=0.0)

    sub.add_parser("backtest-report", help="validation-then-test backtest of every model")

    sub.add_parser("quality-report", help="write the data-quality report")
    sub.add_parser("runs", help="list recent ingestion runs")
    sub.add_parser("ml-run", help="tune, walk forward and compare the ML models and ensemble")
    sub.add_parser("risk-report", help="replay staking policies and simulate bankroll risk")
    p = sub.add_parser("job", help="run a scheduled job now")
    p.add_argument("name", choices=["daily", "weekly"])
    sub.add_parser("audit", help="write the weekly quantitative audit")
    sub.add_parser("backup", help="back up the database")
    sub.add_parser("job-log", help="show recent job steps")
    p = sub.add_parser("paper", help="paper-trading portfolios (no real money)")
    p.add_argument("action", choices=["create", "place", "settle", "status"])
    p.add_argument("--name", default="default")
    p.add_argument("--bankroll", type=float, default=1000.0)

    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings)
    engine = make_engine(settings.database_url)
    init_db(engine)
    today = date.today()

    with make_session_factory(engine)() as session:
        if args.command == "ingest":
            _print_runs(ingest.ingest_football_data(session, settings, args.leagues, today, args.seasons_back))
        elif args.command == "ingest-fixtures":
            _print_runs(ingest.ingest_fixtures(session, settings, args.leagues, today))
        elif args.command == "ingest-csv":
            _print_runs([ingest.ingest_csv_file(session, settings, args.path, args.league, today, args.season)])
        elif args.command == "walk-forward":
            from quantsport.models import report

            preds, actual, tested = report.evaluate(
                engine, None if args.no_store else session, args.leagues, today,
                seasons_ago=1 if args.season == "previous" else 0,
            )
            now = utcnow()
            text = report.render(preds, actual, tested, f"{now:%Y-%m-%d %H:%M}")
            settings.reports_dir.mkdir(parents=True, exist_ok=True)
            tag = "" if args.season == "current" else "_previous_season"
            out = settings.reports_dir / f"phase2_walkforward{tag}_{now:%Y%m%d}.md"
            out.write_text(text, encoding="utf-8")
            print(text)
            print(f"Written to {out}")
        elif args.command == "predict-upcoming":
            from quantsport.models.walkforward import predict_upcoming

            for code in args.leagues:
                print(f"{code}: {predict_upcoming(engine, session, code, today)} live forecasts stored")
        elif args.command == "strengths":
            from quantsport.models import BayesianStrengths, DixonColes, PoissonRegression
            from quantsport.models.store import load_matches, training_set

            model = {"bayesian": BayesianStrengths, "poisson": PoissonRegression,
                     "dixon_coles": DixonColes}[args.model]()
            train = training_set(load_matches(engine, args.league), today)
            model.fit(train, today)
            print(f"{args.model} strengths for {args.league}, {len(train)} matches before {today} "
                  "(1.0 = league average)")
            print(model.strengths().round(3).to_string())
        elif args.command == "market-report":
            from quantsport.market import report as market_report

            now = utcnow()
            text = market_report.render(engine, f"{now:%Y-%m-%d %H:%M}")
            settings.reports_dir.mkdir(parents=True, exist_ok=True)
            out = settings.reports_dir / f"phase3_market_{now:%Y%m%d}.md"
            out.write_text(text, encoding="utf-8")
            print(text)
            print(f"Written to {out}")
        elif args.command == "value":
            from quantsport.market import compare
            from quantsport.market.pricing import executability

            a = compare.value_assessments(engine, args.kind, args.leagues)
            if a.empty:
                print(f"No '{args.kind}' forecasts with matching prices.")
            else:
                a = a[(a.ev > args.min_ev) & (a.best_price >= args.min_odds)]
                now = utcnow()
                a["price_status"] = [
                    executability(False, s, None if pd.isna(o) else pd.Timestamp(o).to_pydatetime(), now)
                    for s, o in zip(a.status, a.observed_at)
                ]
                cols = ["league", "match_id", "model", "market", "line", "selection", "probability",
                        "best_price", "best_bookmaker", "fair_prob", "edge", "ev", "price_status"]
                print(a.sort_values("ev", ascending=False)[cols].head(args.limit).round(4).to_string(index=False))
                print(f"{len(a)} selections with EV > {args.min_ev}. Expected value is theoretical "
                      "unless price_status is 'current'.")
        elif args.command == "backtest":
            import json

            from quantsport.backtest.engine import BacktestConfig, run

            market, line = ("OU", 2.5) if args.market == "OU2.5" else ("1X2", 0.0)
            cfg = BacktestConfig(
                model=args.model, market=market, line=line, seasons_ago=1 if args.split == "validation" else 0,
                leagues=tuple(args.leagues) if args.leagues else None, min_ev=args.min_ev,
                min_odds=args.min_odds, max_odds=args.max_odds, price_source=args.price_source,
                staking=args.staking, stake_pct=args.stake_pct, kelly_fraction=args.kelly_fraction,
                initial_bankroll=args.bankroll, commission=args.commission,
            )
            summary, ledger, coverage = run(engine, cfg, today)
            print(f"Backtest on the {args.split} season (historical simulation, not live results)")
            print(json.dumps({"config": cfg.describe(), "coverage": coverage, "summary": summary}, indent=2))
            if len(ledger):
                settings.reports_dir.mkdir(parents=True, exist_ok=True)
                out = settings.reports_dir / f"backtest_ledger_{args.model}_{args.market}_{args.split}.csv"
                ledger.to_csv(out, index=False)
                print(f"Bet ledger written to {out}")
        elif args.command == "backtest-report":
            from quantsport.backtest import report as backtest_report

            now = utcnow()
            text = backtest_report.render(backtest_report.build(engine, today), f"{now:%Y-%m-%d %H:%M}")
            settings.reports_dir.mkdir(parents=True, exist_ok=True)
            out = settings.reports_dir / f"phase4_backtest_{now:%Y%m%d}.md"
            out.write_text(text, encoding="utf-8")
            print(text)
            print(f"Written to {out}")
        elif args.command == "ml-run":
            from quantsport.ml import report as ml_report

            text = ml_report.run(engine, session, today)
            settings.reports_dir.mkdir(parents=True, exist_ok=True)
            out = settings.reports_dir / f"phase5_ml_{utcnow():%Y%m%d}.md"
            out.write_text(text, encoding="utf-8")
            print(text)
            print(f"Written to {out}")
        elif args.command == "risk-report":
            from quantsport.risk import report as risk_report

            now = utcnow()
            text = risk_report.render(engine, today, f"{now:%Y-%m-%d %H:%M}")
            settings.reports_dir.mkdir(parents=True, exist_ok=True)
            out = settings.reports_dir / f"phase6_risk_{now:%Y%m%d}.md"
            out.write_text(text, encoding="utf-8")
            print(text)
            print(f"Written to {out}")
        elif args.command == "paper":
            import json

            from quantsport.risk import paper

            now = utcnow()
            if args.action == "create":
                paper.create(session, args.name, args.bankroll)
                print(f"Paper portfolio '{args.name}' created with a hypothetical bankroll of {args.bankroll}.")
            elif args.action == "place":
                bets = paper.place(engine, session, args.name, now)
                for b in bets:
                    print(f"match {b.match_id} {b.market} {b.selection} @ {b.odds} ({b.bookmaker}, "
                          f"price {b.price_status}) stake {b.stake:.2f}")
                print(f"{len(bets)} paper bets recorded. Prices marked 'indicative' were not verified as obtainable.")
            elif args.action == "settle":
                print(f"{paper.settle(engine, session, args.name, now)} paper bets settled.")
            else:
                print(json.dumps(paper.status(engine, session, args.name), indent=2, default=str))
        elif args.command == "job":
            from quantsport.jobs.pipeline import run_job

            runs = run_job(args.name, engine, session, settings, today)
            for r in runs:
                print(f"{r.status:<7} {r.step:<24} {r.detail}")
            failed = [r for r in runs if r.status == "failed"]
            print(f"{args.name} job finished: {len(runs) - len(failed)} steps ok, {len(failed)} failed.")
            return 1 if failed else 0
        elif args.command == "audit":
            from quantsport.jobs import audit

            text = audit.render(engine, session, today)
            settings.reports_dir.mkdir(parents=True, exist_ok=True)
            out = settings.reports_dir / f"weekly_audit_{utcnow():%Y%m%d}.md"
            out.write_text(text, encoding="utf-8")
            print(text)
            print(f"Written to {out}")
        elif args.command == "backup":
            from quantsport.jobs.backup import backup_database

            print(f"Backup written to {backup_database(settings)}")
        elif args.command == "job-log":
            from quantsport.db.models import JobRun

            for r in session.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(40)):
                print(f"{r.started_at:%Y-%m-%d %H:%M} {r.job:<7} {r.status:<7} {r.step:<24} {r.detail}")
        elif args.command == "quality-report":
            now = utcnow()
            text = quality.render_report(engine, f"{now:%Y-%m-%d %H:%M}")
            settings.reports_dir.mkdir(parents=True, exist_ok=True)
            out = settings.reports_dir / f"data_quality_{now:%Y%m%d}.md"
            out.write_text(text, encoding="utf-8")
            print(text)
            print(f"Written to {out}")
        elif args.command == "runs":
            _print_runs(list(session.scalars(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(40))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
