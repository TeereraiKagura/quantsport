"""Historical replay of staking policies and Monte Carlo bankroll simulation."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from quantsport.risk import monitoring
from quantsport.risk.staking import (
    RiskConfig, apply_limits, drawdown_multiplier, kelly_fraction, propose, stake_base,
)

# Policies compared in the report. "limits" switches on exposure limits,
# drawdown control and the no-scaling-on-profit stake base.
POLICIES = {
    "flat 0.25% of start": {"kind": "flat", "pct": 0.0025, "limits": False},
    "1% of current bankroll": {"kind": "percent", "pct": 0.01, "limits": False},
    "naive quarter Kelly, 5% cap": {"kind": "naive_kelly", "limits": False},
    "risk engine: uncertainty-adjusted quarter Kelly + limits": {"kind": "risk", "limits": True},
    "risk engine: 1% fixed + limits": {"kind": "risk_percent", "limits": True},
}


def replay(bets: pd.DataFrame, policy: dict, cfg: RiskConfig, initial: float = 1000.0) -> pd.DataFrame:
    """Stake and settle historical bets day by day under one policy.

    bets: match_id, match_date, probability, price, sigma, won, closing_fair_prob
    (one row per bet, any number per match). Returns the ledger of placed bets
    with stake > 0, plus attrs: skipped_zero_stake, limit_hits, halted_days.
    """
    bankroll = peak = initial
    rows, zero, hits, halted = [], 0, {}, 0
    settled = pd.DataFrame()
    for _, day in bets.sort_values(["match_date", "match_id"]).groupby("match_date", sort=True):
        if bankroll <= 0:
            break
        kind = policy["kind"]
        if kind == "flat":
            stakes = np.full(len(day), policy["pct"] * initial)
        elif kind == "percent":
            stakes = np.full(len(day), policy["pct"] * bankroll)
        elif kind == "naive_kelly":
            stakes = np.minimum(0.25 * kelly_fraction(day.probability, day.price), 0.05) * bankroll
        else:
            evidence = monitoring.scaling_evidence(settled, cfg.min_bets_to_scale, n_boot=500)["allowed"]
            base = stake_base(bankroll, initial, evidence)
            use = cfg if kind == "risk" else replace(cfg, staking="percent")
            stakes = propose(day, base, use) * drawdown_multiplier(bankroll, peak, cfg)
            if stakes.sum() == 0 and drawdown_multiplier(bankroll, peak, cfg) == 0:
                halted += 1
        if policy["limits"]:
            # Caps are taken on the stake base, so they too cannot grow on profit alone.
            stakes, hit = apply_limits(day, stakes, base, cfg)
            for h in hit:
                hits[h] = hits.get(h, 0) + 1
        if stakes.sum() > bankroll:
            stakes = stakes * bankroll / stakes.sum()
        placed = stakes > 1e-9
        zero += int((~placed).sum())
        if not placed.any():
            continue
        d = day[placed].assign(stake=stakes[placed])
        d["profit"] = np.where(d.won, d.stake * (d.price - 1.0), -d.stake)
        d["bankroll_before"] = bankroll
        bankroll += d.profit.sum()
        peak = max(peak, bankroll)
        d["bankroll_after"] = bankroll
        d["clv"] = d.price * d.closing_fair_prob - 1.0
        rows.append(d)
        settled = pd.concat(rows, ignore_index=True)
    ledger = settled if len(rows) else bets.iloc[0:0].assign(
        stake=[], profit=[], bankroll_before=[], bankroll_after=[], clv=[])
    ledger.attrs.update(skipped_zero_stake=zero, limit_hits=hits, halted_days=halted, initial=initial)
    return ledger


def summarize(ledger: pd.DataFrame) -> dict:
    initial = ledger.attrs.get("initial", 1000.0)
    n = len(ledger)
    out = {"bets_placed": n, "not_staked": ledger.attrs.get("skipped_zero_stake", 0), "staked": 0.0,
           "profit": 0.0, "roi_pct": None, "final_bankroll": initial, "max_drawdown_pct": 0.0,
           "longest_losing_streak": 0, "expected_longest_streak": None, "max_daily_exposure_pct": None,
           "limit_hits": ledger.attrs.get("limit_hits", {}), "halted_days": ledger.attrs.get("halted_days", 0)}
    if n == 0:
        return out
    equity = np.r_[initial, ledger.groupby("match_date", sort=True).bankroll_after.last().to_numpy()]
    longest, _ = monitoring.losing_streaks(ledger.won)
    out.update(
        staked=round(ledger.stake.sum(), 2), profit=round(ledger.profit.sum(), 2),
        roi_pct=round(100 * ledger.profit.sum() / ledger.stake.sum(), 2),
        final_bankroll=round(equity[-1], 2),
        max_drawdown_pct=round(100 * monitoring.drawdowns(equity).max(), 2),
        longest_losing_streak=longest,
        expected_longest_streak=round(monitoring.expected_longest_losing_streak(n, ledger.won.mean()), 1),
        max_daily_exposure_pct=round(monitoring.daily_exposure(ledger).exposure_pct.max(), 2),
    )
    return out


def monte_carlo(ledger: pd.DataFrame, win_prob: np.ndarray, n_paths: int = 5000, seed: int = 12345,
                ruin_level: float = 0.5) -> dict:
    """Simulate alternative histories of the same bets.

    Each bet keeps its price and the share of bankroll it was actually staked
    at (stake / bankroll at the start of its day). Outcomes are redrawn
    independently with the given win probabilities, and the bankroll compounds
    day by day. Independence between bets is an assumption: bets on the same
    match or day are in truth correlated, so real tails are fatter than these.
    """
    if len(ledger) == 0:
        return {}
    # One ordering for every per-bet array, so each probability stays with its
    # own bet's price and stake.
    order = np.argsort(ledger.match_date.to_numpy(), kind="stable")
    frac = (ledger.stake / ledger.bankroll_before).to_numpy()[order]
    price = ledger.price.to_numpy()[order]
    p = np.clip(np.asarray(win_prob, dtype=float), 0.0, 1.0)[order]
    days = ledger.match_date.to_numpy()[order]
    starts = np.r_[0, np.flatnonzero(days[1:] != days[:-1]) + 1]
    rng = np.random.default_rng(seed)
    wins = rng.random((n_paths, len(p))) < p[None, :]
    returns = np.where(wins, frac * (price - 1.0), -frac)
    daily = np.add.reduceat(returns, starts, axis=1)
    equity = np.cumprod(1.0 + daily, axis=1)
    equity = np.concatenate([np.ones((n_paths, 1)), equity], axis=1)
    peak = np.maximum.accumulate(equity, axis=1)
    max_dd = ((peak - equity) / peak).max(axis=1)
    final = equity[:, -1]
    return {
        "paths": n_paths,
        "median_final_pct": round(100 * (np.median(final) - 1), 2),
        "p5_final_pct": round(100 * (np.percentile(final, 5) - 1), 2),
        "p95_final_pct": round(100 * (np.percentile(final, 95) - 1), 2),
        "prob_loss_pct": round(100 * (final < 1).mean(), 1),
        "mean_max_drawdown_pct": round(100 * max_dd.mean(), 2),
        "prob_drawdown_over_20pct": round(100 * (max_dd >= 0.20).mean(), 1),
        f"prob_losing_{int(ruin_level * 100)}pct_of_bankroll": round(100 * (equity.min(axis=1) <= 1 - ruin_level).mean(), 1),
    }
