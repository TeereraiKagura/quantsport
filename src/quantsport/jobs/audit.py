"""Weekly quantitative audit.

Ten sections, each scored OK / Warning / Problem / Insufficient data by a
stated rule. The audit never infers significance from small samples: where a
minimum number of observations is not met it says so and gives no verdict.

Sample-size minimums (conventional, not tuned):
    forecast accuracy        100 scored matches
    calibration              200 forecasts
    strategy, CLV             30 bets
    deterioration             50 matches in the recent window
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from quantsport.backtest.engine import roi_interval
from quantsport.backtest.report import EV_GRID, MODELS as BACKTEST_MODELS
from quantsport.data import quality
from quantsport.data.leagues import LEAGUES
from quantsport.db.models import Portfolio, utcnow
from quantsport.ml import estimators as est
from quantsport.ml import report as mlr
from quantsport.models import walkforward as wf
from quantsport.models.report import _md
from quantsport.risk import monitoring, paper, simulation
from quantsport.risk import report as risk_report
from quantsport.risk.paper import DEFAULT_MODELS

OK, WARN, BAD, NA = "OK", "Warning", "Problem", "Insufficient data"
MARKET_COLUMNS = {"OU": ("OU2.5", ["over", "under"]), "1X2": ("1X2", ["H", "D", "A"])}
RECENT_DAYS = 28


def match_losses(engine: Engine, today: date) -> pd.DataFrame:
    """Per match and default model: log loss of the model and of the closing
    market, on matches where both exist. Columns: market, model, match_id,
    match_date, split, ll_model, ll_market, p_ref (probability of the market's
    first selection) and hit_ref (whether it happened)."""
    matches, val_ids, test_ids = mlr._splits(engine, today)
    wide = mlr.wide_predictions(engine)
    if wide.empty:
        return pd.DataFrame()
    actual = pd.concat([wf.outcomes(engine, code) for code in LEAGUES], ignore_index=True).set_index("match_id")
    market = pd.concat([wf._market_benchmark(engine, c, matches[matches.league == c]) for c in LEAGUES],
                       ignore_index=True)
    dates = matches.set_index("match_id").match_date
    rows = []
    for mkt, model in DEFAULT_MODELS.items():
        outcome_col, selections = MARKET_COLUMNS[mkt]
        if not set(selections) <= set(wide.columns) or market.empty:
            continue
        m = wide[wide.model == model].set_index("match_id")[selections].dropna()
        b = market.set_index("match_id")[selections].dropna()
        ids = m.index.intersection(b.index).intersection(actual.index)
        if len(ids) == 0:
            continue
        hit = actual.loc[ids, outcome_col].to_numpy()[:, None] == np.array(selections)[None, :]
        rows.append(pd.DataFrame({
            "market": mkt, "model": model, "match_id": ids, "match_date": dates.loc[ids].to_numpy(),
            "split": np.where(np.isin(ids, list(test_ids)), "test",
                              np.where(np.isin(ids, list(val_ids)), "validation", "other")),
            "ll_model": -np.log(np.clip((m.loc[ids].to_numpy() * hit).sum(axis=1), 1e-12, 1)),
            "ll_market": -np.log(np.clip((b.loc[ids].to_numpy() * hit).sum(axis=1), 1e-12, 1)),
            "p_ref": m.loc[ids, selections[0]].to_numpy(), "hit_ref": hit[:, 0],
        }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def mean_ci(values: np.ndarray, n_boot: int = 5000, seed: int = 12345) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(n_boot, len(values)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(values.mean()), float(lo), float(hi)


def expected_calibration_error(p: np.ndarray, hit: np.ndarray, bins: int = 10) -> float:
    """ECE = sum over probability bins of (share of forecasts in the bin) x
    |mean forecast - observed frequency|."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        mask = idx == b
        if mask.any():
            ece += mask.mean() * abs(p[mask].mean() - hit[mask].mean())
    return float(ece)


