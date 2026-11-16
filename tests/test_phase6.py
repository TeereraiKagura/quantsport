"""Phase 6 tests. Bets, prices and fixtures here are SYNTHETIC, chosen so the
expected figures can be worked out by hand."""

from dataclasses import replace
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from quantsport.data.ingest import ingest_bytes
from quantsport.data.leagues import LEAGUES
from quantsport.db import init_db, make_engine
from quantsport.db.models import Match, PaperBet
from quantsport.models.base import Forecast, Model
from quantsport.models.store import get_model_version, save_forecast
from quantsport.risk import monitoring, paper, simulation
from quantsport.risk.staking import (
    RiskConfig, apply_limits, combined_sigma, conservative_probability, drawdown_multiplier,
    kelly_fraction, propose, stake_base,
)

CFG = RiskConfig()


def day(rows):
    return pd.DataFrame(rows, columns=["match_id", "probability", "price", "sigma"])


# ---- staking ---------------------------------------------------------------

def test_kelly_fraction_by_hand():
    assert kelly_fraction(0.55, 2.0) == pytest.approx(0.10)
    assert kelly_fraction(0.60, 1.75) == pytest.approx(0.05 / 0.75)
    assert kelly_fraction(0.40, 2.0) == 0.0  # negative EV: no bet


def test_uncertainty_reduces_and_can_remove_the_stake():
    assert combined_sigma(0.03, 0.04) == pytest.approx(0.05)
    assert conservative_probability(0.55, 0.05, 1.0) == pytest.approx(0.50)
    bets = day([(1, 0.60, 2.0, 0.00), (2, 0.60, 2.0, 0.05), (3, 0.60, 2.0, 0.10), (4, 0.60, 2.0, 0.20)])
    stakes = propose(bets, 1000.0, replace(CFG, kelly_fraction=0.25, z=1.0))
    # full Kelly at p=0.60, 0.55, 0.50, 0.40 -> 0.20, 0.10, 0, 0
    assert stakes.tolist() == pytest.approx([50.0, 25.0, 0.0, 0.0])
    assert (np.diff(stakes) <= 0).all()


def test_stake_base_never_grows_on_profit_without_evidence():
    assert stake_base(1500.0, 1000.0, evidence_ok=False) == 1000.0  # winning run: no increase
    assert stake_base(800.0, 1000.0, evidence_ok=False) == 800.0    # losing run: decrease
    assert stake_base(1500.0, 1000.0, evidence_ok=True) == 1500.0


def test_limits_are_applied_in_order():
    bets = day([(1, 0.9, 2.0, 0), (1, 0.9, 2.0, 0), (2, 0.9, 2.0, 0), (3, 0.9, 2.0, 0)])
    stakes, hit = apply_limits(bets, np.array([50.0, 50.0, 10.0, 10.0]), 1000.0, CFG)
    # per bet 2% = 20 -> [20, 20, 10, 10]; match 1 total 40 > 3% = 30 -> [15, 15, 10, 10]
    assert stakes.tolist() == pytest.approx([15.0, 15.0, 10.0, 10.0])
    assert hit == ["per-bet", "per-match"]
    many = day([(i, 0.9, 2.0, 0) for i in range(10)])
    stakes, hit = apply_limits(many, np.full(10, 20.0), 1000.0, CFG)
    assert stakes.sum() == pytest.approx(100.0) and hit == ["daily"]  # 10% daily cap
    stakes, hit = apply_limits(many.iloc[:2], np.full(2, 20.0), 1000.0, CFG, open_exposure=230.0)
    assert stakes.sum() == pytest.approx(20.0) and hit == ["open-exposure"]  # 25% open cap


def test_drawdown_control():
    assert drawdown_multiplier(1000, 1000, CFG) == 1.0
    assert drawdown_multiplier(895, 1000, CFG) == 0.5   # 10.5% down: halve
    assert drawdown_multiplier(740, 1000, CFG) == 0.0   # 26% down: halt


# ---- monitoring ------------------------------------------------------------

def test_drawdowns_and_streaks():
    dd = monitoring.drawdowns(np.array([1000, 1100, 880, 990, 1200]))
    assert dd.max() == pytest.approx(0.2) and dd[-1] == 0.0
    assert monitoring.losing_streaks([True, False, False, True, False, False, False]) == (3, 3)
    assert monitoring.losing_streaks([False, False, True]) == (2, 0)


def test_expected_longest_losing_streak_matches_simulation():
    rng = np.random.default_rng(0)
    longest = [monitoring.losing_streaks(rng.random(400) < 0.45)[0] for _ in range(2000)]
    assert monitoring.expected_longest_losing_streak(400, 0.45) == pytest.approx(np.mean(longest), abs=1.5)


def test_concentration():
    ledger = pd.DataFrame({"league": ["A", "A", "A", "B"], "stake": [10.0, 10.0, 10.0, 10.0]})
    c = monitoring.concentration(ledger, "league")
    assert c["largest"] == "A" and c["largest_share_pct"] == 75.0
    assert c["herfindahl"] == pytest.approx(0.75**2 + 0.25**2) and c["effective_groups"] == pytest.approx(1.6)


