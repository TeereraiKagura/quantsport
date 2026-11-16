"""Phase 2 tests. Match data here is SYNTHETIC, simulated from known parameters
with a fixed seed so that the models can be checked against the truth. It is
never stored or used in production calculations."""

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from quantsport.db import init_db, make_engine
from quantsport.db.models import ImmutableRecordError, League, Match, Team, DataSource, IngestionRun
from quantsport.models import BaseRate, BayesianStrengths, DixonColes, LogisticMarkets, PoissonRegression
from quantsport.models.markets import OU_LINES, independent_score_matrix, market_probabilities
from quantsport.models.store import get_model_version, save_forecast, training_set
from quantsport.models.walkforward import score

AS_OF = date(2026, 6, 1)


def simulate(n_teams=10, rounds=6, seed=7):
    """Double round-robins with true attack/defence spread; returns frame + truth."""
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(n_teams)]
    att = dict(zip(teams, np.linspace(0.45, -0.45, n_teams)))
    dfn = dict(zip(teams, np.linspace(-0.3, 0.3, n_teams)))
    const, home = 0.1, 0.3
    rows, day = [], date(2024, 8, 1)
    for _ in range(rounds):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                lam = np.exp(const + home + att[h] + dfn[a])
                mu = np.exp(const + att[a] + dfn[h])
                rows.append((day, h, a, rng.poisson(lam), rng.poisson(mu)))
                day += timedelta(days=1) if len(rows) % 5 == 0 else timedelta(0)
    df = pd.DataFrame(rows, columns=["match_date", "home", "away", "home_goals", "away_goals"])
    return df, (lambda h, a: (np.exp(const + home + att[h] + dfn[a]), np.exp(const + att[a] + dfn[h])))


@pytest.fixture(scope="module")
def sim():
    return simulate()


# ---- market mathematics ----------------------------------------------------

def test_market_probabilities_are_consistent():
    probs = market_probabilities(independent_score_matrix(1.6, 1.1))
    for line in OU_LINES:
        assert probs[("OU", line, "over")] + probs[("OU", line, "under")] == pytest.approx(1)
    assert sum(probs[("1X2", 0.0, s)] for s in "HDA") == pytest.approx(1)
    assert probs[("BTTS", 0.0, "yes")] + probs[("BTTS", 0.0, "no")] == pytest.approx(1)
    overs = [probs[("OU", line, "over")] for line in OU_LINES]
    assert overs == sorted(overs, reverse=True)
    assert all(0 <= p <= 1 for p in probs.values())


def test_market_probabilities_match_closed_forms():
    lam, mu = 1.6, 1.1
    probs = market_probabilities(independent_score_matrix(lam, mu))
    total = lam + mu  # sum of independent Poissons is Poisson(lam + mu)
    under25 = np.exp(-total) * (1 + total + total**2 / 2)
    assert probs[("OU", 2.5, "under")] == pytest.approx(under25, abs=1e-9)
    assert probs[("OU", 0.5, "over")] == pytest.approx(1 - np.exp(-total), abs=1e-9)
    assert probs[("BTTS", 0.0, "yes")] == pytest.approx((1 - np.exp(-lam)) * (1 - np.exp(-mu)), abs=1e-9)


# ---- models recover known parameters --------------------------------------

@pytest.mark.parametrize("cls", [PoissonRegression, DixonColes, BayesianStrengths])
def test_goal_models_recover_expected_goals(sim, cls):
    df, truth = sim
    model = cls(xi=0.0) if cls is DixonColes else cls()
    model.fit(df, AS_OF)
    errors = []
    for h, a in [("T00", "T09"), ("T09", "T00"), ("T04", "T05"), ("T02", "T07")]:
        f = model.predict(h, a)
        lam, mu = truth(h, a)
        errors += [abs(f.exp_home - lam) / lam, abs(f.exp_away - mu) / mu]
        assert sum(f.probs[("1X2", 0.0, s)] for s in "HDA") == pytest.approx(1)
    # 540 simulated matches leave real sampling error; the Bayesian model
    # estimates twice as many strengths per team, so it is the noisiest.
    assert max(errors) < 0.3 and np.mean(errors) < 0.16


def test_dixon_coles_matches_poisson_glm_without_decay(sim):
    """With no time decay and independent data, Dixon-Coles must reproduce the
    GLM's maximum-likelihood estimates, with rho close to zero."""
    dc, glm = DixonColes(xi=0.0), PoissonRegression()
    dc.fit(sim[0], AS_OF)
    glm.fit(sim[0], AS_OF)
    assert dc.converged and abs(dc.rho) < 0.15
    assert dc.home_adv == pytest.approx(glm.home_adv, abs=0.01)
    for h, a in [("T00", "T09"), ("T05", "T02")]:
        assert dc.predict(h, a).exp_home == pytest.approx(glm.predict(h, a).exp_home, rel=0.03)


