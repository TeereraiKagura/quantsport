"""Backtest protocol and report.

The protocol keeps the final test season untouched until the end:

1. Validation (previous season). For each model and market, run a small,
   fixed grid of EV thresholds. Choose the threshold with the highest
   validation ROI among those with at least MIN_VALIDATION_BETS bets.
2. Test (current season). Run each model once with its chosen threshold.
   Nothing is tuned on these results.
3. Sensitivity runs on the test season are shown for information only and are
   labelled as such; they must not be used to pick a configuration.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
from sqlalchemy import Engine

from quantsport.backtest.engine import BacktestConfig, load_data, run
from quantsport.models.report import _md

MODELS = ["dixon_coles", "poisson", "bayesian", "logistic", "ml_logistic", "ml_random_forest",
          "ml_gradient_boosting", "ml_xgboost", "ensemble", "base_rate"]
MARKETS = [("OU", 2.5), ("1X2", 0.0)]
EV_GRID = [0.0, 0.05, 0.10, 0.15]
MIN_VALIDATION_BETS = 50
# Flat stake for the protocol, as a share of the starting bankroll. Small
# enough that no strategy runs out of money part-way through a season, which
# would cut its bet count short and make ROI depend on the order of results.
BASE_STAKE_PCT = 0.0025
SUMMARY_COLS = ["bets", "skipped_after_ruin", "wins", "losses", "staked", "profit", "roi_pct", "roi_ci95_low", "roi_ci95_high",
                "win_rate_pct", "mean_odds", "mean_clv_pct", "max_drawdown_pct", "verdict"]


def _label(market: str, line: float) -> str:
    return f"OU {line}" if market == "OU" else market


def build(engine: Engine, today) -> dict[str, pd.DataFrame]:
    data = load_data(engine)
    grid_rows, test_rows, sens_rows, cover_rows = [], [], [], []
    for market, line in MARKETS:
        for model in MODELS:
            base = BacktestConfig(model=model, market=market, line=line, stake_pct=BASE_STAKE_PCT)
            best = None
            for min_ev in EV_GRID:
                s, _, cov = run(engine, replace(base, seasons_ago=1, min_ev=min_ev), today, data)
                grid_rows.append({"market": _label(market, line), "model": model, "min_ev": min_ev,
                                  **{k: s[k] for k in ("bets", "skipped_after_ruin", "roi_pct", "roi_ci95_low",
                                                       "roi_ci95_high", "mean_clv_pct", "verdict")}})
                if s["bets"] >= MIN_VALIDATION_BETS and (best is None or s["roi_pct"] > best[1]):
                    best = (min_ev, s["roi_pct"])
            if model == MODELS[0]:
                cover_rows.append({"market": _label(market, line), "split": "validation (previous season)", **cov})
            if best is None:
                test_rows.append({"market": _label(market, line), "model": model, "chosen_min_ev": None,
                                  "bets": 0, "verdict": "no threshold had enough validation bets"})
                continue
            chosen = replace(base, min_ev=best[0])
            s, _, cov = run(engine, chosen, today, data)
            test_rows.append({"market": _label(market, line), "model": model, "chosen_min_ev": best[0],
                              "validation_roi_pct": best[1], **{k: s[k] for k in SUMMARY_COLS}})
            if model == MODELS[0]:
                cover_rows.append({"market": _label(market, line), "split": "test (current season)", **cov})
            variants = {
                "best price across bookmakers": replace(chosen, price_source="best"),
                "flat 1% of starting bankroll": replace(chosen, stake_pct=0.01),
                "1% of current bankroll": replace(chosen, staking="percent", stake_pct=0.01),
                "quarter Kelly, 5% cap": replace(chosen, staking="kelly"),
                "bet every match (no EV filter)": replace(chosen, min_ev=-1.0),
            }
            for name, cfg in variants.items():
                s, _, _ = run(engine, cfg, today, data)
                sens_rows.append({"market": _label(market, line), "model": model, "variant": name,
                                  **{k: s[k] for k in ("bets", "skipped_after_ruin", "roi_pct", "roi_ci95_low",
                                                       "roi_ci95_high", "max_drawdown_pct", "final_bankroll",
                                                       "verdict")}})
    return {"coverage": pd.DataFrame(cover_rows), "grid": pd.DataFrame(grid_rows),
            "test": pd.DataFrame(test_rows), "sensitivity": pd.DataFrame(sens_rows)}


def render(tables: dict[str, pd.DataFrame], generated_at: str) -> str:
    default = BacktestConfig(stake_pct=BASE_STAKE_PCT)
    return "\n\n".join([
        "# Phase 4 backtest report",
        f"Generated {generated_at} UTC. Historical simulation on stored walk-forward forecasts "
        "and historical pre-closing prices. This is a backtest, not live or paper-trading "
        "performance. Prices carry no collection time, so whether each bet could really have "
        "been placed at the recorded price is not verified; stake limits and account "
        "restrictions are not modelled.",
        f"Base settings: prices from {default.price_source} (pre-closing), flat stakes of "
        f"{default.stake_pct:.2%} of a {default.initial_bankroll:.0f}-unit starting bankroll, "
        f"commission {default.commission:.0%}, one bet per match and market. ROI = profit / "
        "total staked. Intervals are 95% bootstraps resampling whole matches. "
        "`skipped_after_ruin` counts qualifying bets that could not be placed because the "
        "bankroll had already reached zero; when it is above 0, ROI covers only the bets "
        "placed before ruin.",
        "## Coverage",
        "Matches without a forecast (too little history for a team, or too early in the "
        "season) or without a price are not bet. Switzerland and Norway have no pre-closing "
        "prices and therefore contribute no bets.",
        _md(tables["coverage"]),
        "## Step 1: validation season, threshold grid",
        f"The threshold with the highest ROI among those with at least {MIN_VALIDATION_BETS} "
        "bets is carried to the test. With samples this small that choice is itself noisy. "
        "Each verdict is judged alone: with this many grid cells, a few will look "
        "\"profitable beyond chance\" by luck, which is exactly why only the test season counts.",
        _md(tables["grid"]),
        "## Step 2: test season, each model run once with its validation-chosen threshold",
        _md(tables["test"]),
        "## Sensitivity on the test season (information only, not for choosing settings)",
        _md(tables["sensitivity"]) if not tables["sensitivity"].empty else "_None._",
    ]) + "\n"