def test_scaling_evidence_ignores_profit_and_needs_positive_clv():
    n = 600
    profitable_no_clv = pd.DataFrame({"clv": np.full(n, -0.03), "profit": np.full(n, 5.0)})
    e = monitoring.scaling_evidence(profitable_no_clv, 500)
    assert not e["allowed"] and "closing line value" in e["reasons"][0]
    good = pd.DataFrame({"clv": np.random.default_rng(1).normal(0.03, 0.05, n)})
    assert monitoring.scaling_evidence(good, 500)["allowed"]
    assert not monitoring.scaling_evidence(good.iloc[:100], 500)["allowed"]  # too few bets
    assert not monitoring.scaling_evidence(pd.DataFrame(), 500)["allowed"]


# ---- replay and Monte Carlo -----------------------------------------------

def bets_frame(n=300, p=0.55, price=2.0, sigma=0.02, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "match_id": np.arange(n), "match_date": pd.Timestamp("2026-01-01") + pd.to_timedelta(np.arange(n) // 5, unit="D"),
        "probability": p, "price": price, "sigma": sigma, "won": rng.random(n) < p, "closing_fair_prob": 0.5,
    })


def test_replay_flat_policy_by_hand():
    bets = bets_frame(10)
    ledger = simulation.replay(bets, simulation.POLICIES["flat 0.25% of start"], CFG)
    assert ledger.stake.tolist() == [2.5] * 10
    expected = np.where(bets.won, 2.5, -2.5).sum()
    assert ledger.profit.sum() == pytest.approx(expected)
    assert simulation.summarize(ledger)["final_bankroll"] == pytest.approx(1000 + expected)


def test_risk_policy_respects_limits_and_does_not_scale_up_on_profit():
    bets = bets_frame(300, p=0.70, sigma=0.0, seed=3)  # heavily winning run
    ledger = simulation.replay(bets, simulation.POLICIES["risk engine: uncertainty-adjusted quarter Kelly + limits"], CFG)
    assert ledger.bankroll_after.iloc[-1] > 1500
    assert (ledger.stake <= CFG.max_stake_pct * ledger.bankroll_before + 1e-9).all()
    daily = monitoring.daily_exposure(ledger)
    assert (daily.exposure_pct <= 100 * CFG.max_daily_pct + 1e-6).all()
    # CLV here is 2.0 * 0.5 - 1 = 0: no evidence, so stakes stay sized on the starting bankroll.
    assert ledger.stake.max() == pytest.approx(ledger.stake.iloc[0])
    naive = simulation.replay(bets, simulation.POLICIES["naive quarter Kelly, 5% cap"], CFG)
    assert naive.stake.max() > 2 * naive.stake.iloc[0]  # the naive policy does scale up


def test_risk_policy_stakes_nothing_when_edge_is_inside_uncertainty():
    bets = bets_frame(50, p=0.55, price=2.0, sigma=0.06)  # p - sigma = 0.49 -> no positive EV
    ledger = simulation.replay(bets, simulation.POLICIES["risk engine: uncertainty-adjusted quarter Kelly + limits"], CFG)
    assert len(ledger) == 0 and ledger.attrs["skipped_zero_stake"] == 50
    assert simulation.summarize(ledger)["bets_placed"] == 0


def test_risk_policy_halts_in_deep_drawdown():
    bets = bets_frame(400, p=0.9, price=1.8, sigma=0.0).assign(won=False)  # model badly wrong
    ledger = simulation.replay(bets, simulation.POLICIES["risk engine: uncertainty-adjusted quarter Kelly + limits"], CFG)
    s = simulation.summarize(ledger)
    assert s["final_bankroll"] >= 1000 * (1 - CFG.drawdown_halt_pct) - 1000 * CFG.max_daily_pct
    assert s["halted_days"] > 0 and s["bets_placed"] < 400


def test_monte_carlo_matches_theory():
    bets = bets_frame(200, p=0.5, price=2.0)
    ledger = simulation.replay(bets, simulation.POLICIES["flat 0.25% of start"], CFG)
    fair = simulation.monte_carlo(ledger, np.full(len(ledger), 0.5))
    assert abs(fair["median_final_pct"]) < 1.0 and 40 < fair["prob_loss_pct"] < 60
    edge = simulation.monte_carlo(ledger, np.full(len(ledger), 0.6))
    bad = simulation.monte_carlo(ledger, np.full(len(ledger), 0.4))
    assert edge["median_final_pct"] > 5 > -5 > bad["median_final_pct"]
    assert bad["prob_loss_pct"] > 95 and simulation.monte_carlo(ledger.iloc[0:0], np.array([])) == {}


