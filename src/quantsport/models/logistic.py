"""Logistic regression fitted directly on market outcomes.

Unlike the goal models it does not produce a score distribution, so it only
covers the three markets it is trained on: Over/Under 2.5 (binary), Both Teams
to Score (binary) and 1X2 (multinomial).

Features, for each side, are the mean goals scored and conceded over that
team's previous `window` matches. For a match on date d they are computed only
from matches played before d, both when training and when predicting.
"""

from __future__ import annotations

import warnings
from collections import defaultdict, deque
from datetime import date

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from quantsport.models.base import Forecast, Model

MIN_TRAINING_ROWS = 100


class LogisticMarkets(Model):
    name = "logistic"

    def __init__(self, window: int = 10, **params):
        super().__init__(window=window, **params)

    def _features(self, home: str, away: str) -> list[float] | None:
        need = self.params["min_matches"]
        h, a = self._history[home], self._history[away]
        if len(h) < need or len(a) < need:
            return None
        hf, ha = np.mean(h, axis=0)
        af, aa = np.mean(a, axis=0)
        return [hf, ha, af, aa]

    def fit(self, train: pd.DataFrame, as_of: date) -> None:
        self.fitted = False
        self._count_games(train)
        self._history = defaultdict(lambda: deque(maxlen=self.params["window"]))
        rows, over, btts, result = [], [], [], []
        for _, day in train.sort_values("match_date").groupby("match_date", sort=True):
            records = list(day.itertuples(index=False))
            for r in records:  # features first: nothing from the same day leaks in
                x = self._features(r.home, r.away)
                if x is not None:
                    rows.append(x)
                    over.append(int(r.home_goals + r.away_goals > 2.5))
                    btts.append(int(r.home_goals > 0 and r.away_goals > 0))
                    result.append("H" if r.home_goals > r.away_goals else "A" if r.away_goals > r.home_goals else "D")
            for r in records:
                self._history[r.home].append((r.home_goals, r.away_goals))
                self._history[r.away].append((r.away_goals, r.home_goals))
        if len(rows) < MIN_TRAINING_ROWS or min(len(set(v)) for v in (over, btts)) < 2 or len(set(result)) < 3:
            return
        x = np.array(rows)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._over = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(x, over)
            self._btts = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(x, btts)
            self._result = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(x, result)
        self.n_training_rows = len(rows)
        self.fitted = True

    def predict(self, home: str, away: str) -> Forecast | None:
        if not self.fitted:
            return None
        x = self._features(home, away)
        if x is None:
            return None
        x = np.array([x])
        over = float(self._over.predict_proba(x)[0, 1])
        btts = float(self._btts.predict_proba(x)[0, 1])
        result = dict(zip(self._result.classes_, self._result.predict_proba(x)[0]))
        return Forecast(None, None, {
            ("OU", 2.5, "over"): over, ("OU", 2.5, "under"): 1 - over,
            ("BTTS", 0.0, "yes"): btts, ("BTTS", 0.0, "no"): 1 - btts,
            ("1X2", 0.0, "H"): float(result["H"]), ("1X2", 0.0, "D"): float(result["D"]),
            ("1X2", 0.0, "A"): float(result["A"]),
        })
