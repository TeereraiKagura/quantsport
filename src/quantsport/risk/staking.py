"""Stake sizing with probability uncertainty, exposure limits and drawdown control.

Definitions (p = model probability, o = decimal odds, B = bankroll):

    full Kelly fraction     k(p, o) = max(0, (p*o - 1) / (o - 1))
    probability uncertainty sigma = sqrt(disagreement^2 + model_error^2)
        disagreement = standard deviation of the probability across models
        model_error  = RMS gap between this model and the closing market's fair
                       probability, measured on the validation season
    conservative probability p_c = p - z * sigma
    uncertainty-adjusted stake  = kelly_fraction * k(p_c, o) * stake base

A bet whose conservative probability no longer has positive expected value
gets a stake of zero: the edge is inside the model's own error.

Stake base. Stakes are sized on min(current bankroll, starting bankroll). A
losing run shrinks stakes immediately; a winning run does not raise them. The
base may follow the bankroll upward only after `min_bets_to_scale` settled
bets whose mean closing line value is positive with a 95% interval above zero.
Short-term profit alone never increases stakes.

Limits, applied in this order, each as a share of the current bankroll:
    max_stake_pct   per bet
    max_match_pct   all bets on one match
    max_daily_pct   all bets on one day
    max_open_pct    all unsettled bets (paper trading)

Drawdown control: at `drawdown_reduce_pct` below the bankroll's peak stakes
are halved; at `drawdown_halt_pct` no new bets are placed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RiskConfig:
    staking: str = "kelly"  # "kelly" (uncertainty-adjusted) or "percent"
    kelly_fraction: float = 0.25
    z: float = 1.0
    stake_pct: float = 0.01  # for "percent"
    max_stake_pct: float = 0.02
    max_match_pct: float = 0.03
    max_daily_pct: float = 0.10
    max_open_pct: float = 0.25
    drawdown_reduce_pct: float = 0.10
    drawdown_halt_pct: float = 0.25
    min_bets_to_scale: int = 500

    def describe(self) -> dict:
        return asdict(self)


def kelly_fraction(p, odds):
    """Full Kelly fraction of bankroll; zero when the bet has no positive EV."""
    p, odds = np.asarray(p, dtype=float), np.asarray(odds, dtype=float)
    return np.maximum(0.0, (p * odds - 1.0) / (odds - 1.0))


def combined_sigma(disagreement, model_error):
    return np.sqrt(np.asarray(disagreement, dtype=float) ** 2 + float(model_error) ** 2)


def conservative_probability(p, sigma, z: float):
    return np.clip(np.asarray(p, dtype=float) - z * np.asarray(sigma, dtype=float), 0.0, 1.0)


def stake_base(current: float, initial: float, evidence_ok: bool) -> float:
    return current if evidence_ok else min(current, initial)


def drawdown_multiplier(current: float, peak: float, cfg: RiskConfig) -> float:
    drawdown = 0.0 if peak <= 0 else (peak - current) / peak
    if drawdown >= cfg.drawdown_halt_pct:
        return 0.0
    return 0.5 if drawdown >= cfg.drawdown_reduce_pct else 1.0


def propose(day: pd.DataFrame, base: float, cfg: RiskConfig) -> np.ndarray:
    """Unconstrained stakes for one day's bets (columns: probability, price, sigma)."""
    if cfg.staking == "percent":
        return np.full(len(day), cfg.stake_pct * base)
    p_c = conservative_probability(day.probability, day.sigma, cfg.z)
    return cfg.kelly_fraction * kelly_fraction(p_c, day.price) * base


def apply_limits(day: pd.DataFrame, stakes: np.ndarray, bankroll: float, cfg: RiskConfig,
                 open_exposure: float = 0.0) -> tuple[np.ndarray, list[str]]:
    """Scale stakes down to respect every limit. Returns (stakes, limits hit)."""
    stakes = np.asarray(stakes, dtype=float).copy()
    hit: list[str] = []
    cap = cfg.max_stake_pct * bankroll
    if (stakes > cap + 1e-12).any():
        hit.append("per-bet")
        stakes = np.minimum(stakes, cap)
    match_cap = cfg.max_match_pct * bankroll
    totals = pd.Series(stakes).groupby(day.match_id.to_numpy()).transform("sum").to_numpy()
    over = totals > match_cap + 1e-12
    if over.any():
        hit.append("per-match")
        stakes = np.where(over, stakes * match_cap / np.where(totals > 0, totals, 1.0), stakes)
    daily_cap = cfg.max_daily_pct * bankroll
    if stakes.sum() > daily_cap + 1e-12:
        hit.append("daily")
        stakes = stakes * daily_cap / stakes.sum()
    room = max(0.0, cfg.max_open_pct * bankroll - open_exposure)
    if stakes.sum() > room + 1e-12:
        hit.append("open-exposure")
        stakes = stakes * (room / stakes.sum()) if stakes.sum() > 0 else stakes
    return stakes, hit