def test_monte_carlo_keeps_each_probability_with_its_own_price():
    """Regression test: with mixed prices on the same day and fair
    probabilities (p = 1/price), the expected return is exactly zero. A
    version that mis-paired probabilities and prices showed large gains."""
    rng = np.random.default_rng(5)
    n = 400
    price = rng.choice([1.5, 2.0, 4.0, 8.0], size=n)
    bets = pd.DataFrame({
        "match_id": np.arange(n), "match_date": pd.Timestamp("2026-01-01") + pd.to_timedelta(np.arange(n) // 20, unit="D"),
        "probability": 1 / price, "price": price, "sigma": 0.0, "won": rng.random(n) < 1 / price,
        "closing_fair_prob": 1 / price,
    })
    ledger = simulation.replay(bets, simulation.POLICIES["flat 0.25% of start"], CFG)
    fair = simulation.monte_carlo(ledger, ledger.closing_fair_prob.to_numpy())
    assert abs(fair["median_final_pct"]) < 2.0 and 35 < fair["prob_loss_pct"] < 65
    with_margin = simulation.monte_carlo(ledger, (ledger.closing_fair_prob / 1.05).to_numpy())
    assert with_margin["median_final_pct"] < -3.0  # a 5% margin must cost about 5% of turnover


# ---- paper trading ---------------------------------------------------------

HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,AvgH,AvgD,AvgA,B365>2.5,B365<2.5,Avg>2.5,Avg<2.5"
FIXTURE = "E0,21/11/2026,15:00,Alpha,Beta,,,,2.10,3.40,3.80,2.05,3.35,3.70,2.20,1.70,2.15,1.68"
RESULT = ("E0,21/11/2026,15:00,Alpha,Beta,3,1,H,2.10,3.40,3.80,2.05,3.35,3.70,2.20,1.70,2.15,1.68,"
          "2.00,3.50,4.00,2.00,3.50,4.00")
RESULT_HEADER = HEADER + ",B365CH,B365CD,B365CA,AvgCH,AvgCD,AvgCA"
BEFORE, AFTER = datetime(2026, 11, 20, 10, 0), datetime(2026, 11, 22, 10, 0)


class Named(Model):
    def __init__(self, name):
        super().__init__()
        self.name = name


@pytest.fixture
def world():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as s:
        ingest_bytes(s, f"{HEADER}\n{FIXTURE}\n".encode(), league=LEAGUES["E0"], source_key="csv_upload",
                     origin="fixtures.csv", today=date(2026, 11, 16))
        match = s.scalars(select(Match)).one()
        probs = {("OU", 2.5, "over"): 0.62, ("OU", 2.5, "under"): 0.38,
                 ("1X2", 0.0, "H"): 0.46, ("1X2", 0.0, "D"): 0.29, ("1X2", 0.0, "A"): 0.25}
        for name in ("ml_random_forest", "poisson"):
            mv = get_model_version(s, Named(name), "E0", date(2026, 11, 16), 500)
            save_forecast(s, match.id, mv, Forecast(None, None, probs), "live", BEFORE)
        s.commit()
        paper.create(s, "test", 1000.0, settings={"model_error": 0.02})
        yield engine, s, match


def test_paper_bet_is_sized_by_the_risk_engine_and_recorded_before_kickoff(world):
    engine, s, match = world
    bets = paper.place(engine, s, "test", BEFORE)
    assert len(bets) == 1  # over 2.5 qualifies (EV +36%); no 1X2 selection has positive EV
    b = bets[0]
    assert (b.market, b.selection, b.odds, b.bookmaker, b.price_status) == ("OU", "over", 2.20, "Bet365", "indicative")
    p_c = 0.62 - 0.02  # both models agree, so sigma is the model error alone
    kelly_stake = 0.25 * (p_c * 2.20 - 1) / 1.20 * 1000
    assert b.stake == pytest.approx(min(kelly_stake, 20.0))  # 2% per-bet cap binds
    assert paper.place(engine, s, "test", BEFORE) == []  # never a second bet on the same market
    st = paper.status(engine, s, "test")
    assert (st["open_bets"], st["open_exposure"], st["settled_bets"]) == (1, 20.0, 0)
    assert st["stake_review"]["allowed"] is False


def test_paper_bet_refused_after_kickoff(world):
    engine, s, match = world
    assert paper.place(engine, s, "test", datetime(2026, 11, 21, 15, 30)) == []


def test_paper_settlement_profit_and_clv(world):
    engine, s, match = world
    paper.place(engine, s, "test", BEFORE)
    assert paper.settle(engine, s, "test", BEFORE) == 0  # match not finished yet
    ingest_bytes(s, f"{RESULT_HEADER}\n{RESULT}\n".encode(), league=LEAGUES["E0"], source_key="csv_upload",
                 origin="results.csv", today=date(2026, 11, 22))
    assert paper.settle(engine, s, "test", AFTER) == 1
    bet = s.scalars(select(PaperBet)).one()
    assert (bet.status, bet.profit) == ("won", pytest.approx(20.0 * 1.20))  # 3-1: over 2.5 wins
    st = paper.status(engine, s, "test")
    assert st["bankroll"] == pytest.approx(1024.0) and st["roi_pct"] == pytest.approx(120.0)
    assert st["longest_losing_streak"] == 0
