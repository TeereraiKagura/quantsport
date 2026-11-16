"""Phase 7 tests. Fixtures, prices and forecasts here are SYNTHETIC."""

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from quantsport import config
from quantsport.app import data
from quantsport.data.ingest import ingest_bytes
from quantsport.data.leagues import LEAGUES
from quantsport.db import init_db, make_engine
from quantsport.db.models import Match
from quantsport.models.base import Forecast, Model
from quantsport.models.store import get_model_version, save_forecast

TODAY = date(2026, 11, 16)
HEADER = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,BWH,BWD,BWA,AvgH,AvgD,AvgA,"
          "B365>2.5,B365<2.5,Avg>2.5,Avg<2.5")
FIX1 = "E0,21/11/2026,15:00,Alpha,Beta,,,,2.00,3.50,4.00,2.10,3.40,3.80,2.00,3.40,3.90,2.20,1.70,2.15,1.68"
FIX2 = "E0,22/11/2026,15:00,Gamma,Delta,,,,,,,,,,,,,,,,"   # no prices at all
FIX3 = "E0,22/11/2026,17:30,Epsilon,Zeta,,,,1.50,4.20,6.50,1.52,4.10,6.40,1.50,4.10,6.30,1.80,2.00,1.78,1.98"


class Named(Model):
    def __init__(self, name):
        super().__init__()
        self.name = name


def probs(over, h, d):
    return {("OU", 2.5, "over"): over, ("OU", 2.5, "under"): 1 - over,
            ("1X2", 0.0, "H"): h, ("1X2", 0.0, "D"): d, ("1X2", 0.0, "A"): 1 - h - d}


def build(url: str):
    engine = make_engine(url)
    init_db(engine)
    with Session(engine) as s:
        ingest_bytes(s, ("\n".join([HEADER, FIX1, FIX2, FIX3]) + "\n").encode(), league=LEAGUES["E0"],
                     source_key="csv_upload", origin="fixtures.csv", today=TODAY)
        ids = [m.id for m in s.scalars(select(Match).order_by(Match.match_date, Match.kickoff_utc))]
        when = datetime(2026, 11, 16, 9, 0)
        forecasts = {
            "dixon_coles": {ids[0]: (probs(0.52, 0.55, 0.25), 1.6, 1.1), ids[1]: (probs(0.50, 0.40, 0.30), 1.3, 1.2)},
            "poisson": {ids[0]: (probs(0.48, 0.43, 0.27), None, None), ids[1]: (probs(0.50, 0.40, 0.30), None, None)},
        }
        for name, per_match in forecasts.items():
            mv = get_model_version(s, Named(name), "E0", TODAY, 400)
            for mid, (p, eh, ea) in per_match.items():
                save_forecast(s, mid, mv, Forecast(eh, ea, p), "live", when)
        s.commit()
    return engine, ids


@pytest.fixture
def world():
    return build("sqlite:///:memory:")


# ---- data layer ------------------------------------------------------------

def test_selection_indicators_match_hand_calculation(world):
    engine, ids = world
    sel = data.selections(engine, "live", TODAY)
    row = sel[(sel.match_id == ids[0]) & (sel.model == "dixon_coles") & (sel.selection == "H")].iloc[0]
    assert (row.best_price, row.best_bookmaker, row.n_books) == (2.10, "Bwin", 2)
    assert row.implied_prob == pytest.approx(1 / 2.10)
    fair = (1 / 2.00) / (1 / 2.00 + 1 / 3.40 + 1 / 3.90)
    assert row.fair_prob == pytest.approx(fair)
    assert row.edge == pytest.approx(0.55 - fair) and row.ev == pytest.approx(0.55 * 2.10 - 1)
    assert row.n_models == 2 and row.disagreement == pytest.approx(np.std([0.55, 0.43]))
    assert (row.exp_home, row.exp_away) == (1.6, 1.1)
    assert row.fixture == "Alpha v Beta" and row.market_label == "Match result"
    assert bool(row.model_disagreement) is True  # 0.06 s.d. is above the 0.05 display cut
    # no validation history in this fixture: uncertainty is unknown, shown as missing, not as zero
    assert np.isnan(row.sigma)


def test_status_labels(world):
    engine, ids = world
    sel = data.selections(engine, "live", TODAY)
    dc = sel[sel.model == "dixon_coles"].set_index(["match_id", "selection"]).status_label
    assert dc[(ids[0], "H")] == "Positive EV"       # 0.55 * 2.10 - 1 = +15.5%
    assert dc[(ids[0], "A")] == "Negative EV"       # 0.20 * 4.00 - 1 = -20%
    assert dc[(ids[1], "H")] == "No price"          # fixture with no odds
    assert dc[(ids[0], "over")] == "Positive EV"    # 0.52 * 2.20 - 1 = +14.4%


