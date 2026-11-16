"""QuantSport dashboard (Streamlit MVP).

Run:  python -m streamlit run src/quantsport/app/dashboard.py
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quantsport.app import data
from quantsport.backtest.engine import BacktestConfig, load_data
from quantsport.backtest.engine import run as run_backtest
from quantsport.config import PROJECT_ROOT, get_settings
from quantsport.data import quality
from quantsport.data.ingest import ingest_bytes
from quantsport.data.leagues import LEAGUES
from quantsport.db import init_db, make_engine, make_session_factory

STATUS_COLOURS = {"Positive EV": "#d7f0dd", "Negative EV": "#f6dcdc", "High uncertainty": "#fff1cc",
                  "No price": "#e8e8e8"}
DOCS = {"Models and forecast metrics": "MODELS.md", "Market: margin, EV, CLV": "MARKET.md",
        "Backtesting": "BACKTEST.md", "Machine learning and ensemble": "ML.md", "Risk": "RISK.md",
        "Dashboard indicators": "DASHBOARD.md", "Data sources": "DATA_SOURCES.md"}

st.set_page_config(page_title="QuantSport", layout="wide")


@st.cache_resource
def get_engine():
    engine = make_engine(get_settings().database_url)
    init_db(engine)
    return engine


@st.cache_data(ttl=600, show_spinner="Loading forecasts and prices...")
def load_selections(kind: str, today: date) -> pd.DataFrame:
    return data.selections(get_engine(), kind, today)


@st.cache_data(ttl=600, show_spinner="Loading backtest data...")
def backtest_data():
    return load_data(get_engine())


@st.cache_data(ttl=600, show_spinner="Scoring models...")
def comparison(today: date):
    from quantsport.ml import report as mlr
    from quantsport.models import walkforward as wf

    engine = get_engine()
    all_matches, val_ids, test_ids = mlr._splits(engine, today)
    actual = pd.concat([wf.outcomes(engine, code) for code in LEAGUES], ignore_index=True)
    wide = mlr.wide_predictions(engine)
    if wide.empty:
        return pd.DataFrame(), pd.DataFrame()
    market = pd.concat([wf._market_benchmark(engine, c, all_matches[all_matches.league == c]) for c in LEAGUES],
                       ignore_index=True)
    everything = pd.concat([wide, market], ignore_index=True)
    return (mlr._comparison(everything[everything.match_id.isin(val_ids) & (everything.model != "ensemble")], actual),
            mlr._comparison(everything[everything.match_id.isin(test_ids)], actual))


def banner():
    st.caption("Research and paper trading only. No real-money betting. Expected value shown here is "
               "theoretical: stored prices have no collection time and were never verified as obtainable.")


# --------------------------------------------------------------------------- fixtures

def page_fixtures(today: date):
    st.header("Fixtures and value")
    banner()
    mode = st.radio("View", ["Upcoming fixtures (live forecasts)", "Historical reconstruction (walk-forward)"],
                    horizontal=True)
    kind = "live" if mode.startswith("Upcoming") else "walk_forward"
    sel = load_selections(kind, today)
    if sel.empty:
        if kind == "live":
            st.info("There are no live forecasts. The data provider currently lists no upcoming fixtures "
                    "for the tracked leagues, so nothing can be forecast yet. Run `ingest-fixtures` and "
                    "`predict-upcoming` when fixtures are published, or switch to the historical view.")
        else:
            st.info("No walk-forward forecasts are stored. Run `python -m quantsport walk-forward`.")
        return
    if kind == "walk_forward":
        st.warning("Historical reconstruction: forecasts were generated after the matches, using only "
                   "data from before each match. These are not live predictions.")

    models = sorted(sel.model.unique())
    c1, c2, c3, c4 = st.columns(4)
    model = c1.selectbox("Model", models, index=models.index("dixon_coles") if "dixon_coles" in models else 0)
    leagues = c2.multiselect("League", sorted(sel.league.unique()), format_func=lambda c: f"{c} - {LEAGUES[c].name}")
    market_labels = sorted(sel.market_label.unique())
    markets = c3.multiselect("Betting market", market_labels,
                             default=[m for m in market_labels if m in ("Over/Under 2.5", "Match result")])
    team = c4.text_input("Team contains")
    c5, c6, c7, c8 = st.columns(4)
    lo, hi = sel.match_date.min().date(), sel.match_date.max().date()
    dates = c5.date_input("Date range", (max(lo, hi - pd.Timedelta(days=30)), hi), min_value=lo, max_value=hi)
    min_ev = c6.number_input("Minimum expected value (%)", value=-100.0, step=1.0)
    min_odds = c7.number_input("Minimum available odds", value=1.0, step=0.1, min_value=1.0)
    statuses = c8.multiselect("Status", list(STATUS_COLOURS), default=list(STATUS_COLOURS))

    view = sel[sel.model == model]
    if leagues:
        view = view[view.league.isin(leagues)]
    if markets:
        view = view[view.market_label.isin(markets)]
    if team:
        view = view[view.fixture.str.contains(team, case=False, regex=False)]
    if len(dates) == 2:
        view = view[(view.match_date.dt.date >= dates[0]) & (view.match_date.dt.date <= dates[1])]
    priced = view.best_price.notna()
    view = view[~priced | ((view.ev * 100 >= min_ev) & (view.best_price >= min_odds))]
    if min_ev > -100 or min_odds > 1:
        view = view[view.best_price.notna()]
    view = view[view.status_label.isin(statuses)]

    counts = view.status_label.value_counts()
    cols = st.columns(5)
    cols[0].metric("Selections shown", len(view))
    for col, label in zip(cols[1:], STATUS_COLOURS):
        col.metric(label, int(counts.get(label, 0)))

    table = view.sort_values(["match_date", "fixture", "market_label", "selection"])[[
        "match_date", "league", "fixture", "market_label", "selection", "probability", "exp_home", "exp_away",
        "best_price", "best_bookmaker", "implied_prob", "fair_prob", "edge", "ev", "n_models", "disagreement",
        "sigma", "model_disagreement", "status_label"]].rename(columns={
            "match_date": "Date", "league": "League", "fixture": "Fixture", "market_label": "Market",
            "selection": "Selection", "probability": "Model prob.", "exp_home": "Exp. home goals",
            "exp_away": "Exp. away goals", "best_price": "Best odds", "best_bookmaker": "Bookmaker",
            "implied_prob": "Implied prob.", "fair_prob": "Market fair prob.", "edge": "Edge", "ev": "EV",
            "n_models": "Models", "disagreement": "Disagreement", "sigma": "Uncertainty (sigma)",
            "model_disagreement": "Models disagree", "status_label": "Status"})
    table["Date"] = table["Date"].dt.date
    shown = table.head(1500)
    styled = shown.style.apply(
        lambda row: [f"background-color: {STATUS_COLOURS[row['Status']]}; color: #111" if c == "Status" else ""
                     for c in shown.columns], axis=1).format({
        "Model prob.": "{:.1%}", "Implied prob.": "{:.1%}", "Market fair prob.": "{:.1%}", "Edge": "{:+.1%}",
        "EV": "{:+.1%}", "Disagreement": "{:.3f}", "Uncertainty (sigma)": "{:.3f}", "Best odds": "{:.2f}",
        "Exp. home goals": "{:.2f}", "Exp. away goals": "{:.2f}"}, na_rep="n/a")
    st.dataframe(styled, width="stretch", hide_index=True, height=480)
    if len(table) > len(shown):
        st.caption(f"Showing the first {len(shown)} of {len(table)} rows. Narrow the filters to see the rest.")
    st.caption("Expected goals are from the Dixon-Coles model. Status: **Positive EV** = EV above zero and still "
               "above zero after subtracting one sigma of probability uncertainty; **High uncertainty** = EV above "
               "zero but inside the model's error; **Models disagree** = standard deviation across models above "
               f"{data.DISAGREEMENT_FLAG:.2f}. Definitions: see the Definitions page.")

    missing = data.missing_forecasts(get_engine(), kind, model, set(sel.match_id) if kind == "walk_forward" else None)
    with st.expander(f"Insufficient data: {len(missing)} matches without a forecast from this model"):
        st.caption("A model gives no forecast when a team has too few earlier matches. Nothing is estimated.")
        st.dataframe(missing, width="stretch", hide_index=True)

    st.subheader("Model agreement for one match")
    fixtures = view.drop_duplicates("match_id").sort_values("match_date", ascending=False)
    if fixtures.empty:
        st.caption("No fixtures match the filters.")
        return
    labels = {int(r.match_id): f"{r.match_date:%Y-%m-%d}  {r.fixture} ({r.league})" for r in fixtures.itertuples()}
    mid = st.selectbox("Match", list(labels), format_func=labels.get)
    market_label = st.selectbox("Market", sorted(sel[sel.match_id == mid].market_label.unique()), key="detail_market")
    wide = data.match_models(sel, mid, market_label)
    fig = go.Figure()
    for column in [c for c in wide.columns if c != "model"]:
        fig.add_bar(name=str(column), x=wide.model, y=wide[column])
    fig.update_layout(barmode="group", yaxis_title="Probability", yaxis_tickformat=".0%", height=360,
                      margin=dict(t=20, b=20))
    st.plotly_chart(fig, width="stretch")


# --------------------------------------------------------------------------- models

def page_models(today: date):
    st.header("Model comparison")
    banner()
    validation, test = comparison(today)
    st.caption("Log loss and Brier score on identical matches per market (lower is better). `ll_minus_ref` is the "
               "model's log loss minus the reference's, with a 95% paired bootstrap interval. The reference is the "
               "closing market where prices exist, otherwise the league base rate.")
    tab_test, tab_val = st.tabs(["Test season (current)", "Validation season (previous)"])
    for tab, frame in ((tab_test, test), (tab_val, validation)):
        with tab:
            if frame.empty:
                st.info("No scored matches.")
                continue
            for market, g in frame.groupby("market"):
                st.subheader(f"{market}: {int(g.n_matches.iloc[0])} matches")
                st.dataframe(g.drop(columns=["market", "n_matches"]), width="stretch", hide_index=True)

    st.subheader("Calibration")
    sel = load_selections("walk_forward", today)
    if sel.empty:
        st.info("No walk-forward forecasts stored.")
        return
    c1, c2 = st.columns(2)
    models = sorted(sel.model.unique())
    model = c1.selectbox("Model", models, index=models.index("dixon_coles") if "dixon_coles" in models else 0,
                         key="cal_model")
    options = {"Over 2.5 goals": ("OU", 2.5, "over"), "Both teams to score": ("BTTS", 0.0, "yes"),
               "Home win": ("1X2", 0.0, "H"), "Draw": ("1X2", 0.0, "D"), "Away win": ("1X2", 0.0, "A")}
    choice = c2.selectbox("Outcome", list(options))
    rel = data.reliability(sel, model, *options[choice])
    if rel.empty:
        st.info("No finished matches with this forecast.")
        return
    fig = go.Figure()
    fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="Perfect calibration", line=dict(dash="dash", color="grey"))
    fig.add_scatter(x=rel.mean_forecast, y=rel.observed_frequency, mode="markers+lines", name=model,
                    error_y=dict(type="data", array=rel.interval), text=rel.forecasts,
                    hovertemplate="forecast %{x:.1%}<br>observed %{y:.1%}<br>n=%{text}")
    fig.update_layout(xaxis_title="Mean forecast probability", yaxis_title="Observed frequency",
                      xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=420, margin=dict(t=20))
    st.plotly_chart(fig, width="stretch")
    st.caption("Each point is a 10-point probability bin of all stored walk-forward forecasts (both seasons). "
               "Bars are 95% intervals for the observed frequency: 1.96 x sqrt(f(1-f)/n).")
    st.dataframe(rel, width="stretch", hide_index=True)


# --------------------------------------------------------------------------- backtest

def page_backtest(today: date):
    st.header("Backtesting")
    banner()
    st.caption("Historical simulation on stored walk-forward forecasts and pre-closing prices. Not live or "
               "paper-trading performance.")
    sel_models = sorted(backtest_data()[1].model.unique()) if len(backtest_data()[1]) else []
    if not sel_models:
        st.info("No walk-forward forecasts stored.")
        return
    c1, c2, c3, c4 = st.columns(4)
    model = c1.selectbox("Model", sel_models, index=sel_models.index("dixon_coles") if "dixon_coles" in sel_models else 0)
    market = c2.selectbox("Betting market", ["Over/Under 2.5", "Match result (1X2)"])
    split = c3.selectbox("Season", ["Validation (previous season)", "Test (current season)"])
    leagues = c4.multiselect("Leagues", list(LEAGUES), format_func=lambda c: f"{c} - {LEAGUES[c].name}")
    c5, c6, c7, c8 = st.columns(4)
    min_ev = c5.number_input("Minimum expected value (%)", value=5.0, step=1.0)
    min_odds = c6.number_input("Minimum odds", value=1.0, step=0.1, min_value=1.0)
    max_odds = c7.number_input("Maximum odds", value=1000.0, step=1.0, min_value=1.0)
    source = c8.selectbox("Price source", ["Bet365", "best"], help="'best' takes the highest individual "
                          "bookmaker price, which assumes an account at every bookmaker.")
    c9, c10, c11, c12 = st.columns(4)
    staking = c9.selectbox("Staking strategy", ["flat", "percent", "kelly"])
    stake_pct = c10.number_input("Stake (% of bankroll)", value=0.25, step=0.05, min_value=0.01)
    kelly = c11.number_input("Kelly fraction", value=0.25, step=0.05, min_value=0.01, max_value=1.0)
    commission = c12.number_input("Commission on winnings (%)", value=0.0, step=0.5, min_value=0.0)
    if split.startswith("Test"):
        st.warning("The test season is for final evaluation. Choosing settings by what performs best here "
                   "is over-fitting; choose on the validation season.")
    cfg = BacktestConfig(
        model=model, market="OU" if market.startswith("Over") else "1X2", line=2.5 if market.startswith("Over") else 0.0,
        seasons_ago=1 if split.startswith("Validation") else 0, leagues=tuple(leagues) or None, min_ev=min_ev / 100,
        min_odds=min_odds, max_odds=max_odds, price_source=source, staking=staking, stake_pct=stake_pct / 100,
        kelly_fraction=kelly, commission=commission / 100)
    summary, ledger, coverage = run_backtest(get_engine(), cfg, today, backtest_data())

    st.subheader(f"Result: {summary['verdict']}")
    m = st.columns(6)
    m[0].metric("Total bets", summary["bets"])
    m[1].metric("Won / lost", f"{summary['wins']} / {summary['losses']}")
    m[2].metric("Total staked", f"{summary['staked']:.0f}")
    m[3].metric("Net profit", f"{summary['profit']:+.1f}")
    m[4].metric("ROI", "n/a" if summary["roi_pct"] is None else f"{summary['roi_pct']:+.1f}%")
    m[5].metric("Max drawdown", "n/a" if summary["max_drawdown_pct"] is None else f"{summary['max_drawdown_pct']:.1f}%")
    m = st.columns(6)
    ci = ("not computed (under 30 bets)" if summary["roi_ci95_low"] is None
          else f"{summary['roi_ci95_low']:+.1f}% to {summary['roi_ci95_high']:+.1f}%")
    m[0].metric("Mean CLV", "n/a" if summary["mean_clv_pct"] is None else f"{summary['mean_clv_pct']:+.1f}%")
    m[1].metric("Win rate", "n/a" if summary["win_rate_pct"] is None else f"{summary['win_rate_pct']:.1f}%")
    m[2].metric("Mean odds", "n/a" if summary["mean_odds"] is None else f"{summary['mean_odds']:.2f}")
    m[3].metric("Final bankroll", f"{summary['final_bankroll']:.0f}")
    m[4].metric("Skipped after ruin", summary["skipped_after_ruin"])
    st.write(f"**ROI 95% interval:** {ci} (bootstrap over matches).")
    st.caption(f"Coverage: {coverage['finished_matches']} finished matches, {coverage['with_forecast']} with a "
               f"forecast, {coverage['with_price']} with a price from this source. Matches without either are not bet.")
    if len(ledger):
        curve = data.equity_curve(ledger, cfg.initial_bankroll)
        fig = go.Figure(go.Scatter(x=curve.match_date, y=curve.bankroll, mode="lines", name="Bankroll"))
        fig.add_hline(y=cfg.initial_bankroll, line_dash="dash", line_color="grey")
        fig.update_layout(yaxis_title="Bankroll (units)", height=360, margin=dict(t=20))
        st.plotly_chart(fig, width="stretch")
        st.download_button("Download bet ledger (CSV)", ledger.to_csv(index=False), "backtest_ledger.csv", "text/csv")


# --------------------------------------------------------------------------- risk

def page_risk(today: date):
    st.header("Risk and paper trading")
    banner()
    from sqlalchemy import select

    from quantsport.db.models import Portfolio
    from quantsport.risk import paper

    engine = get_engine()
    with make_session_factory(engine)() as session:
        names = list(session.scalars(select(Portfolio.name)))
        st.subheader("Paper portfolios")
        if not names:
            st.info("No paper portfolio exists. Create one with `python -m quantsport paper create`.")
        for name in names:
            s = paper.status(engine, session, name)
            with st.expander(f"{name}: bankroll {s['bankroll']:.2f}, {s['settled_bets']} settled, "
                             f"{s['open_bets']} open", expanded=True):
                if "note" in s:
                    st.caption(s["note"].capitalize() + ". Paper bets need live forecasts for upcoming fixtures.")
                review = s.get("stake_review")
                if review:
                    st.write("**Stake review:** " + ("stakes may follow the bankroll upward." if review["allowed"]
                             else "do not increase stakes: " + "; ".join(review["reasons"]) + "."))
                st.json({k: v for k, v in s.items() if k != "stake_review"}, expanded=False)
    st.subheader("Latest risk report")
    reports = sorted(get_settings().reports_dir.glob("phase6_risk_*.md"))
    if reports:
        st.caption(f"From {reports[-1].name}. Regenerate with `python -m quantsport risk-report`.")
        st.markdown(reports[-1].read_text(encoding="utf-8"))
    else:
        st.info("No risk report yet. Run `python -m quantsport risk-report`.")


# --------------------------------------------------------------------------- data

def page_data(today: date):
    st.header("Data")
    engine = get_engine()
    cov = quality.coverage_table(engine)
    st.subheader("Coverage by league and season")
    st.caption("Percentages are the share of finished matches where the field is present. Missing values are "
               "never filled in.")
    st.dataframe(cov, width="stretch", hide_index=True)
    st.subheader("Validation issues")
    st.dataframe(quality.issue_table(engine), width="stretch", hide_index=True)
    st.subheader("Recent ingestion runs")
    runs = pd.read_sql("SELECT id, origin, status, started_at, rows_read, matches_inserted, matches_updated, "
                       "matches_unchanged, rows_rejected, error FROM ingestion_runs ORDER BY id DESC LIMIT 30", engine)
    st.dataframe(runs, width="stretch", hide_index=True)

    st.subheader("Upload a CSV")
    st.caption("Accepts either football-data.co.uk layout. The file goes through the same validation as "
               "downloaded data; rejected rows are listed, not repaired.")
    with st.form("upload"):
        up = st.file_uploader("CSV file", type="csv")
        league = st.selectbox("League", list(LEAGUES), format_func=lambda c: f"{c} - {LEAGUES[c].name}")
        season = st.text_input("Season (e.g. 2025/2026). Leave blank if the file has a Season column "
                               "or to derive it from match dates.")
        submitted = st.form_submit_button("Validate and load")
    if submitted and up is not None:
        with make_session_factory(engine)() as session:
            run = ingest_bytes(session, up.getvalue(), league=LEAGUES[league], source_key="csv_upload",
                               origin=up.name, today=today, season_hint=season.strip() or None,
                               raw_dir=get_settings().raw_dir)
            if run.status == "failed":
                st.error(f"Upload failed: {run.error}")
            elif run.status == "skipped_unchanged":
                st.info("This exact file has already been loaded; nothing changed.")
            else:
                st.success(f"Loaded: {run.matches_inserted} new, {run.matches_updated} updated, "
                           f"{run.matches_unchanged} unchanged, {run.rows_rejected} rejected.")
            issues = pd.read_sql("SELECT severity, code, row_number, field, message, context FROM "
                                 "validation_issues WHERE run_id = :r", engine, params={"r": run.id})
            if len(issues):
                st.dataframe(issues, width="stretch", hide_index=True)
        st.cache_data.clear()


# --------------------------------------------------------------------------- definitions

def page_definitions(today: date):
    st.header("Definitions")
    st.caption("Every figure in this dashboard is defined in one of these documents.")
    choice = st.selectbox("Document", list(DOCS))
    path = PROJECT_ROOT / "docs" / DOCS[choice]
    st.markdown(path.read_text(encoding="utf-8") if path.exists() else "_Document not found._")


PAGES = {"Fixtures and value": page_fixtures, "Model comparison": page_models, "Backtesting": page_backtest,
         "Risk and paper trading": page_risk, "Data": page_data, "Definitions": page_definitions}


def main():
    st.sidebar.title("QuantSport")
    st.sidebar.caption("Quantitative football research. Paper trading only.")
    page = st.sidebar.radio("Page", list(PAGES))
    PAGES[page](date.today())


main()
