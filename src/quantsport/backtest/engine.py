"""Historical betting simulation on stored walk-forward forecasts.

What a simulated bettor knows when a bet is chosen:
  - the model's forecast, which was fitted only on matches before that day;
  - the pre-closing price at the chosen bookmaker (or the best individual
    bookmaker price), which was published before kick-off.
The result and the closing price are attached only for settlement and for
closing line value. They never enter bet selection or stake sizing.

Rules:
  - A selection is bet when EV = p * price - 1 exceeds `min_ev` and the price
    lies within [min_odds, max_odds].
  - At most one bet per match and market: the selection with the highest EV.
  - Bets are processed day by day. Stakes for a day are sized from the
    bankroll at the start of that day; results are settled at the end of it.
  - Forecasts with no usable price are skipped and counted, never filled in.

Staking:
  flat    - stake = stake_pct * initial bankroll, every bet
  percent - stake = stake_pct * current bankroll
  kelly   - stake = kelly_fraction * (p*o - 1)/(o - 1) * current bankroll,
            capped at max_stake_pct of the current bankroll

Settlement: a win returns stake * (o - 1) * (1 - commission); a loss costs the
stake. `commission` models exchange commission or other proportional costs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from quantsport.data.leagues import LEAGUES, season_label, season_start_year
from quantsport.market import compare

MATCH_SQL = """
SELECT m.id AS match_id, l.code AS league, m.season, m.match_date, m.home_goals, m.away_goals,
       h.name AS home, a.name AS away
FROM matches m
JOIN leagues l ON l.id = m.league_id
JOIN teams h ON h.id = m.home_team_id
JOIN teams a ON a.id = m.away_team_id
WHERE m.status = 'finished'
"""


@dataclass(frozen=True)
class BacktestConfig:
    model: str = "dixon_coles"
    market: str = "OU"
    line: float = 2.5
    seasons_ago: int = 0  # 0 = current season (final test), 1 = previous (validation)
    leagues: tuple[str, ...] | None = None
    min_ev: float = 0.05
    min_odds: float = 1.0
    max_odds: float = 1000.0
    price_source: str = "Bet365"  # a bookmaker name, or "best" across individual bookmakers
    staking: str = "flat"
    stake_pct: float = 0.01
    kelly_fraction: float = 0.25
    max_stake_pct: float = 0.05
    initial_bankroll: float = 1000.0
    commission: float = 0.0

    def describe(self) -> dict:
        return asdict(self)


def split_season(league_code: str, today, seasons_ago: int) -> str:
    league = LEAGUES[league_code]
    return season_label(league.season_type, season_start_year(league.season_type, today) - seasons_ago)


def _won(market: str, line: float, selection: str, hg: pd.Series, ag: pd.Series) -> pd.Series:
    if market == "OU":
        over = hg + ag > line
        return over if selection == "over" else ~over
    if market == "BTTS":
        both = (hg > 0) & (ag > 0)
        return both if selection == "yes" else ~both
    if market == "1X2":
        return {"H": hg > ag, "D": hg == ag, "A": hg < ag}[selection]
    raise ValueError(f"Unknown market '{market}'")


def load_data(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(finished matches, stored walk-forward forecasts, odds quotes)."""
    return (pd.read_sql(MATCH_SQL, engine, parse_dates=["match_date"]),
            compare.load_predictions(engine, "walk_forward"), compare.load_quotes(engine))


def candidates(engine: Engine, cfg: BacktestConfig, today, data=None) -> tuple[pd.DataFrame, dict]:
    """Every forecast selection for the configured model, market and split,
    with its price (NaN if none) and outcome. Also returns coverage counts."""
    matches, preds, quotes = data or load_data(engine)
    leagues = list(cfg.leagues) if cfg.leagues else list(LEAGUES)
    wanted = pd.Series({code: split_season(code, today, cfg.seasons_ago) for code in leagues})
    matches = matches[matches.league.isin(leagues) & (matches.season == matches.league.map(wanted))]

    if preds.empty:
        return pd.DataFrame(), {"finished_matches": len(matches), "with_forecast": 0, "with_price": 0}
    preds = preds[(preds.model == cfg.model) & (preds.market == cfg.market) & (preds.line == cfg.line)]
    df = preds[["match_id", "market", "line", "selection", "probability"]].merge(matches, on="match_id")

    quotes = quotes[quotes.league.isin(leagues)]
    key = compare.SELECTION_KEY
    if cfg.price_source == "best":
        prices = compare.best_prices(quotes, "pre_close")[key + ["best_price", "best_bookmaker"]].rename(
            columns={"best_price": "price", "best_bookmaker": "bookmaker"})
    else:
        q = quotes[(quotes.bookmaker == cfg.price_source) & (quotes.snapshot_type == "pre_close")]
        prices = q[key + ["price", "bookmaker"]]
    df = df.merge(prices, on=key, how="left")
    closing = compare.consensus(quotes, "closing")[key + ["fair_prob"]].rename(
        columns={"fair_prob": "closing_fair_prob"})
    df = df.merge(closing, on=key, how="left")

    df["won"] = False
    for selection, idx in df.groupby("selection").groups.items():
        rows = df.loc[idx]
        df.loc[idx, "won"] = _won(cfg.market, cfg.line, selection, rows.home_goals, rows.away_goals)
    coverage = {
        "finished_matches": len(matches),
        "with_forecast": int(df.match_id.nunique()),
        "with_price": int(df.dropna(subset=["price"]).match_id.nunique()),
    }
    return df, coverage


