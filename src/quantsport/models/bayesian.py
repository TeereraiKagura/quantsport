"""Bayesian team strengths with venue-specific attack and defence.

Four strengths per team, each a multiplier where 1.0 is league average:
    HA home attack      HD home defensive weakness (goals conceded at home)
    AA away attack      AD away defensive weakness (goals conceded away)

    home goals ~ Poisson(mH * HA[home] * AD[away])
    away goals ~ Poisson(mA * AA[away] * HD[home])

mH, mA are the league's average home and away goals per match in the training
data. Every strength has a Gamma(k, k) prior (mean 1). With the opponents'
strengths held at their current posterior means, the Gamma prior is conjugate:

    HA[i] | data ~ Gamma(k + goals scored at home,
                         k + sum over those matches of mH * AD[opponent])

and likewise for the other three. The updates are iterated to a fixed point.
This is a coordinate-wise (mean-field style) approximation, not full joint
posterior sampling. The prior shrinks teams with few matches toward 1.0, and
the posterior standard deviation sqrt(shape)/rate quantifies how uncertain
each strength still is. Predictions plug in posterior means.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quantsport.models.base import Forecast, Model
from quantsport.models.markets import independent_score_matrix

KINDS = ("home_attack", "home_defence", "away_attack", "away_defence")


class BayesianStrengths(Model):
    name = "bayesian"

    def __init__(self, prior_strength: float = 8.0, **params):
        # prior_strength k: the prior weighs as much as k expected goals of
        # evidence (roughly six matches). A default, not a tuned value.
        super().__init__(prior_strength=prior_strength, **params)

    def fit(self, train: pd.DataFrame, as_of: date) -> None:
        self.fitted = False
        self._count_games(train)
        teams = sorted(self._games)
        t = len(teams)
        if t < 2 or len(train) == 0:
            return
        idx = {name: i for i, name in enumerate(teams)}
        hi = train.home.map(idx).to_numpy()
        ai = train.away.map(idx).to_numpy()
        hg = train.home_goals.to_numpy(dtype=float)
        ag = train.away_goals.to_numpy(dtype=float)
        self.mean_home, self.mean_away = float(hg.mean()), float(ag.mean())
        if self.mean_home <= 0 or self.mean_away <= 0:
            return
        k = self.params["prior_strength"]

        def total(index, values):
            return np.bincount(index, weights=values, minlength=t)

        shape = {
            "home_attack": k + total(hi, hg), "away_defence": k + total(ai, hg),
            "away_attack": k + total(ai, ag), "home_defence": k + total(hi, ag),
        }
        mean = {kind: np.ones(t) for kind in KINDS}
        rate = {kind: np.full(t, k) for kind in KINDS}
        for _ in range(200):
            previous = np.concatenate([mean[kind] for kind in KINDS])
            rate["home_attack"] = k + total(hi, self.mean_home * mean["away_defence"][ai])
            mean["home_attack"] = shape["home_attack"] / rate["home_attack"]
            rate["away_defence"] = k + total(ai, self.mean_home * mean["home_attack"][hi])
            mean["away_defence"] = shape["away_defence"] / rate["away_defence"]
            rate["away_attack"] = k + total(ai, self.mean_away * mean["home_defence"][hi])
            mean["away_attack"] = shape["away_attack"] / rate["away_attack"]
            rate["home_defence"] = k + total(hi, self.mean_away * mean["away_attack"][ai])
            mean["home_defence"] = shape["home_defence"] / rate["home_defence"]
            if np.abs(np.concatenate([mean[kind] for kind in KINDS]) - previous).max() < 1e-9:
                break
        self._idx = idx
        self._mean = mean
        self._sd = {kind: np.sqrt(shape[kind]) / rate[kind] for kind in KINDS}
        self.fitted = True

    def expected(self, home: str, away: str) -> tuple[float, float]:
        i, j = self._idx[home], self._idx[away]
        lam = self.mean_home * self._mean["home_attack"][i] * self._mean["away_defence"][j]
        mu = self.mean_away * self._mean["away_attack"][j] * self._mean["home_defence"][i]
        return float(lam), float(mu)

    def predict(self, home: str, away: str) -> Forecast | None:
        if not self._enough(home, away):
            return None
        return Forecast.from_matrix(independent_score_matrix(*self.expected(home, away)))

    def strengths(self) -> pd.DataFrame:
        teams = list(self._idx)
        data = {"matches": [self._games[name] for name in teams]}
        for kind in KINDS:
            data[kind] = self._mean[kind]
            data[f"{kind}_sd"] = self._sd[kind]
        return pd.DataFrame(data, index=teams).sort_values("home_attack", ascending=False)
