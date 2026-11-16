"""Dixon-Coles (1997) model.

Same mean structure as the Poisson regression, with two additions:

1. Low-score dependence. The independent-Poisson probability of each score
   (x, y) is multiplied by tau(x, y):
       tau(0,0) = 1 - lam*mu*rho     tau(0,1) = 1 + lam*rho
       tau(1,0) = 1 + mu*rho         tau(1,1) = 1 - rho
       tau = 1 otherwise
   where x = home goals, y = away goals.
2. Time decay. Each match's log-likelihood is weighted by exp(-xi * days),
   days = age of the match at the fitting date, so recent form counts more.

Parameters are estimated by weighted maximum likelihood.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

from quantsport.models.base import Forecast, Model
from quantsport.models.markets import MAX_GOALS


class DixonColes(Model):
    name = "dixon_coles"

    def __init__(self, xi: float = 0.002, **params):
        # xi is per day; 0.002 halves a match's weight after about 347 days.
        # It is a default, not a tuned value.
        super().__init__(xi=xi, **params)
        self._warm: dict[str, tuple[float, float]] = {}
        self._warm_globals = (0.3, 0.25, -0.05)

    def fit(self, train: pd.DataFrame, as_of: date) -> None:
        self.fitted = False
        self._count_games(train)
        teams = sorted(self._games)
        t = len(teams)
        if t < 2 or len(train) < t:
            return
        idx = {name: i for i, name in enumerate(teams)}
        hi = train.home.map(idx).to_numpy()
        ai = train.away.map(idx).to_numpy()
        hg = train.home_goals.to_numpy(dtype=float)
        ag = train.away_goals.to_numpy(dtype=float)
        age = np.array([(as_of - d).days for d in train.match_date], dtype=float)
        w = np.exp(-self.params["xi"] * age)
        m00, m01 = (hg == 0) & (ag == 0), (hg == 0) & (ag == 1)
        m10, m11 = (hg == 1) & (ag == 0), (hg == 1) & (ag == 1)

        def unpack(theta):
            att = theta[:t] - theta[:t].mean()
            dfn = theta[t:2 * t] - theta[t:2 * t].mean()
            return att, dfn, theta[2 * t], theta[2 * t + 1], theta[2 * t + 2]

        def nll(theta):
            att, dfn, const, home, rho = unpack(theta)
            loglam = const + home + att[hi] + dfn[ai]
            logmu = const + att[ai] + dfn[hi]
            lam, mu = np.exp(loglam), np.exp(logmu)
            tau = np.ones_like(lam)
            tau[m00] = 1 - lam[m00] * mu[m00] * rho
            tau[m01] = 1 + lam[m01] * rho
            tau[m10] = 1 + mu[m10] * rho
            tau[m11] = 1 - rho
            ll = np.log(np.maximum(tau, 1e-10)) + hg * loglam - lam + ag * logmu - mu
            return -(w * ll).sum()

        start = np.zeros(2 * t + 3)
        for name, i in idx.items():  # warm start from the previous fit
            start[i], start[t + i] = self._warm.get(name, (0.0, 0.0))
        start[2 * t:] = self._warm_globals
        bounds = [(-3, 3)] * (2 * t) + [(-3, 3), (-1, 2), (-0.3, 0.3)]
        res = minimize(nll, start, method="L-BFGS-B", bounds=bounds)
        if not np.all(np.isfinite(res.x)):
            return
        att, dfn, self.const, self.home_adv, self.rho = unpack(res.x)
        self.att, self.dfn = dict(zip(teams, att)), dict(zip(teams, dfn))
        self._warm = {name: (att[i], dfn[i]) for name, i in idx.items()}
        self._warm_globals = (self.const, self.home_adv, self.rho)
        self.converged = bool(res.success)
        self.fitted = True

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        lam = np.exp(self.const + self.home_adv + self.att[home] + self.dfn[away])
        mu = np.exp(self.const + self.att[away] + self.dfn[home])
        goals = np.arange(MAX_GOALS + 1)
        matrix = np.outer(poisson.pmf(goals, lam), poisson.pmf(goals, mu))
        rho = self.rho
        matrix[0, 0] *= max(1 - lam * mu * rho, 1e-10)
        matrix[0, 1] *= max(1 + lam * rho, 1e-10)
        matrix[1, 0] *= max(1 + mu * rho, 1e-10)
        matrix[1, 1] *= max(1 - rho, 1e-10)
        return matrix / matrix.sum()

    def predict(self, home: str, away: str) -> Forecast | None:
        if not self._enough(home, away):
            return None
        return Forecast.from_matrix(self.score_matrix(home, away))

    def strengths(self) -> pd.DataFrame:
        return pd.DataFrame({
            "attack": np.exp(pd.Series(self.att)),
            "defence_weakness": np.exp(pd.Series(self.dfn)),
            "matches": pd.Series(self._games),
        }).sort_values("attack", ascending=False)
