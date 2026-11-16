"""Phase 5 tests. All match data here is SYNTHETIC (simulated with a fixed
seed) and exists only to check the machinery."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quantsport.ml import ensemble
from quantsport.ml import estimators as est
from quantsport.ml.features import FEATURES, MIN_HISTORY, build_features
from quantsport.ml.pipeline import TARGETS, month_blocks, tune


def simulate(n_teams=12, rounds=4, seed=3, league="X1"):
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(n_teams)]
    strength = dict(zip(teams, np.linspace(0.5, -0.5, n_teams)))
    rows, day, mid = [], date(2025, 8, 1), 1
    for _ in range(rounds):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                hg = rng.poisson(np.exp(0.3 + strength[h] - strength[a] * 0.5))
                ag = rng.poisson(np.exp(0.0 + strength[a] - strength[h] * 0.5))
                rows.append(dict(match_id=mid, league=league, season="2025/2026", match_date=day,
                                 status="finished", home=h, away=a, home_goals=hg, away_goals=ag,
                                 home_shots=10 + 3 * hg, away_shots=8 + 3 * ag,
                                 home_sot=3 + hg, away_sot=2 + ag))
                mid += 1
                if mid % 6 == 0:
                    day += timedelta(days=1)
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def matches():
    return simulate()


@pytest.fixture(scope="module")
def feats(matches):
    return build_features(matches)


# ---- features --------------------------------------------------------------

def test_feature_table_shape_and_usability(matches, feats):
    assert len(feats) == len(matches) and set(FEATURES) <= set(feats.columns)
    first = feats.iloc[0]
    assert not first.usable and pd.isna(first.h_gf5)  # nobody has history on day one
    usable = feats[feats.usable]
    assert len(usable) > 0.7 * len(feats)
    assert usable[["h_gf5", "a_ga10", "elo_diff", "h_rest"]].notna().all().all()


def test_features_match_a_hand_computation(matches, feats):
    row = feats[feats.usable].iloc[200]
    m = matches.set_index("match_id").loc[row.match_id]
    earlier = matches[matches.match_date < m.match_date]
    played = earlier[(earlier.home == m.home) | (earlier.away == m.home)].tail(5)
    gf = np.where(played.home == m.home, played.home_goals, played.away_goals).mean()
    ga = np.where(played.home == m.home, played.away_goals, played.home_goals).mean()
    assert row.h_gf5 == pytest.approx(gf) and row.h_ga5 == pytest.approx(ga)
    home_only = earlier[earlier.home == m.home].tail(5)
    assert row.h_home_gf5 == pytest.approx(home_only.home_goals.mean())
    assert row.league_gpm == pytest.approx((earlier.home_goals + earlier.away_goals).mean())


def test_features_ignore_same_day_and_future_results(matches, feats):
    """Leakage guard: rewrite every result on or after a cut-off date; features
    of matches up to and including that date must not move."""
    cutoff = matches.match_date.iloc[300]
    tampered = matches.copy()
    late = tampered.match_date >= cutoff
    tampered.loc[late, ["home_goals", "away_goals", "home_shots", "away_shots"]] = 9
    again = build_features(tampered)
    keep = feats.match_date <= cutoff
    pd.testing.assert_frame_equal(feats.loc[keep, FEATURES], again.loc[keep, FEATURES])
    after = feats.match_date > cutoff + timedelta(days=3)
    assert not feats.loc[after, FEATURES].equals(again.loc[after, FEATURES])  # and later ones do change


def test_scheduled_matches_get_features_but_no_targets(matches):
    upcoming = matches.iloc[-1:].assign(match_id=99999, status="scheduled", home_goals=None, away_goals=None,
                                        match_date=matches.match_date.max() + timedelta(days=7))
    f = build_features(pd.concat([matches, upcoming], ignore_index=True))
    row = f[f.match_id == 99999].iloc[0]
    assert row.usable and pd.notna(row.h_gf5) and pd.isna(row.over25)


def test_missing_shot_data_stays_missing(matches):
    f = build_features(matches.assign(home_shots=None, away_shots=None, home_sot=None, away_sot=None))
    usable = f[f.usable]
    assert usable.h_sh10.isna().all() and usable.h_gf5.notna().all()


# ---- chronological validation ---------------------------------------------

def test_rolling_splits_never_train_on_the_future():
    dates = np.repeat(np.arange(100), 7)
    splits = list(est.rolling_splits(dates, n_splits=3))
    assert len(splits) == 3
    previous_end = -1
    for train, val in splits:
        assert dates[train].max() < dates[val].min()
        assert dates[val].min() > previous_end
        previous_end = dates[val].max()
    assert set(dates[splits[-1][1]]) | set(dates[splits[-1][0]]) == set(dates)


def test_month_blocks():
    dates = pd.Series([date(2025, 12, 30), date(2026, 1, 3), date(2026, 1, 20), date(2026, 3, 1), date(2026, 12, 5)])
    assert month_blocks(dates, date(2026, 1, 1)) == [
        (date(2026, 1, 1), date(2026, 2, 1)), (date(2026, 3, 1), date(2026, 4, 1)),
        (date(2026, 12, 1), date(2027, 1, 1))]


# ---- estimators, tuning, calibration --------------------------------------

@pytest.mark.parametrize("name", est.MODEL_NAMES)
def test_every_model_fits_with_missing_values_and_gives_valid_probabilities(feats, name):
    rows = feats[feats.usable].copy()
    rows.loc[rows.index[::7], "h_sh10"] = np.nan
    x = rows[FEATURES].to_numpy(dtype=float)
    d = rows.match_date.map(date.toordinal).to_numpy()
    for target, keys in TARGETS.items():
        y = rows[target].to_numpy(dtype=int)
        model = est.fit_calibrated(name, est.grid(name)[0], x, y, d)
        p = model.predict_proba(x[-50:])
        assert p.shape == (50, len(keys)) and np.allclose(p.sum(axis=1), 1) and (p >= 0).all()


def test_tuning_returns_a_choice_for_every_model_and_target(feats):
    rows = feats[feats.usable]
    chosen, table = tune(rows)
    assert set(chosen) == {(m, t) for m in est.MODEL_NAMES for t in TARGETS}
    assert table.groupby(["model", "target"]).chosen.sum().eq(1).all()
    best = table[table.chosen].set_index(["model", "target"]).cv_log_loss.sort_index()
    assert (table.groupby(["model", "target"]).cv_log_loss.min().sort_index() == best).all()


def test_calibration_repairs_an_overconfident_model():
    """A classifier that is systematically overconfident should score better
    after Platt scaling on held-back data."""
    rng = np.random.default_rng(0)
    n = 4000
    x = rng.normal(size=(n, 1))
    y = (rng.random(n) < 1 / (1 + np.exp(-x[:, 0]))).astype(int)

    class Overconfident:
        def predict_proba(self, x):
            p = 1 / (1 + np.exp(-4 * x[:, 0]))  # true slope is 1
            return np.column_stack([1 - p, p])

    base = Overconfident()
    from sklearn.linear_model import LogisticRegression
    half = n // 2
    cal = LogisticRegression(C=10.0).fit(est.Calibrated._z(base.predict_proba(x[:half])), y[:half])
    model = est.Calibrated(base, cal, 2)
    raw = est.log_loss(model.raw_proba(x[half:]), y[half:])
    fixed = est.log_loss(model.predict_proba(x[half:]), y[half:])
    assert fixed < raw - 0.05


# ---- ensemble --------------------------------------------------------------

def test_weights_are_a_simplex_and_favour_the_better_model():
    rng = np.random.default_rng(1)
    truth = rng.uniform(0.2, 0.8, 3000)
    happened = rng.random(3000) < truth
    good = np.where(happened, truth, 1 - truth)
    noise = np.clip(truth + rng.normal(0, 0.25, 3000), 0.02, 0.98)
    bad = np.where(happened, noise, 1 - noise)
    w = ensemble.fit_weights(np.column_stack([good, bad]))
    assert w.sum() == pytest.approx(1) and (w >= 0).all() and w[0] > 0.8


def _wide(ids, model, p_over):
    return pd.DataFrame({"match_id": ids, "model": model, "over": p_over, "under": 1 - p_over,
                         "yes": 0.5, "no": 0.5, "H": 0.4, "D": 0.3, "A": 0.3})


def test_ensemble_is_fitted_on_validation_and_applied_to_test_only():
    rng = np.random.default_rng(2)
    ids = np.arange(1, 601)
    truth = rng.uniform(0.2, 0.8, 600)
    over = rng.random(600) < truth
    actual = pd.DataFrame({"match_id": ids, "OU2.5": np.where(over, "over", "under"),
                           "BTTS": "yes", "1X2": "H"})
    wide = pd.concat([_wide(ids, "dixon_coles", truth),
                      _wide(ids, "poisson", np.clip(truth + rng.normal(0, 0.3, 600), 0.02, 0.98))])
    val, test = set(ids[:400]), set(ids[400:])
    built = ensemble.build(wide, actual, val, test)
    assert built["weights"]["OU2.5"]["dixon_coles"] > 0.7
    f = built["forecasts"]
    assert set(f.match_id) == test and np.allclose(f.over + f.under, 1)
    # Changing test outcomes must not change the weights.
    flipped = actual.copy()
    flipped.loc[flipped.match_id > 400, "OU2.5"] = "over"
    again = ensemble.build(wide, flipped, val, test)
    assert again["weights"]["OU2.5"].equals(built["weights"]["OU2.5"])


def test_gate_keeps_single_model_unless_ensemble_is_measurably_better():
    rng = np.random.default_rng(4)
    ids = np.arange(1, 801)
    truth = rng.uniform(0.2, 0.8, 800)
    over = rng.random(800) < truth
    actual = pd.DataFrame({"match_id": ids, "OU2.5": np.where(over, "over", "under"), "BTTS": "yes", "1X2": "H"})
    wide = pd.concat([_wide(ids, "dixon_coles", truth), _wide(ids, "poisson", truth)])
    val, test = set(ids[:400]), set(ids[400:])
    built = ensemble.build(wide, actual, val, test)
    g = ensemble.gate(pd.concat([wide, built["forecasts"]]), actual, val, test).set_index("market")
    assert g.loc["OU2.5", "default_engine"] != "ensemble"  # identical components: no measurable gain
    assert g.loc["OU2.5", "difference"] == pytest.approx(0, abs=1e-6)