def test_high_uncertainty_label_when_edge_is_inside_sigma(world, monkeypatch):
    engine, ids = world
    monkeypatch.setattr(data, "model_errors", lambda e, t: {("dixon_coles", "1X2"): 0.10, ("dixon_coles", "OU"): 0.01})
    sel = data.selections(engine, "live", TODAY)
    dc = sel[sel.model == "dixon_coles"].set_index(["match_id", "selection"])
    home = dc.loc[(ids[0], "H")]
    assert home.sigma == pytest.approx(np.sqrt(0.06**2 + 0.10**2))
    assert home.status_label == "High uncertainty"  # (0.55 - 0.117) * 2.10 - 1 < 0
    assert dc.loc[(ids[0], "over"), "status_label"] == "Positive EV"  # (0.52 - 0.022) * 2.20 - 1 > 0


def test_missing_forecasts_lists_matches_the_model_could_not_forecast(world):
    engine, ids = world
    missing = data.missing_forecasts(engine, "live", "dixon_coles")
    assert list(missing.home) == ["Epsilon"]  # the third fixture has prices but no forecast


def test_match_models_and_empty_cases(world):
    engine, ids = world
    sel = data.selections(engine, "live", TODAY)
    wide = data.match_models(sel, ids[0], "Match result").set_index("model")
    assert wide.loc["dixon_coles", "H"] == 0.55 and wide.loc["poisson", "H"] == 0.43
    assert data.selections(engine, "walk_forward", TODAY).empty


def test_reliability_bins_by_hand():
    sel = pd.DataFrame({
        "model": "m", "market": "OU", "line": 2.5, "selection": "over", "status": "finished",
        "probability": [0.62, 0.65, 0.68, 0.31, 0.35], "home_goals": [2, 3, 0, 1, 2], "away_goals": [1, 1, 0, 0, 2]})
    rel = data.reliability(sel, "m", "OU", 2.5, "over").set_index("bin")
    high, low = rel.loc["(0.6, 0.7]"], rel.loc["(0.3, 0.4]"]
    assert high.forecasts == 3 and high.mean_forecast == pytest.approx(0.65)
    assert high.observed_frequency == pytest.approx(2 / 3)  # 2-1 and 3-1 are over, 0-0 is not
    assert low.forecasts == 2 and low.observed_frequency == pytest.approx(0.5)


def test_equity_curve():
    ledger = pd.DataFrame({"match_date": pd.to_datetime(["2026-01-02", "2026-01-02", "2026-01-05"]),
                           "bankroll_after": [1010.0, 1010.0, 995.0]})
    curve = data.equity_curve(ledger, 1000.0)
    assert curve.bankroll.tolist() == [1000.0, 1010.0, 995.0]
    assert data.equity_curve(pd.DataFrame(), 1000.0).empty


# ---- API -------------------------------------------------------------------

def test_api_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from quantsport.app import api

    # A file database: the test client serves requests on another thread.
    engine, ids = build(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    monkeypatch.setattr(api, "get_engine", lambda: engine)
    monkeypatch.setattr(api, "date", type("D", (), {"today": staticmethod(lambda: TODAY)}))
    client = TestClient(api.app)
    assert client.get("/health").json() == {"status": "ok", "matches": 3, "predictions": 4}
    assert {lg["code"] for lg in client.get("/leagues").json()} == set(LEAGUES)
    assert len(client.get("/matches", params={"status": "scheduled"}).json()) == 3
    rows = client.get("/selections", params={"model": "dixon_coles", "min_ev": 0.0}).json()
    assert {(r["home"], r["selection"]) for r in rows} == {("Alpha", "H"), ("Alpha", "over")}
    assert all(r["status_label"] == "Positive EV" for r in rows)
    assert client.get("/selections", params={"kind": "walk_forward"}).json() == []
    assert client.get("/selections", params={"kind": "nonsense"}).status_code == 422
    assert client.get("/docs").status_code == 200


# ---- dashboard smoke test --------------------------------------------------

@pytest.mark.parametrize("page", ["Fixtures and value", "Model comparison", "Backtesting",
                                  "Risk and paper trading", "Data", "Definitions"])
def test_dashboard_pages_render_without_error(tmp_path, monkeypatch, page):
    from streamlit.testing.v1 import AppTest

    url = f"sqlite:///{(tmp_path / 'dash.db').as_posix()}"
    build(url)
    monkeypatch.setenv("QUANTSPORT_DATABASE_URL", url)
    config.get_settings.cache_clear()
    try:
        app = AppTest.from_file(str(config.PROJECT_ROOT / "src" / "quantsport" / "app" / "dashboard.py"),
                                default_timeout=120)
        app.run()
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, [e.value for e in app.exception]
        assert app.header[0].value.startswith(page.split(" ")[0])
    finally:
        config.get_settings.cache_clear()
