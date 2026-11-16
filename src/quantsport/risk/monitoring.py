"""Monitoring: drawdown, losing streaks, daily exposure, concentration,
outcome correlation, and the evidence test for raising stakes."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sqlalchemy import Engine

OUTCOME_SQL = "SELECT home_goals, away_goals FROM matches WHERE status = 'finished'"


def drawdowns(equity: np.ndarray) -> np.ndarray:
    """Fall from the running peak, as a fraction of the peak, at each point."""
    equity = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(equity)
    return (peak - equity) / np.where(peak > 0, peak, 1.0)


def losing_streaks(won) -> tuple[int, int]:
    """(longest losing streak, current losing streak) in chronological order."""
    longest = current = 0
    for w in won:
        current = 0 if w else current + 1
        longest = max(longest, current)
    return longest, current


def expected_longest_losing_streak(n_bets: int, win_rate: float) -> float:
    """Approximate expected longest run of losses in n independent bets:
    log(n * p) / log(1 / (1 - p)), p = win rate. A streak near this length is
    ordinary variance, not evidence that something has broken."""
    if n_bets <= 0 or not 0 < win_rate < 1:
        return float("nan")
    return max(0.0, math.log(n_bets * win_rate) / math.log(1.0 / (1.0 - win_rate)))


def daily_exposure(ledger: pd.DataFrame) -> pd.DataFrame:
    """Total staked per day and its share of the bankroll at the start of that day."""
    g = ledger.groupby("match_date", sort=True)
    out = pd.DataFrame({"bets": g.size(), "staked": g.stake.sum(), "bankroll_before": g.bankroll_before.first()})
    out["exposure_pct"] = 100 * out.staked / out.bankroll_before
    return out.reset_index()


def concentration(ledger: pd.DataFrame, by: str) -> dict:
    """Stake concentration across groups (league, day, ...).
    Herfindahl H = sum of squared stake shares; effective groups = 1 / H."""
    shares = ledger.groupby(by).stake.sum()
    shares = shares / shares.sum()
    h = float((shares**2).sum())
    return {"groups": int(len(shares)), "largest_share_pct": round(100 * float(shares.max()), 1),
            "largest": str(shares.idxmax()), "herfindahl": round(h, 4), "effective_groups": round(1 / h, 1)}


def outcome_correlation(engine: Engine) -> pd.DataFrame:
    """Correlation between outcome indicators of the same match, from every
    finished match stored. Two bets on one match are not independent: this
    matrix says how strongly they move together."""
    m = pd.read_sql(OUTCOME_SQL, engine)
    hg, ag = m.home_goals, m.away_goals
    ind = pd.DataFrame({
        "home_win": hg > ag, "draw": hg == ag, "away_win": hg < ag,
        "over_2.5": hg + ag > 2.5, "under_2.5": hg + ag < 2.5, "btts_yes": (hg > 0) & (ag > 0),
    }).astype(float)
    return ind.corr().round(3)


def scaling_evidence(ledger: pd.DataFrame, min_bets: int, n_boot: int = 5000, seed: int = 12345) -> dict:
    """May the stake base follow the bankroll upward? Only with enough settled
    bets AND closing line value that is positive beyond chance. Profit is
    deliberately not part of the test."""
    clv = ledger.clv.dropna().to_numpy() if len(ledger) else np.array([])
    out = {"settled_bets": int(len(ledger)), "bets_with_clv": int(len(clv)), "min_bets_required": min_bets,
           "mean_clv_pct": None, "clv_ci95_low": None, "clv_ci95_high": None, "allowed": False, "reasons": []}
    if len(ledger) < min_bets:
        out["reasons"].append(f"only {len(ledger)} settled bets; {min_bets} required")
    if len(clv) >= 30:
        rng = np.random.default_rng(seed)
        means = clv[rng.integers(0, len(clv), size=(n_boot, len(clv)))].mean(axis=1)
        lo, hi = np.percentile(means, [2.5, 97.5])
        out.update(mean_clv_pct=round(100 * clv.mean(), 2), clv_ci95_low=round(100 * lo, 2),
                   clv_ci95_high=round(100 * hi, 2))
        if lo <= 0:
            out["reasons"].append("closing line value is not positive beyond chance")
    else:
        out["reasons"].append("fewer than 30 bets with a closing price; CLV cannot be assessed")
    out["allowed"] = not out["reasons"]
    return out