def test_dixon_coles_time_decay_follows_recent_form(sim):
    """A team that starts scoring far more late on is rated higher with decay."""
    df = sim[0].copy()
    recent = (df.match_date >= df.match_date.iloc[-120]) & (df.home == "T09")
    df.loc[recent, "home_goals"] += 3
    flat, decayed = DixonColes(xi=0.0), DixonColes(xi=0.02)
    flat.fit(df, df.match_date.max() + timedelta(days=1))
    decayed.fit(df, df.match_date.max() + timedelta(days=1))
    assert decayed.att["T09"] > flat.att["T09"]


def test_dixon_coles_matrix_applies_low_score_correction(sim):
    model = DixonColes(xi=0.0)
    model.fit(sim[0], AS_OF)
    model.rho = -0.1
    lam = np.exp(model.const + model.home_adv + model.att["T03"] + model.dfn["T04"])
    mu = np.exp(model.const + model.att["T04"] + model.dfn["T03"])
    dc, ind = model.score_matrix("T03", "T04"), independent_score_matrix(lam, mu)
    assert dc.sum() == pytest.approx(1)
    assert dc[0, 0] > ind[0, 0] and dc[1, 1] > ind[1, 1]  # negative rho: more 0-0 and 1-1
    assert dc[0, 1] < ind[0, 1] and dc[1, 0] < ind[1, 0]
    assert dc[3, 2] == pytest.approx(ind[3, 2], rel=1e-6)


def test_bayesian_shrinks_small_samples_and_reports_uncertainty(sim):
    df = sim[0]
    few, many = BayesianStrengths(), BayesianStrengths()
    few.fit(df.iloc[:60], AS_OF)
    many.fit(df, AS_OF)
    s_few, s_many = few.strengths(), many.strengths()
    assert s_few.home_attack.std() < s_many.home_attack.std()  # closer to 1.0
    assert s_few.home_attack_sd.mean() > s_many.home_attack_sd.mean()
    assert {"home_attack", "home_defence", "away_attack", "away_defence"} <= set(s_many.columns)


def test_insufficient_data_returns_none(sim):
    df = sim[0]
    newcomer = pd.DataFrame([(date(2026, 5, 1), "NEW", "T00", 1, 1)], columns=df.columns)
    train = pd.concat([df, newcomer])
    for cls in (PoissonRegression, DixonColes, BayesianStrengths, LogisticMarkets):
        model = cls()
        model.fit(train, AS_OF)
        assert model.predict("NEW", "T01") is None
        assert model.predict("T00", "UNKNOWN") is None
        assert model.predict("T00", "T01") is not None


@pytest.mark.parametrize("cls", [PoissonRegression, DixonColes, BayesianStrengths])
def test_goalless_one_match_team_does_not_wreck_the_fit(sim, cls):
    """Regression test: a promoted side with one match and no goals once made
    the unpenalised Poisson fit diverge for every team in the league."""
    df, truth = sim
    newcomer = pd.DataFrame([(date(2026, 5, 1), "T00", "NEW", 3, 0)], columns=df.columns)
    model = cls()
    model.fit(pd.concat([df, newcomer]), AS_OF)
    f = model.predict("T04", "T05")
    lam, mu = truth("T04", "T05")
    assert f.exp_home == pytest.approx(lam, rel=0.3) and f.exp_away == pytest.approx(mu, rel=0.3)
    assert 0.02 < f.probs[("BTTS", 0.0, "yes")] < 0.98


def test_logistic_probabilities_valid_and_directional(sim):
    model = LogisticMarkets()
    model.fit(sim[0], AS_OF)
    strong_home = model.predict("T00", "T09").probs
    weak_home = model.predict("T09", "T00").probs
    assert sum(strong_home[("1X2", 0.0, s)] for s in "HDA") == pytest.approx(1)
    assert strong_home[("1X2", 0.0, "H")] > weak_home[("1X2", 0.0, "H")]


# ---- leakage ---------------------------------------------------------------

def test_training_set_excludes_the_prediction_date_and_later():
    df = pd.DataFrame({
        "match_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 1)],
        "status": ["finished", "finished", "finished", "scheduled"],
    })
    train = training_set(df, date(2026, 1, 2))
    assert list(train.match_date) == [date(2026, 1, 1)] and list(train.status) == ["finished"]