def select_bets(cands: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Apply the entry rule. Uses only the forecast and the pre-match price."""
    c = cands.dropna(subset=["price"]).copy()
    c["ev"] = c.probability * c.price - 1.0
    c = c[(c.ev > cfg.min_ev) & (c.price >= cfg.min_odds) & (c.price <= cfg.max_odds)]
    if c.empty:
        return c
    c = c.loc[c.groupby("match_id").ev.idxmax()]
    return c.sort_values(["match_date", "match_id"]).reset_index(drop=True)


def simulate(bets: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Stake and settle the bets in date order. Returns the bet ledger."""
    bankroll = cfg.initial_bankroll
    rows = []
    for _, day in bets.groupby("match_date", sort=True):
        if bankroll <= 0:
            break  # ruined: no further bets can be placed
        if cfg.staking == "flat":
            stakes = np.full(len(day), cfg.stake_pct * cfg.initial_bankroll)
        elif cfg.staking == "percent":
            stakes = np.full(len(day), cfg.stake_pct * bankroll)
        elif cfg.staking == "kelly":
            full = (day.probability * day.price - 1.0) / (day.price - 1.0)
            stakes = np.minimum(cfg.kelly_fraction * full, cfg.max_stake_pct).to_numpy() * bankroll
        else:
            raise ValueError(f"Unknown staking '{cfg.staking}'")
        total = stakes.sum()
        if total > bankroll:  # cannot stake more than is held
            stakes = stakes * bankroll / total
        profit = np.where(day.won, stakes * (day.price - 1.0) * (1.0 - cfg.commission), -stakes)
        bankroll_before = bankroll
        bankroll += profit.sum()
        rows.append(day.assign(stake=stakes, profit=profit, bankroll_before=bankroll_before,
                               bankroll_after=bankroll))
    if not rows:
        return bets.assign(stake=[], profit=[], bankroll_before=[], bankroll_after=[])
    ledger = pd.concat(rows, ignore_index=True)
    ledger["clv"] = ledger.price * ledger.closing_fair_prob - 1.0
    return ledger


def roi_interval(ledger: pd.DataFrame, n_boot: int = 5000, seed: int = 12345) -> tuple[float, float]:
    """95% bootstrap interval for ROI, resampling whole matches."""
    per = ledger.groupby("match_id")[["profit", "stake"]].sum().to_numpy()
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(per), size=(n_boot, len(per)))
    roi = per[draws, 0].sum(axis=1) / per[draws, 1].sum(axis=1)
    lo, hi = np.percentile(roi, [2.5, 97.5])
    return float(lo), float(hi)


def max_drawdown(ledger: pd.DataFrame, initial: float) -> float:
    """Largest peak-to-trough fall of the end-of-day bankroll, as a fraction of the peak."""
    equity = np.r_[initial, ledger.groupby("match_date", sort=True).bankroll_after.last().to_numpy()]
    peak = np.maximum.accumulate(equity)
    return float(((peak - equity) / peak).max())


def summarize(ledger: pd.DataFrame, cfg: BacktestConfig, min_bets_for_interval: int = 30) -> dict:
    n = len(ledger)
    out = {"bets": n, "wins": 0, "losses": 0, "staked": 0.0, "profit": 0.0, "roi_pct": None,
           "roi_ci95_low": None, "roi_ci95_high": None, "win_rate_pct": None, "mean_odds": None,
           "mean_ev_pct": None, "mean_clv_pct": None, "clv_bets": 0, "max_drawdown_pct": None,
           "final_bankroll": cfg.initial_bankroll, "verdict": "no bets"}
    if n == 0:
        return out
    staked, profit = ledger.stake.sum(), ledger.profit.sum()
    clv = ledger.clv.dropna()
    out.update(
        wins=int(ledger.won.sum()), losses=int((~ledger.won).sum()), staked=round(staked, 2),
        profit=round(profit, 2), roi_pct=round(100 * profit / staked, 2),
        win_rate_pct=round(100 * ledger.won.mean(), 1), mean_odds=round(ledger.price.mean(), 3),
        mean_ev_pct=round(100 * ledger.ev.mean(), 2),
        mean_clv_pct=round(100 * clv.mean(), 2) if len(clv) else None, clv_bets=len(clv),
        max_drawdown_pct=round(100 * max_drawdown(ledger, cfg.initial_bankroll), 2),
        final_bankroll=round(ledger.bankroll_after.iloc[-1], 2),
    )
    if n < min_bets_for_interval:
        out["verdict"] = f"insufficient sample (<{min_bets_for_interval} bets)"
        return out
    lo, hi = roi_interval(ledger)
    out.update(roi_ci95_low=round(100 * lo, 2), roi_ci95_high=round(100 * hi, 2))
    out["verdict"] = ("profitable beyond chance" if lo > 0 else
                      "losing beyond chance" if hi < 0 else "not distinguishable from break-even")
    return out


def run(engine: Engine, cfg: BacktestConfig, today, data=None) -> tuple[dict, pd.DataFrame, dict]:
    """Full backtest: (summary, ledger, coverage)."""
    cands, coverage = candidates(engine, cfg, today, data)
    if cands.empty:
        return {**summarize(pd.DataFrame(), cfg), "skipped_after_ruin": 0}, pd.DataFrame(), coverage
    selected = select_bets(cands, cfg)
    ledger = simulate(selected, cfg)
    summary = summarize(ledger, cfg)
    summary["skipped_after_ruin"] = len(selected) - len(ledger)
    return summary, ledger, coverage
