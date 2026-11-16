"""Ensemble of stored forecasts, weighted on validation data only.

The ensemble probability is a linear pool: p = sum_k w_k * p_k, with weights
w_k >= 0 that sum to 1. For each market the weights minimise the pool's mean
log loss on validation-season matches. They are then frozen and applied to the
test season. The ensemble replaces the best single model as the default for a
market only if, on the test season, its log loss is lower with a 95% paired
bootstrap interval that excludes zero.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

MARKETS = {"OU2.5": ["over", "under"], "BTTS": ["yes", "no"], "1X2": ["H", "D", "A"]}
COMPONENTS = ["dixon_coles", "poisson", "bayesian", "logistic",
              "ml_logistic", "ml_random_forest", "ml_gradient_boosting", "ml_xgboost"]


def fit_weights(p_true: np.ndarray) -> np.ndarray:
    """p_true[n, k] = probability model k gave to what happened in match n.
    Returns the simplex weights minimising -mean(log(p_true @ w))."""
    k = p_true.shape[1]

    def loss(z):
        w = np.exp(z - z.max())
        w /= w.sum()
        return -np.log(np.clip(p_true @ w, 1e-12, 1)).mean()

    res = minimize(loss, np.zeros(k), method="L-BFGS-B")
    w = np.exp(res.x - res.x.max())
    return w / w.sum()


def _stack(wide: pd.DataFrame, components: list[str], selections: list[str]):
    """Matches where every component has a forecast -> (match ids, array[n, k, c])."""
    sub = wide[wide.model.isin(components)].dropna(subset=selections)
    counts = sub.groupby("match_id").model.nunique()
    ids = np.sort(counts[counts == len(components)].index.to_numpy())
    sub = sub[sub.match_id.isin(ids)].set_index(["match_id", "model"])[selections]
    arr = np.stack([sub.xs(m, level="model").loc[ids].to_numpy() for m in components], axis=1)
    return ids, arr


def build(wide: pd.DataFrame, actual: pd.DataFrame, validation_ids: set, test_ids: set) -> dict:
    """wide: one row per (match_id, model) with a probability column per
    selection. Returns weights per market and the ensemble's test forecasts."""
    components = [m for m in COMPONENTS if m in set(wide.model)]
    outcome = actual.set_index("match_id")
    weights, pooled = {}, {}
    for market, selections in MARKETS.items():
        ids, arr = _stack(wide, components, selections)
        val = np.isin(ids, list(validation_ids))
        test = np.isin(ids, list(test_ids))
        if val.sum() < 100 or test.sum() == 0:
            continue
        hit = (outcome.loc[ids[val], market].to_numpy()[:, None] == np.array(selections)[None, :])
        p_true = (arr[val] * hit[:, None, :]).sum(axis=2)
        w = fit_weights(p_true)
        weights[market] = pd.Series(w, index=components).round(4)
        pool = (arr[test] * w[None, :, None]).sum(axis=1)
        pool /= pool.sum(axis=1, keepdims=True)
        pooled[market] = pd.DataFrame(pool, index=ids[test], columns=selections)
        weights[market].attrs["validation_matches"] = int(val.sum())
    if not pooled:
        return {"weights": {}, "forecasts": pd.DataFrame(), "components": components}
    common = sorted(set.intersection(*(set(p.index) for p in pooled.values())))
    forecasts = pd.concat([p.loc[common] for p in pooled.values()], axis=1).rename_axis("match_id").reset_index()
    return {"weights": weights, "forecasts": forecasts.assign(model="ensemble"), "components": components}


def gate(wide: pd.DataFrame, actual: pd.DataFrame, validation_ids: set, test_ids: set,
         n_boot: int = 5000, seed: int = 12345) -> pd.DataFrame:
    """Per market: the best single component on validation, and whether the
    ensemble beats it on the test season."""
    rng = np.random.default_rng(seed)
    outcome = actual.set_index("match_id")
    components = [m for m in COMPONENTS if m in set(wide.model)]
    rows = []
    for market, selections in MARKETS.items():
        if "ensemble" not in set(wide.model):
            break
        ids, arr = _stack(wide, components + ["ensemble"], selections)
        hit = (outcome.loc[ids, market].to_numpy()[:, None] == np.array(selections)[None, :])
        ll = -np.log(np.clip((arr * hit[:, None, :]).sum(axis=2), 1e-12, 1))  # [n, k+1]
        test = np.isin(ids, list(test_ids))
        vids, varr = _stack(wide, components, selections)
        val = np.isin(vids, list(validation_ids))
        vhit = (outcome.loc[vids[val], market].to_numpy()[:, None] == np.array(selections)[None, :])
        vll = -np.log(np.clip((varr[val] * vhit[:, None, :]).sum(axis=2), 1e-12, 1)).mean(axis=0)
        best = int(np.argmin(vll))
        diff = ll[test, -1] - ll[test, best]
        draws = rng.integers(0, len(diff), size=(n_boot, len(diff)))
        lo, hi = np.percentile(diff[draws].mean(axis=1), [2.5, 97.5])
        rows.append({
            "market": market, "best_single_on_validation": components[best],
            "test_matches": int(test.sum()),
            "single_test_log_loss": round(float(ll[test, best].mean()), 4),
            "ensemble_test_log_loss": round(float(ll[test, -1].mean()), 4),
            "difference": round(float(diff.mean()), 4), "ci95_low": round(float(lo), 4),
            "ci95_high": round(float(hi), 4),
            "default_engine": "ensemble" if hi < 0 else components[best],
            "reason": "ensemble measurably better" if hi < 0 else "ensemble not measurably better",
        })
    return pd.DataFrame(rows)
