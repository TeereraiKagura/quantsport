"""Risk report: replay staking policies on the test season's historical bets."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from quantsport.backtest.engine import BacktestConfig, candidates, load_data, select_bets
from quantsport.backtest.report import EV_GRID, MIN_VALIDATION_BETS, BASE_STAKE_PCT
from quantsport.backtest.engine import run as backtest_run
from quantsport.market import compare
from quantsport.models.report import _md
from quantsport.risk import monitoring, simulation
from quantsport.risk.paper import DEFAULT_MODELS
from quantsport.risk.staking import RiskConfig, combined_sigma

LINES = {"OU": 2.5, "1X2": 0.0}


def model_error(cands: pd.DataFrame) -> float:
    """RMS gap between model probability and closing fair probability."""
    gap = (cands.probability - cands.closing_fair_prob).dropna()
    return float(np.sqrt((gap**2).mean())) if len(gap) else float("nan")


def build_bets(engine: Engine, today) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Test-season bets of the default model per market, with sigma attached.
    The EV threshold and the model error both come from the validation season."""
    data = load_data(engine)
    preds = data[1]
    if preds.empty:
        return pd.DataFrame(), pd.DataFrame()
    spread =(preds[preds.model != "base_rate"].groupby(compare.SELECTION_KEY).probability.std(ddof=0)
              .rename("disagreement").reset_index())
    bets, info = [], []
    for market, model in DEFAULT_MODELS.items():
        base = BacktestConfig(model=model, market=market, line=LINES[market], stake_pct=BASE_STAKE_PCT)
        best = None
        for min_ev in EV_GRID:
            s, _, _ = backtest_run(engine, replace(base, seasons_ago=1, min_ev=min_ev), today, data)
            if s["bets"] >= MIN_VALIDATION_BETS and (best is None or s["roi_pct"] > best[1]):
                best = (min_ev, s["roi_pct"])
        val_cands, _ = candidates(engine, replace(base, seasons_ago=1), today, data)
        err = model_error(val_cands)
        row = {"market": market, "model": model, "validation_model_error": round(err, 4),
               "chosen_min_ev": None if best is None else best[0],
               "validation_roi_pct": None if best is None else best[1], "test_bets": 0}
        if best is not None:
            cands, _ = candidates(engine, base, today, data)
            chosen = select_bets(cands, replace(base, min_ev=best[0]))
            chosen = chosen.merge(spread, on=compare.SELECTION_KEY, how="left")
            chosen["sigma"] = combined_sigma(chosen.disagreement.fillna(0.0), err)
            chosen["model"] = model
            row.update(test_bets=len(chosen), mean_disagreement=round(float(chosen.disagreement.mean()), 4),
                       mean_sigma=round(float(chosen.sigma.mean()), 4),
                       mean_model_edge=round(float((chosen.probability - 1 / chosen.price).mean()), 4))
            bets.append(chosen)
        info.append(row)
    return (pd.concat(bets, ignore_index=True) if bets else pd.DataFrame()), pd.DataFrame(info)


def render(engine: Engine, today, generated_at: str) -> str:
    cfg = RiskConfig()
    bets, info = build_bets(engine, today)
    policy_rows, mc_rows, ledgers = [], [], {}
    for name, policy in simulation.POLICIES.items():
        ledger = simulation.replay(bets, policy, cfg)
        ledgers[name] = ledger
        s = simulation.summarize(ledger)
        s["limit_hits"] = ", ".join(f"{k} x{v}" for k, v in s["limit_hits"].items()) or "none"
        policy_rows.append({"policy": name, **s})
        if len(ledger):
            scenarios = {
                "market is right (closing fair probability)": ledger.closing_fair_prob.fillna(1 / ledger.price),
                "model is right": ledger.probability,
            }
            for scenario, p in scenarios.items():
                mc_rows.append({"policy": name, "scenario": scenario, **simulation.monte_carlo(ledger, p.to_numpy())})

    flat = ledgers["flat 0.25% of start"]
    conc = pd.DataFrame([{"by": by, **monitoring.concentration(flat, by)}
                         for by in ("league", "match_date", "market")]) if len(flat) else pd.DataFrame()
    evidence = monitoring.scaling_evidence(flat, cfg.min_bets_to_scale)
    review = ("Stakes may follow the bankroll upward." if evidence["allowed"] else
              "**Do not increase stakes.** " + "; ".join(evidence["reasons"]) + ".")
    return "\n\n".join([
        "# Phase 6 risk report",
        f"Generated {generated_at} UTC. Staking policies replayed on the test season's "
        "historical bets. This is a historical simulation, not paper-trading or live "
        "performance, and the prices were never verified as obtainable.",
        "## Bets and probability uncertainty",
        "Default model per market (Phase 5 gate). The EV threshold and `validation_model_error` "
        "(RMS gap between the model and the closing market's fair probability) are measured on "
        "the validation season. sigma = sqrt(disagreement^2 + model_error^2). "
        "`mean_model_edge` is the model's probability minus the price's implied probability: "
        "when sigma is as large as the edge, the edge is not distinguishable from model error.",
        _md(info),
        "## Risk settings",
        _md(pd.DataFrame([cfg.describe()])),
        "## Staking policies replayed on the same bets",
        "`not_staked` counts bets given a zero stake (edge inside the model's uncertainty, or "
        "betting halted by the drawdown rule). `expected_longest_streak` is what chance alone "
        "produces at that win rate.",
        _md(pd.DataFrame(policy_rows)),
        "## Monte Carlo: alternative histories of the same bets",
        "5,000 paths per row. Each bet keeps its price and stake share; only outcomes are "
        "redrawn. Final values are bankroll change in percent. Bets are drawn independently, "
        "so real tail risk is somewhat larger than shown.",
        _md(pd.DataFrame(mc_rows)) if mc_rows else "_No bets were staked._",
        "## Correlation between outcomes of the same match",
        "From every finished match stored. Bets on correlated outcomes of one match add less "
        "diversification than their count suggests, which is why exposure is capped per match.",
        _md(monitoring.outcome_correlation(engine).reset_index(names="outcome")),
        "## Stake concentration (flat-stake ledger)",
        _md(conc) if not conc.empty else "_No bets._",
        "## Stake review",
        f"Settled bets: {evidence['settled_bets']} (minimum {evidence['min_bets_required']}). "
        f"Mean CLV: {evidence['mean_clv_pct']}% (95% interval {evidence['clv_ci95_low']} to "
        f"{evidence['clv_ci95_high']}).",
        review,
    ]) + "\n"