def deterioration(losses: pd.DataFrame, today: date, min_recent: int = 50, seed: int = 12345) -> dict:
    """Has the model's log loss relative to the market got worse recently?
    Compares mean (model - market) log loss in the last RECENT_DAYS days with
    the rest of the test season, with a two-sample bootstrap interval."""
    cutoff = pd.Timestamp(today - timedelta(days=RECENT_DAYS))
    excess = losses.ll_model - losses.ll_market
    recent, earlier = excess[losses.match_date >= cutoff].to_numpy(), excess[losses.match_date < cutoff].to_numpy()
    out = {"recent_matches": len(recent), "earlier_matches": len(earlier)}
    if len(recent) < min_recent or len(earlier) < min_recent:
        return {**out, "status": NA}
    rng = np.random.default_rng(seed)
    diff = (recent[rng.integers(0, len(recent), (5000, len(recent)))].mean(axis=1)
            - earlier[rng.integers(0, len(earlier), (5000, len(earlier)))].mean(axis=1))
    lo, hi = np.percentile(diff, [2.5, 97.5])
    return {**out, "change": round(float(recent.mean() - earlier.mean()), 4), "ci95_low": round(float(lo), 4),
            "ci95_high": round(float(hi), 4), "status": WARN if lo > 0 else OK}


def _data_quality(engine: Engine, today: date) -> tuple[str, str, str]:
    week = utcnow() - timedelta(days=7)
    runs = pd.read_sql("SELECT status, started_at FROM ingestion_runs", engine, parse_dates=["started_at"])
    recent = runs[runs.started_at >= week] if len(runs) else runs
    failed = int((recent.status == "failed").sum()) if len(recent) else 0
    good = int(recent.status.isin(["success", "skipped_unchanged"]).sum()) if len(recent) else 0
    issues = pd.read_sql("SELECT v.severity, r.started_at FROM validation_issues v JOIN ingestion_runs r "
                         "ON r.id = v.run_id", engine, parse_dates=["started_at"])
    errors = int(((issues.severity == "error") & (issues.started_at >= week)).sum()) if len(issues) else 0
    last = pd.read_sql("SELECT l.code AS league, MAX(m.match_date) AS last_match FROM matches m JOIN leagues l "
                       "ON l.id = m.league_id WHERE m.status = 'finished' GROUP BY l.code", engine,
                       parse_dates=["last_match"])
    if last.empty:
        return NA, "no matches stored", "_No data has been ingested._"
    last["days_old"] = (pd.Timestamp(today) - last.last_match).dt.days
    stale = last[last.days_old > 21]
    status = BAD if good == 0 else WARN if failed or errors or len(stale) else OK
    key = f"{good} successful and {failed} failed ingestion runs in 7 days; newest result {int(last.days_old.min())} days old"
    body = "\n\n".join([
        f"- Ingestion runs in the last 7 days: {good} successful, {failed} failed.\n"
        f"- Rows rejected by validation in the last 7 days: {errors}.\n"
        f"- Leagues with no result for more than 21 days: "
        f"{', '.join(stale.league) if len(stale) else 'none'} (expected outside the season).",
        _md(last.assign(last_match=last.last_match.dt.date)),
        "Coverage by league and season:", _md(quality.coverage_table(engine)[[
            "league", "season", "finished", "scheduled", "shots_%", "xg_%", "1X2_closing_%", "OU2.5_pre_close_%"]]),
    ])
    return status, key, body


