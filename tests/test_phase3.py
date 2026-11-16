"""Phase 3 tests. Odds and forecasts here are SYNTHETIC values chosen so the
expected answers can be worked out by hand."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from quantsport.data.ingest import ingest_bytes
from quantsport.data.leagues import LEAGUES
from quantsport.db import init_db, make_engine
from quantsport.db.models import Match
from quantsport.market import compare
from quantsport.market import pricing as px
from quantsport.market.report import value_screen
from quantsport.models.base import Forecast, Model
from quantsport.models.store import get_model_version, save_forecast

NOW = datetime(2026, 11, 16, 12, 0)


# ---- pricing maths ---------------------------------------------------------

def test_implied_probability_overround_and_proportional_fair():
    odds = [2.0, 4.0, 4.0]  # implied 0.5 + 0.25 + 0.25 = 1.0 -> no margin
    assert px.overround(odds) == pytest.approx(0.0)
    odds = [1.8, 3.6, 4.5]  # implied 0.5556 + 0.2778 + 0.2222 = 1.0556
    assert px.overround(odds) == pytest.approx(1 / 1.8 + 1 / 3.6 + 1 / 4.5 - 1)
    fair = px.fair_probabilities(odds)
    assert sum(fair) == pytest.approx(1.0)
    assert fair[0] == pytest.approx((1 / 1.8) / (1 / 1.8 + 1 / 3.6 + 1 / 4.5))


def test_power_method_sums_to_one_and_cuts_longshots_more():
    odds = [1.25, 6.0, 12.0]
    prop, power = px.fair_probabilities(odds), px.fair_probabilities(odds, "power")
    assert sum(power) == pytest.approx(1.0)
    assert power[2] < prop[2] and power[0] > prop[0]  # favourite-longshot adjustment
    assert px.fair_probabilities([2.0, 2.0], "power") == pytest.approx([0.5, 0.5])


def test_expected_value_edge_and_clv():
    assert px.expected_value(0.55, 2.0) == pytest.approx(0.10)
    assert px.expected_value(0.50, 1.9) == pytest.approx(-0.05)
    assert px.edge(0.55, 0.5) == pytest.approx(0.05)
    assert px.closing_line_value(2.10, 0.50) == pytest.approx(0.05)   # beat the close
    assert px.closing_line_value(1.90, 0.50) == pytest.approx(-0.05)
    assert px.price_clv(2.10, 2.00) == pytest.approx(0.05)


def test_invalid_odds_rejected():
    with pytest.raises(ValueError):
        px.implied_probability(1.0)
    with pytest.raises(ValueError):
        px.fair_probabilities([2.0, 3.0], "nonsense")


def test_executability_never_overstates():
    recent, stale = NOW - timedelta(minutes=5), NOW - timedelta(hours=3)
    assert px.executability(True, "scheduled", recent, NOW) == "aggregate"
    assert px.executability(False, "finished", recent, NOW) == "historical"
    assert px.executability(False, "scheduled", None, NOW) == "indicative"
    assert px.executability(False, "scheduled", stale, NOW) == "indicative"
    assert px.executability(False, "scheduled", recent, NOW) == "current"


# ---- comparison on stored data --------------------------------------------

HEADER = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,"
          "B365H,B365D,B365A,BWH,BWD,BWA,BFEH,BFED,BFEA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,"
          "B365>2.5,B365<2.5,Avg>2.5,Avg<2.5,"
          "B365CH,B365CD,B365CA,AvgCH,AvgCD,AvgCA,AvgC>2.5,AvgC<2.5")
# Pre-close 1X2: Bet365 2.00/3.50/4.00, Bwin 2.10/3.40/3.80, exchange 2.50/3.6/4.2 (must be ignored),
# average 2.00/3.40/3.90. Closing average 1.80/3.60/4.80. Bwin's away price is missing in row 2.
ROW1 = ("E0,10/10/2026,15:00,Alpha,Beta,2,1,H,"
        "2.00,3.50,4.00,2.10,3.40,3.80,2.50,3.60,4.20,2.50,3.60,4.20,2.00,3.40,3.90,"
        "1.90,1.95,1.88,1.92,"
        "1.85,3.60,4.50,1.80,3.60,4.80,1.80,2.00")
ROW2 = ("E0,11/10/2026,15:00,Gamma,Delta,0,0,D,"
        "2.60,3.20,2.80,2.70,3.10,,2.9,3.3,3.0,2.9,3.3,3.0,2.60,3.15,2.80,"
        "2.10,1.75,2.05,1.78,"
        "2.60,3.20,2.80,2.60,3.20,2.80,2.05,1.78")


class Fixed(Model):
    name = "fixed"

    def __init__(self, probs):
        super().__init__()
        self._probs = probs


@pytest.fixture
def engine():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as s:
        raw = ("\n".join([HEADER, ROW1, ROW2]) + "\n").encode()
        run = ingest_bytes(s, raw, league=LEAGUES["E0"], source_key="csv_upload", origin="t.csv",
                           today=date(2026, 11, 16), season_hint="2026/2027")
        assert run.status == "success" and run.matches_inserted == 2
        match = s.scalars(select(Match).order_by(Match.match_date)).first()
        probs = {("1X2", 0.0, "H"): 0.55, ("1X2", 0.0, "D"): 0.25, ("1X2", 0.0, "A"): 0.20,
                 ("OU", 2.5, "over"): 0.50, ("OU", 2.5, "under"): 0.50}
        model = Fixed(probs)
        mv = get_model_version(s, model, "E0", date(2026, 10, 10), 100)
        save_forecast(s, match.id, mv, Forecast(None, None, probs), "walk_forward", NOW)
        s.commit()
    return engine


def test_book_sets_only_use_complete_sets(engine):
    sets = compare.book_sets(compare.load_quotes(engine))
    bwin = sets[(sets.bookmaker == "Bwin") & (sets.market == "1X2")]
    assert bwin.match_id.nunique() == 1  # the incomplete Bwin set in row 2 is excluded
    b365 = sets[(sets.bookmaker == "Bet365") & (sets.market == "1X2") & (sets.snapshot_type == "pre_close")]
    first = b365[b365.match_id == b365.match_id.min()].set_index("selection")
    assert first.booksum.iloc[0] == pytest.approx(1 / 2.0 + 1 / 3.5 + 1 / 4.0)
    assert first.loc["H", "fair_prob"] == pytest.approx(0.5 / (1 / 2.0 + 1 / 3.5 + 1 / 4.0))
    assert first.fair_prob.sum() == pytest.approx(1.0)


def test_best_price_excludes_aggregates_and_exchange(engine):
    quotes = compare.load_quotes(engine)
    best = compare.best_prices(quotes, "pre_close")
    home = best[(best.market == "1X2") & (best.selection == "H")].sort_values("match_id").iloc[0]
    assert (home.best_price, home.best_bookmaker, home.n_books) == (2.10, "Bwin", 2)
    with_exchange = compare.best_prices(quotes, "pre_close", include_exchanges=True)
    home = with_exchange[(with_exchange.market == "1X2") & (with_exchange.selection == "H")].sort_values("match_id").iloc[0]
    assert (home.best_price, home.best_bookmaker) == (2.50, "Betfair Exchange")
    assert "Market maximum" not in set(with_exchange.best_bookmaker)


def test_cross_book_booksum(engine):
    cross = compare.cross_book(compare.best_prices(compare.load_quotes(engine), "pre_close"))
    first = cross[cross.market == "1X2"].sort_values("match_id").iloc[0]
    assert first.best_booksum == pytest.approx(1 / 2.10 + 1 / 3.50 + 1 / 4.00)


def test_movement_between_snapshots(engine):
    m = compare.movement(compare.load_quotes(engine))
    home = m[(m.market == "1X2") & (m.selection == "H")].sort_values("match_id").iloc[0]
    pre = (1 / 2.00) / (1 / 2.00 + 1 / 3.40 + 1 / 3.90)
    close = (1 / 1.80) / (1 / 1.80 + 1 / 3.60 + 1 / 4.80)
    assert home.prob_change == pytest.approx(close - pre)
    assert home.price_change == pytest.approx(1.80 / 2.00 - 1)


def test_value_assessment_matches_hand_calculation(engine):
    a = compare.value_assessments(engine, "walk_forward")
    home = a[(a.market == "1X2") & (a.selection == "H")].iloc[0]
    close = (1 / 1.80) / (1 / 1.80 + 1 / 3.60 + 1 / 4.80)
    pre = (1 / 2.00) / (1 / 2.00 + 1 / 3.40 + 1 / 3.90)
    assert home.best_price == 2.10 and home.best_bookmaker == "Bwin"
    assert home.ev == pytest.approx(0.55 * 2.10 - 1)
    assert home.edge == pytest.approx(0.55 - pre)
    assert home.clv == pytest.approx(2.10 * close - 1)
    over = a[(a.market == "OU") & (a.selection == "over")].iloc[0]
    assert over.best_price == 1.90 and over.ev == pytest.approx(0.50 * 1.90 - 1)
    assert over.clv == pytest.approx(1.90 * ((1 / 1.80) / (1 / 1.80 + 1 / 2.00)) - 1)
    assert set(a.model) == {"fixed"} and len(a) == 5


def test_value_screen_counts_flagged_selections():
    a = pd.DataFrame({
        "match_id": [1, 1, 2, 2, 3, 3], "market": ["OU"] * 6, "line": [2.5] * 6, "model": ["m"] * 6,
        "ev": [0.10, -0.15, 0.02, -0.08, 0.07, -0.12], "clv": [0.04, -0.06, -0.01, -0.03, 0.02, -0.05],
    })
    s = value_screen(a).set_index("subset")
    assert s.loc["all selections", "selections"] == 6
    assert s.loc["model EV > 0%", "selections"] == 3
    assert s.loc["model EV > 0%", "mean_clv_pct"] == pytest.approx(100 * (0.04 - 0.01 + 0.02) / 3, abs=0.01)
    assert s.loc["model EV > 5%", "selections"] == 2
    assert s.loc["model EV > 5%", "pct_beating_close"] == 100.0