@pytest.mark.parametrize("cls", [PoissonRegression, DixonColes, BayesianStrengths, LogisticMarkets, BaseRate])
def test_future_results_cannot_change_a_forecast(sim, cls):
    """Fitting through the store's gate gives the same forecast whatever
    happens on or after the prediction date."""
    df = sim[0].assign(status="finished")
    cutoff = df.match_date.iloc[400]
    tampered = df.copy()
    late = tampered.match_date >= cutoff
    tampered.loc[late, ["home_goals", "away_goals"]] = 9
    a, b = cls(), cls()
    a.fit(training_set(df, cutoff), cutoff)
    b.fit(training_set(tampered, cutoff), cutoff)
    assert a.predict("T01", "T06").probs == b.predict("T01", "T06").probs


# ---- storage ---------------------------------------------------------------

@pytest.fixture
def db():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as s:
        league = s.query(League).filter_by(code="E0").one()
        source = s.query(DataSource).first()
        run = IngestionRun(source_id=source.id, origin="test")
        home, away = Team(name="T00", country="England"), Team(name="T01", country="England")
        s.add_all([run, home, away])
        s.flush()
        match = Match(league_id=league.id, season="2026/2027", match_date=date(2026, 12, 5),
                      kickoff_utc=datetime(2026, 12, 5, 15, 0), home_team_id=home.id, away_team_id=away.id,
                      status="scheduled", source_id=source.id, first_run_id=run.id, last_run_id=run.id,
                      payload_hash="x")
        s.add(match)
        s.commit()
        yield s, match


def test_predictions_are_stored_once_and_cannot_be_changed(db, sim):
    s, match = db
    model = PoissonRegression()
    model.fit(sim[0], AS_OF)
    forecast = model.predict("T00", "T01")
    mv = get_model_version(s, model, "E0", date(2026, 12, 1), len(sim[0]))
    before = datetime(2026, 12, 4, 9, 0)
    assert save_forecast(s, match.id, mv, forecast, "live", before) is True
    assert save_forecast(s, match.id, mv, forecast, "live", before) is False  # original kept
    s.commit()
    from quantsport.db.models import Prediction
    pred = s.query(Prediction).one()
    assert pred.created_at == before and pred.exp_home_goals == pytest.approx(forecast.exp_home)
    pred.exp_home_goals = 99.0
    with pytest.raises(ImmutableRecordError):
        s.commit()
    s.rollback()
    with pytest.raises(ImmutableRecordError):
        s.delete(s.query(Prediction).one())
        s.commit()


def test_live_prediction_refused_after_kickoff(db, sim):
    s, match = db
    model = PoissonRegression()
    model.fit(sim[0], AS_OF)
    mv = get_model_version(s, model, "E0", date(2026, 12, 1), len(sim[0]))
    with pytest.raises(ValueError):
        save_forecast(s, match.id, mv, model.predict("T00", "T01"), "live", datetime(2026, 12, 5, 15, 30))


# ---- scoring ---------------------------------------------------------------

def test_scoring_rules_on_hand_computed_case():
    preds = pd.DataFrame([
        dict(match_id=1, league="X", model="base_rate", over=0.5, under=0.5, yes=0.5, no=0.5, H=0.4, D=0.3, A=0.3),
        dict(match_id=1, league="X", model="m", over=0.8, under=0.2, yes=0.6, no=0.4, H=0.7, D=0.2, A=0.1),
        dict(match_id=2, league="X", model="base_rate", over=0.5, under=0.5, yes=0.5, no=0.5, H=0.4, D=0.3, A=0.3),
        dict(match_id=2, league="X", model="m", over=0.3, under=0.7, yes=0.6, no=0.4, H=0.2, D=0.5, A=0.3),
    ])
    actual = pd.DataFrame({"match_id": [1, 2], "OU2.5": ["over", "under"], "BTTS": ["yes", "no"], "1X2": ["H", "A"]})
    s = score(preds, actual, n_boot=10).set_index(["market", "model"])
    assert s.loc[("OU2.5", "m"), "log_loss"] == pytest.approx(-(np.log(0.8) + np.log(0.7)) / 2)
    assert s.loc[("OU2.5", "m"), "brier"] == pytest.approx((0.2**2 + 0.3**2) / 2)
    assert s.loc[("1X2", "m"), "brier"] == pytest.approx(
        ((0.3**2 + 0.2**2 + 0.1**2) + (0.2**2 + 0.5**2 + 0.7**2)) / 2)
    assert s.loc[("1X2", "base_rate"), "log_loss"] == pytest.approx(-(np.log(0.4) + np.log(0.3)) / 2)
    assert s.loc[("BTTS", "m"), "n_matches"] == 2