def render(engine: Engine, session: Session, today: date) -> str:
    scorecard, sections, recommendations = [], [], []

    def add(number: int, title: str, status: str, key: str, body: str) -> None:
        scorecard.append({"#": number, "area": title, "status": status, "key figure": key})
        sections.append(f"## {number}. {title}\n\n**Status: {status}.** {key}\n\n{body}")

    # 1. Data quality
    status, key, body = _data_quality(engine, today)
    add(1, "Data quality", status, key, body)
    scheduled = int(pd.read_sql("SELECT COUNT(*) AS n FROM matches WHERE status = 'scheduled'", engine).n[0])
    if scheduled == 0:
        recommendations.append("No upcoming fixtures are stored, so no live forecasts or paper bets can be made. "
                               "Connect a fixtures and live-odds source (for example the OddAlerts API).")

    losses = match_losses(engine, today)
    test = losses[losses.split == "test"] if len(losses) else losses
    val = losses[losses.split == "validation"] if len(losses) else losses

    # 2. Model accuracy
    rows, statuses = [], []
    for (mkt, model), g in (test.groupby(["market", "model"]) if len(test) else []):
        n = len(g)
        row = {"market": mkt, "model": model, "test_matches": n}
        if n < 100:
            row["finding"] = "insufficient observations (fewer than 100) for a significance statement"
            statuses.append(NA)
        else:
            mean, lo, hi = mean_ci((g.ll_model - g.ll_market).to_numpy())
            row.update(model_log_loss=round(g.ll_model.mean(), 4), market_log_loss=round(g.ll_market.mean(), 4),
                       difference=round(mean, 4), ci95_low=round(lo, 4), ci95_high=round(hi, 4))
            row["finding"] = ("worse than the closing market" if lo > 0 else
                              "better than the closing market" if hi < 0 else "not distinguishable from the market")
            statuses.append(BAD if lo > 0 else OK if hi < 0 else WARN)
        rows.append(row)
    acc_status = NA if not statuses else BAD if BAD in statuses else WARN if WARN in statuses else \
        NA if all(s == NA for s in statuses) else OK
    add(2, "Model accuracy", acc_status,
        "; ".join(f"{r['market']} {r['model']}: {r['finding']}" for r in rows) or "no scored forecasts",
        "Default model per market against the margin-free closing market on the test season. "
        "Difference = model log loss minus market log loss (positive is worse), 95% paired bootstrap interval.\n\n"
        + (_md(pd.DataFrame(rows)) if rows else "_No forecasts with closing prices._"))
    if BAD in statuses:
        recommendations.append("The default models are measurably worse than the closing market. Treat every "
                               "positive expected value they report as model error until this changes.")

    # 3. Calibration
    rows, statuses = [], []
    for (mkt, model), g in (test.groupby(["market", "model"]) if len(test) else []):
        ref = MARKET_COLUMNS[mkt][1][0]
        row = {"market": mkt, "model": model, "outcome": ref, "forecasts": len(g)}
        if len(g) < 200:
            row["finding"] = "insufficient observations (fewer than 200)"
            statuses.append(NA)
        else:
            ece = expected_calibration_error(g.p_ref.to_numpy(), g.hit_ref.to_numpy().astype(float))
            row.update(mean_forecast=round(g.p_ref.mean(), 4), observed_frequency=round(g.hit_ref.mean(), 4),
                       ece=round(ece, 4), finding="within 5 points" if ece <= 0.05 else "miscalibrated by over 5 points")
            statuses.append(OK if ece <= 0.05 else WARN)
        rows.append(row)
    cal_status = NA if not statuses or all(s == NA for s in statuses) else WARN if WARN in statuses else OK
    add(3, "Probability calibration", cal_status,
        "; ".join(f"{r['market']}: ECE {r.get('ece', 'n/a')}" for r in rows) or "no forecasts",
        "Expected calibration error over ten probability bins, test season. ECE above 0.05 is flagged.\n\n"
        + (_md(pd.DataFrame(rows)) if rows else "_No forecasts._"))

    # 4-5, 7-9. Strategy, CLV, risk, reliability, overfitting share the test-season bets
    bets, info = risk_report.build_bets(engine, today)
    ledger = simulation.replay(bets, simulation.POLICIES["flat 0.25% of start"], risk_report.RiskConfig()) \
        if len(bets) else pd.DataFrame()
    summary = simulation.summarize(ledger) if len(ledger) else {}
    names = list(session.scalars(select(Portfolio.name)))
    paper_rows = [{k: v for k, v in paper.status(engine, session, n).items() if k != "stake_review"} for n in names]
    paper_text = ("Paper trading (separate ledger):\n\n" + _md(pd.DataFrame(paper_rows))) if paper_rows else \
        "No paper portfolio exists."
    settled_paper = sum(r.get("settled_bets", 0) for r in paper_rows)

    if len(ledger) < 30:
        add(4, "Betting strategy performance", NA, f"{len(ledger)} backtest bets; fewer than 30",
            "Insufficient observations for any statement about profitability.\n\n" + paper_text)
        add(5, "Closing line value", NA, f"{len(ledger)} bets", "Insufficient observations.")
    else:
        lo, hi = roi_interval(ledger)
        roi = summary["roi_pct"]
        status = BAD if hi < 0 else OK if lo > 0 else WARN
        finding = ("losing beyond chance" if hi < 0 else "profitable beyond chance" if lo > 0
                   else "not distinguishable from break-even")
        add(4, "Betting strategy performance", status,
            f"backtest ROI {roi:+.1f}% on {len(ledger)} bets (95% interval {100 * lo:+.1f}% to {100 * hi:+.1f}%): {finding}",
            "Historical backtest of the default models on the test season, flat stakes, Bet365 pre-closing "
            "prices, thresholds chosen on validation. A backtest is not live performance.\n\n"
            + _md(info) + f"\n\n{paper_text}\n\nSettled paper bets: {settled_paper}. "
            + ("Paper results are too few for any conclusion." if settled_paper < 30 else ""))
        ev = monitoring.scaling_evidence(ledger, risk_report.RiskConfig().min_bets_to_scale)
        clv_status = NA if ev["mean_clv_pct"] is None else BAD if ev["clv_ci95_high"] < 0 else \
            OK if ev["clv_ci95_low"] > 0 else WARN
        add(5, "Closing line value", clv_status,
            f"mean CLV {ev['mean_clv_pct']}% (95% interval {ev['clv_ci95_low']} to {ev['clv_ci95_high']}) on "
            f"{ev['bets_with_clv']} bets",
            "CLV = price taken x closing fair probability - 1. Persistently negative CLV means the bets are, on "
            "average, worse than the closing price, which is the strongest available sign of no edge.")
        if clv_status == BAD:
            recommendations.append("Closing line value is negative beyond chance. Do not increase stakes, and do "
                                   "not move from paper trading to real money.")

    # 6. Model deterioration
    rows = []
    for (mkt, model), g in (test.groupby(["market", "model"]) if len(test) else []):
        rows.append({"market": mkt, "model": model, **deterioration(g, today)})
    statuses = [r["status"] for r in rows]
    det_status = NA if not statuses or all(s == NA for s in statuses) else WARN if WARN in statuses else OK
    add(6, "Model deterioration", det_status,
        "; ".join(f"{r['market']}: {r['recent_matches']} recent matches, {r['status']}" for r in rows) or "no data",
        f"Change in (model - market) log loss between the last {RECENT_DAYS} days and the earlier test season. "
        "A positive change with an interval above zero would mean the model is getting worse. With fewer than "
        "50 matches on either side, no statement is made.\n\n" + (_md(pd.DataFrame(rows)) if rows else "_No data._"))

    # 7. Financial risk
    if not summary or summary["bets_placed"] == 0:
        add(7, "Financial risk", NA, "no bets", "No bets to assess.")
    else:
        mc = simulation.monte_carlo(ledger, ledger.closing_fair_prob.fillna(1 / ledger.price).to_numpy())
        streak_ok = summary["longest_losing_streak"] <= 1.5 * summary["expected_longest_streak"]
        status = WARN if summary["max_drawdown_pct"] > 20 or not streak_ok else OK
        open_exposure = sum(r.get("open_exposure", 0) for r in paper_rows)
        add(7, "Financial risk", status,
            f"max drawdown {summary['max_drawdown_pct']}%, longest losing streak {summary['longest_losing_streak']} "
            f"(chance alone gives about {summary['expected_longest_streak']})",
            f"- Flat-stake backtest: final bankroll {summary['final_bankroll']} from 1000, largest daily exposure "
            f"{summary['max_daily_exposure_pct']}%.\n"
            f"- If the closing market's probabilities are right, simulated probability of ending with a loss: "
            f"{mc['prob_loss_pct']}%; mean maximum drawdown {mc['mean_max_drawdown_pct']}%.\n"
            f"- Open paper exposure: {open_exposure}.\n"
            "- Flagged when drawdown exceeds 20% or the losing streak exceeds 1.5 times what chance gives.")

    # 8. Backtesting reliability
    stamped = pd.read_sql("SELECT COUNT(*) AS n, SUM(CASE WHEN observed_at IS NULL THEN 1 ELSE 0 END) AS missing "
                          "FROM odds_quotes", engine).iloc[0]
    share = 100.0 * stamped.missing / stamped.n if stamped.n else float("nan")
    from quantsport.backtest.engine import BacktestConfig, candidates, load_data
    _, cov = candidates(engine, BacktestConfig(model=DEFAULT_MODELS["OU"]), today, load_data(engine))
    priced = 100.0 * cov["with_price"] / cov["finished_matches"] if cov["finished_matches"] else float("nan")
    add(8, "Backtesting reliability", WARN if share > 0 or priced < 80 else OK,
        f"{share:.0f}% of prices have no collection time; {priced:.0f}% of test-season matches could be bet",
        f"- Test-season matches: {cov['finished_matches']} finished, {cov['with_forecast']} with a forecast, "
        f"{cov['with_price']} with a price.\n"
        "- Prices without a collection time cannot be proven to have been obtainable, so every backtest ROI is an "
        "upper bound on what was achievable.\n"
        "- Stake limits, account restrictions and price slippage are not modelled.")
    if share > 0:
        recommendations.append("Obtain timestamped odds. Without them no backtest can show that a price was "
                               "actually available, and odds movement can only be approximated.")

    # 9. Potential overfitting
    rows = []
    for r in info.itertuples() if len(info) else []:
        mkt_led = ledger[ledger.market == r.market] if len(ledger) else ledger
        test_roi = 100 * mkt_led.profit.sum() / mkt_led.stake.sum() if len(mkt_led) else None
        v = val[val.market == r.market] if len(val) else val
        t = test[test.market == r.market] if len(test) else test
        rows.append({"market": r.market, "model": r.model, "validation_roi_pct": r.validation_roi_pct,
                     "test_roi_pct": None if test_roi is None else round(test_roi, 2),
                     "validation_excess_log_loss": round(float((v.ll_model - v.ll_market).mean()), 4) if len(v) else None,
                     "test_excess_log_loss": round(float((t.ll_model - t.ll_market).mean()), 4) if len(t) else None})
    gaps = [r["validation_roi_pct"] - r["test_roi_pct"] for r in rows
            if r["validation_roi_pct"] is not None and r["test_roi_pct"] is not None]
    tried = len(EV_GRID) * len(BACKTEST_MODELS) * 2
    ml_cells = sum(len(est.grid(n)) for n in est.MODEL_NAMES) * 3
    over_status = NA if not gaps else WARN if max(gaps) > 10 else OK
    add(9, "Potential overfitting", over_status,
        (f"largest validation-to-test ROI drop {max(gaps):.1f} points" if gaps else "no comparable results"),
        f"- Backtest configurations examined on validation: {tried} (threshold grid x models x markets). "
        f"ML hyperparameter settings examined: {ml_cells}. The more settings are tried, the more of the best "
        "validation result is luck.\n- A validation ROI more than 10 points above the test ROI is flagged.\n\n"
        + (_md(pd.DataFrame(rows)) if rows else "_No results._"))
    if gaps and max(gaps) > 10:
        recommendations.append("Validation results did not carry over to the test season. Do not select strategies "
                               "on validation ROI from samples this small; extend the history first.")

    # 10. Recommendations
    seasons = pd.read_sql("SELECT COUNT(DISTINCT season) AS n FROM matches", engine).n[0]
    if seasons <= 4:
        recommendations.append("Only the current season and the one before are stored. More seasons would give the "
                               "models and the validation step far more to work with.")
    recommendations.append("Platt calibration made ML forecasts worse on both validation and test in the Phase 5 "
                           "report; consider storing uncalibrated ML probabilities.")
    recommendations.append("xG and player availability are not model inputs. xG history is one season long and no "
                           "licensed source for injuries or lineups is connected.")
    add(10, "Recommended improvements", "See list", f"{len(recommendations)} recommendations",
        "\n".join(f"{i}. {text}" for i, text in enumerate(recommendations, 1)))

    by_area = {r["area"]: r["status"] for r in scorecard}
    edge = (by_area.get("Model accuracy") == OK and by_area.get("Closing line value") == OK
            and by_area.get("Betting strategy performance") == OK)
    insufficient = [r["area"] for r in scorecard if r["status"] == NA]
    verdict = ("The evidence supports a predictive advantage over the market." if edge else
               "There is no statistically defensible predictive advantage. Stakes should not be increased and "
               "operation should remain paper trading only.")
    summary_lines = [
        f"- **Verdict:** {verdict}",
        f"- Problems: {', '.join(r['area'] for r in scorecard if r['status'] == BAD) or 'none'}.",
        f"- Warnings: {', '.join(r['area'] for r in scorecard if r['status'] == WARN) or 'none'}.",
        f"- Insufficient observations for a verdict: {', '.join(insufficient) or 'none'}.",
    ]
    return "\n\n".join([
        f"# Weekly quantitative audit, {today:%d %B %Y}",
        f"Generated {utcnow():%Y-%m-%d %H:%M} UTC. Backtest, out-of-sample forecast and paper-trading results are "
        "reported separately and are never combined.",
        "## Executive summary", "\n".join(summary_lines),
        "## Scorecard", _md(pd.DataFrame(scorecard)),
        *sections,
    ]) + "\n"
