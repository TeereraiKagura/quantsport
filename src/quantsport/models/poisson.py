"""Independent Poisson regression (Maher-style), fitted as a GLM.

    home goals ~ Poisson(exp(c + h + att[home] + dfn[away]))
    away goals ~ Poisson(exp(c +     att[away] + dfn[home]))

att = attacking strength, dfn = defensive weakness (higher concedes more),
h = home advantage. Home and away goals are treated as independent.
"""

from __future__ import annotations

import warnings
from datetime import date

import numpy as np
import pandas as pd
import statsmodels.api as sm

from quantsport.models.base import Forecast, Model
from quantsport.models.markets import independent_score_matrix


class PoissonRegression(Model):
    name = "poisson"

    def __init__(self, ridge: float = 0.001, **params):
        # ridge: penalty per observation on squared team effects. A fixed
        # small default chosen for numerical stability, not tuned.
        super().__init__(ridge=ridge, **params)

    def fit(self, train: pd.DataFrame, as_of: date) -> None:
        self.fitted = False
        self._count_games(train)
        teams = sorted(self._games)
        t, n = len(teams), len(train)
        if t < 2 or n < t:
            return
        idx = {name: i for i, name in enumerate(teams)}
        hi = train.home.map(idx).to_numpy()
        ai = train.away.map(idx).to_numpy()
        rows = np.arange(n)
        # Columns: const, home flag, attack dummies, defence dummies.
        x = np.zeros((2 * n, 2 + 2 * t))
        x[:, 0] = 1.0
        x[:n, 1] = 1.0
        x[rows, 2 + hi] = 1.0          # home side attacking
        x[rows, 2 + t + ai] = 1.0      # away side defending
        x[n + rows, 2 + ai] = 1.0      # away side attacking
        x[n + rows, 2 + t + hi] = 1.0  # home side defending
        y = np.concatenate([train.home_goals.to_numpy(), train.away_goals.to_numpy()])
        # A small ridge penalty on the team effects (not on the constant or
        # home advantage). Without it the likelihood has no finite maximum
        # when a team has, say, one match and no goals, and the whole fit
        # diverges. The penalty also identifies the full set of team dummies
        # and pulls thinly observed teams toward the league average.
        alpha = np.r_[0.0, 0.0, np.full(2 * t, self.params["ridge"])]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = sm.GLM(y, x, family=sm.families.Poisson()).fit_regularized(alpha=alpha, L1_wt=0.0)
        except Exception:
            return
        beta = np.asarray(res.params)
        if not np.all(np.isfinite(beta)) or np.abs(beta).max() > 5:
            return  # diverged: report "insufficient data" instead of nonsense
        self.const, self.home_adv = float(beta[0]), float(beta[1])
        self.att = dict(zip(teams, beta[2:2 + t]))
        self.dfn = dict(zip(teams, beta[2 + t:]))
        self.fitted = True

    def expected(self, home: str, away: str) -> tuple[float, float]:
        lam = np.exp(self.const + self.home_adv + self.att[home] + self.dfn[away])
        mu = np.exp(self.const + self.att[away] + self.dfn[home])
        return float(lam), float(mu)

    def predict(self, home: str, away: str) -> Forecast | None:
        if not self._enough(home, away):
            return None
        return Forecast.from_matrix(independent_score_matrix(*self.expected(home, away)))

    def strengths(self) -> pd.DataFrame:
        """Multipliers relative to the average team (1.0 = league average)."""
        att = pd.Series(self.att)
        dfn = pd.Series(self.dfn)
        return pd.DataFrame({
            "attack": np.exp(att - att.mean()),
            "defence_weakness": np.exp(dfn - dfn.mean()),
            "matches": pd.Series(self._games),
        }).sort_values("attack", ascending=False)
