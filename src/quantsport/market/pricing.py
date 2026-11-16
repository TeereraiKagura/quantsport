"""Pricing mathematics. Pure functions on decimal odds; no database access.

Definitions (o = decimal odds, p = model probability):

    implied probability   q = 1 / o
    booksum               B = sum of q over all outcomes of a market
    overround (margin)    B - 1
    fair probability      the bookmaker's implied probability with the margin
                          removed, by one of:
                            proportional: f_i = q_i / B
                            power:        f_i = q_i ** k, with k solving sum(f) = 1
    expected value        EV = p * o - 1        (profit per unit staked)
    edge                  p - f                 (model minus market, in probability)
    closing line value    CLV = o_taken * f_close - 1
                          the EV of the price taken, judged by the closing
                          market's fair probability instead of the model's
    price CLV             o_taken / o_close - 1 (same bookmaker's closing price)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import brentq


def implied_probability(odds: float) -> float:
    if not odds > 1.0:
        raise ValueError(f"Decimal odds must exceed 1.0, got {odds}")
    return 1.0 / odds


def booksum(odds: list[float]) -> float:
    return sum(implied_probability(o) for o in odds)


def overround(odds: list[float]) -> float:
    return booksum(odds) - 1.0


def fair_probabilities(odds: list[float], method: str = "proportional") -> list[float]:
    """Margin-free probabilities for a complete set of outcomes."""
    q = np.array([implied_probability(o) for o in odds])
    if method == "proportional":
        return list(q / q.sum())
    if method == "power":
        if abs(q.sum() - 1.0) < 1e-12:
            return list(q)
        k = brentq(lambda k: (q**k).sum() - 1.0, 0.01, 100.0)
        return list(q**k)
    raise ValueError(f"Unknown method '{method}'")


def expected_value(probability: float, odds: float) -> float:
    return probability * odds - 1.0


def edge(probability: float, fair_probability: float) -> float:
    return probability - fair_probability


def closing_line_value(odds_taken: float, closing_fair_probability: float) -> float:
    return odds_taken * closing_fair_probability - 1.0


def price_clv(odds_taken: float, closing_odds: float) -> float:
    return odds_taken / closing_odds - 1.0


def executability(
    is_aggregate: bool,
    match_status: str,
    observed_at: datetime | None,
    now: datetime,
    max_age: timedelta = timedelta(minutes=15),
) -> str:
    """How far a quoted price can be treated as something one could bet.

    aggregate  - a market max/average: not a price at any one bookmaker.
    historical - the match is no longer upcoming; the price is gone.
    indicative - pre-match, but with no collection time or a stale one. The
                 price may have moved; expected value on it is theoretical.
    current    - pre-match and observed within `max_age`.

    Only "current" may be described as an executable opportunity, and even
    then stake limits and account restrictions are not modelled.
    """
    if is_aggregate:
        return "aggregate"
    if match_status != "scheduled":
        return "historical"
    if observed_at is None or now - observed_at > max_age:
        return "indicative"
    return "current"
