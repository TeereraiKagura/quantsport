"""Market probabilities derived from a single score matrix.

matrix[i, j] = P(home scores i, away scores j). Every goal-based market is a
sum over cells of the same matrix, so the markets are consistent by
construction: Over + Under = 1, Home + Draw + Away = 1, and Over 0.5 >= Over
1.5 >= Over 2.5 >= Over 3.5.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 15  # scores above this are truncated and the matrix renormalised
OU_LINES = (0.5, 1.5, 2.5, 3.5)

Key = tuple[str, float, str]  # (market, line, selection)


def independent_score_matrix(exp_home: float, exp_away: float) -> np.ndarray:
    goals = np.arange(MAX_GOALS + 1)
    matrix = np.outer(poisson.pmf(goals, exp_home), poisson.pmf(goals, exp_away))
    return matrix / matrix.sum()


def expected_goals(matrix: np.ndarray) -> tuple[float, float]:
    goals = np.arange(matrix.shape[0])
    return float(matrix.sum(axis=1) @ goals), float(matrix.sum(axis=0) @ goals)


def market_probabilities(matrix: np.ndarray) -> dict[Key, float]:
    n = matrix.shape[0]
    home, away = np.indices((n, n))
    total = home + away
    probs: dict[Key, float] = {}
    for line in OU_LINES:
        over = float(matrix[total > line].sum())
        probs[("OU", line, "over")] = over
        probs[("OU", line, "under")] = 1.0 - over
    yes = float(matrix[1:, 1:].sum())
    probs[("BTTS", 0.0, "yes")] = yes
    probs[("BTTS", 0.0, "no")] = 1.0 - yes
    h = float(matrix[home > away].sum())
    d = float(np.trace(matrix))
    probs[("1X2", 0.0, "H")] = h
    probs[("1X2", 0.0, "D")] = d
    probs[("1X2", 0.0, "A")] = 1.0 - h - d
    return probs
