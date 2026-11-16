"""Estimators, hyperparameter grids, chronological splitting and calibration."""

from __future__ import annotations

import warnings
from itertools import product

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

# Small fixed grids. With about a thousand tuning rows a wide search would
# mostly fit noise.
GRIDS: dict[str, dict[str, list]] = {
    "ml_logistic": {"C": [0.01, 0.1, 1.0]},
    "ml_random_forest": {"max_depth": [3, 5], "min_samples_leaf": [10, 30]},
    "ml_gradient_boosting": {"learning_rate": [0.03, 0.1], "max_depth": [2, 3]},
    "ml_xgboost": {"learning_rate": [0.03, 0.1], "max_depth": [2, 3]},
}
MODEL_NAMES = list(GRIDS)


def grid(name: str) -> list[dict]:
    keys = list(GRIDS[name])
    return [dict(zip(keys, values)) for values in product(*(GRIDS[name][k] for k in keys))]


def make(name: str, params: dict):
    if name == "ml_logistic":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             LogisticRegression(C=params["C"], max_iter=2000))
    if name == "ml_random_forest":
        return RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1, **params)
    if name == "ml_gradient_boosting":
        return HistGradientBoostingClassifier(max_iter=150, early_stopping=False, random_state=0, **params)
    if name == "ml_xgboost":
        return XGBClassifier(n_estimators=200, subsample=0.8, colsample_bytree=0.8, random_state=0,
                             n_jobs=4, verbosity=0, **params)
    raise ValueError(f"Unknown model '{name}'")


def log_loss(proba: np.ndarray, y: np.ndarray) -> float:
    return float(-np.log(np.clip(proba[np.arange(len(y)), y], 1e-12, 1)).mean())


def rolling_splits(dates: np.ndarray, n_splits: int = 3, first_train_share: float = 0.4):
    """Expanding-window splits cut at date boundaries: every validation fold
    lies strictly after its training data in time. Yields (train_idx, val_idx)."""
    unique = np.sort(np.unique(dates))
    cum = np.searchsorted(np.sort(dates), unique, side="right") / len(dates)
    edges = np.linspace(first_train_share, 1.0, n_splits + 1)
    cut_dates = [unique[min(np.searchsorted(cum, e), len(unique) - 1)] for e in edges]
    for start, end in zip(cut_dates[:-1], cut_dates[1:]):
        train = np.where(dates <= start)[0]
        val = np.where((dates > start) & (dates <= end))[0]
        if len(train) and len(val):
            yield train, val


class Calibrated:
    """A fitted classifier plus a calibration map fitted on later data.

    The base model is fitted on the earliest 80% of the training window (by
    date). A logistic regression on the base model's log-probabilities is then
    fitted on the remaining 20%, which the base model has not seen (Platt
    scaling; for three classes, its multinomial generalisation).
    """

    def __init__(self, base, calibrator, n_classes: int):
        self.base, self.calibrator, self.n_classes = base, calibrator, n_classes

    @staticmethod
    def _z(raw: np.ndarray) -> np.ndarray:
        logp = np.log(np.clip(raw, 1e-6, 1.0))
        return (logp[:, 1] - logp[:, 0]).reshape(-1, 1) if raw.shape[1] == 2 else logp

    def raw_proba(self, x) -> np.ndarray:
        return self.base.predict_proba(x)

    def predict_proba(self, x) -> np.ndarray:
        raw = self.raw_proba(x)
        return raw if self.calibrator is None else self.calibrator.predict_proba(self._z(raw))


def fit_calibrated(name: str, params: dict, x: np.ndarray, y: np.ndarray, dates: np.ndarray,
                   calibration_share: float = 0.2) -> Calibrated:
    n_classes = len(np.unique(y))
    unique = np.sort(np.unique(dates))
    cum = np.searchsorted(np.sort(dates), unique, side="right") / len(dates)
    cut = unique[min(np.searchsorted(cum, 1.0 - calibration_share), len(unique) - 1)]
    early, late = dates <= cut, dates > cut
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        base = make(name, params).fit(x[early], y[early])
        calibrator = None
        # Calibrate only if the held-back slice contains every class.
        if late.sum() >= 50 and len(np.unique(y[late])) == n_classes == len(np.unique(y[early])):
            calibrator = LogisticRegression(C=10.0, max_iter=2000).fit(
                Calibrated._z(base.predict_proba(x[late])), y[late])
    return Calibrated(base, calibrator, n_classes)
