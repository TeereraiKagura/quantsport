"""Common model interface.

A model is fitted on a frame of finished matches (columns: match_date, home,
away, home_goals, away_goals) that the caller has already restricted to
matches played strictly before the prediction date. predict() returns None
when the model has too little information about either team: the system
reports "insufficient data" instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from quantsport.models.markets import Key, expected_goals, market_probabilities


@dataclass
class Forecast:
    exp_home: float | None  # None for models that do not model goals
    exp_away: float | None
    probs: dict[Key, float]

    @classmethod
    def from_matrix(cls, matrix: np.ndarray) -> "Forecast":
        eh, ea = expected_goals(matrix)
        return cls(eh, ea, market_probabilities(matrix))


class Model:
    name = "model"

    def __init__(self, min_matches: int = 5, **params):
        # min_matches: matches a team must have in the training data.
        self.params = {"min_matches": min_matches, **params}
        self._games: dict[str, int] = {}
        self.fitted = False

    def _count_games(self, train: pd.DataFrame) -> None:
        self._games = pd.concat([train.home, train.away]).value_counts().to_dict()

    def _enough(self, home: str, away: str) -> bool:
        need = self.params["min_matches"]
        return self.fitted and self._games.get(home, 0) >= need and self._games.get(away, 0) >= need

    def fit(self, train: pd.DataFrame, as_of: date) -> None:
        raise NotImplementedError

    def predict(self, home: str, away: str) -> Forecast | None:
        raise NotImplementedError


class BaseRate(Model):
    """Benchmark: every match gets the league's historical outcome frequencies.
    A model that cannot beat this has learned nothing about the teams."""

    name = "base_rate"

    def fit(self, train: pd.DataFrame, as_of: date) -> None:
        self._count_games(train)
        hg, ag = train.home_goals, train.away_goals
        over = float((hg + ag > 2.5).mean())
        btts = float(((hg > 0) & (ag > 0)).mean())
        h, d = float((hg > ag).mean()), float((hg == ag).mean())
        self._probs = {
            ("OU", 2.5, "over"): over, ("OU", 2.5, "under"): 1 - over,
            ("BTTS", 0.0, "yes"): btts, ("BTTS", 0.0, "no"): 1 - btts,
            ("1X2", 0.0, "H"): h, ("1X2", 0.0, "D"): d, ("1X2", 0.0, "A"): 1 - h - d,
        }
        self.fitted = len(train) > 0

    def predict(self, home: str, away: str) -> Forecast | None:
        return Forecast(None, None, dict(self._probs)) if self.fitted else None
