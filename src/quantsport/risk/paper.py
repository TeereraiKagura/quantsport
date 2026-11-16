"""Paper-trading portfolios: hypothetical bets recorded before kick-off.

Paper results are a third ledger, separate from backtests and walk-forward
evaluation. A paper bet is created only from a live forecast (stored before
kick-off) and a pre-match price, and is refused once the match has started.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from quantsport.backtest.engine import _won
from quantsport.db.models import Match, PaperBet, Portfolio
from quantsport.market import compare
from quantsport.market.pricing import executability
from quantsport.risk import monitoring
from quantsport.risk.staking import RiskConfig, apply_limits, combined_sigma, drawdown_multiplier, propose, stake_base

DEFAULT_MODELS = {"OU": "ml_random_forest", "1X2": "poisson"}  # Phase 5 gate result
DEFAULT_SETTINGS = {"models": DEFAULT_MODELS, "min_ev": 0.05, "model_error": 0.06}


def create(session: Session, name: str, bankroll: float, cfg: RiskConfig | None = None,
           settings: dict | None = None) -> Portfolio:
    config = {"risk": (cfg or RiskConfig()).describe(), **DEFAULT_SETTINGS, **(settings or {})}
    portfolio = Portfolio(name=name, initial_bankroll=bankroll, config_json=json.dumps(config, sort_keys=True))
    session.add(portfolio)
    session.commit()
    return portfolio


def _get(session: Session, name: str) -> tuple[Portfolio, dict, RiskConfig]:
    portfolio = session.scalars(select(Portfolio).where(Portfolio.name == name)).one()
    config = json.loads(portfolio.config_json)
    return portfolio, config, RiskConfig(**config["risk"])


def ledger(engine: Engine, portfolio_id: int) -> pd.DataFrame:
    sql = ("SELECT b.*, m.match_date FROM paper_bets b JOIN matches m ON m.id = b.match_id "
           "WHERE b.portfolio_id = :pid ORDER BY b.placed_at, b.id")
    df = pd.read_sql(sql, engine, params={"pid": portfolio_id}, parse_dates=["match_date", "placed_at"])
    if len(df):
        df["won"] = df.status == "won"
        df["price"] = df.odds
        df["clv"] = df.odds * df.closing_fair_prob - 1.0
    return df


def place(engine: Engine, session: Session, name: str, now: datetime) -> list[PaperBet]:
    """Scan live forecasts for upcoming matches and record qualifying paper bets."""
    portfolio, config, cfg = _get(session, name)
    assess = compare.value_assessments(engine, "live")
    if assess.empty:
        return []
    led = ledger(engine, portfolio.id)
    settled = led[led.status != "open"] if len(led) else led
    bankroll = portfolio.initial_bankroll + (settled.profit.sum() if len(settled) else 0.0)
    open_exposure = float(led[led.status == "open"].stake.sum()) if len(led) else 0.0
    equity = np.r_[portfolio.initial_bankroll,
                   portfolio.initial_bankroll + settled.profit.cumsum().to_numpy()] if len(settled) else [bankroll]
    peak = float(np.max(equity))

    # Disagreement between models on the same selection.
    spread = assess[assess.model != "base_rate"].groupby(compare.SELECTION_KEY).probability.std(ddof=0)
    assess = assess.merge(spread.rename("disagreement").reset_index(), on=compare.SELECTION_KEY, how="left")
    wanted = pd.Series(config["models"])
    assess = assess[(assess.status == "scheduled") & (assess.model == assess.market.map(wanted))
                    & (assess.ev > config["min_ev"])]
    already = set(zip(led.match_id, led.market, led.line)) if len(led) else set()
    assess = assess[[key not in already for key in zip(assess.match_id, assess.market, assess.line)]]
    if assess.empty:
        return []
    assess = assess.loc[assess.groupby(["match_id", "market", "line"]).ev.idxmax()].copy()
    assess["sigma"] = combined_sigma(assess.disagreement.fillna(0.0), config["model_error"])
    assess["price"] = assess.best_price

    evidence = monitoring.scaling_evidence(settled, cfg.min_bets_to_scale)["allowed"]
    base = stake_base(bankroll, portfolio.initial_bankroll, evidence)
    stakes = propose(assess, base, cfg) * drawdown_multiplier(bankroll, peak, cfg)
    stakes, _ = apply_limits(assess, stakes, base, cfg, open_exposure)

    placed = []
    for row, stake in zip(assess.itertuples(index=False), stakes):
        match = session.get(Match, row.match_id)
        started = now >= match.kickoff_utc if match.kickoff_utc else now.date() >= match.match_date
        if stake <= 1e-9 or started or match.status != "scheduled":
            continue
        observed = None if pd.isna(row.observed_at) else pd.Timestamp(row.observed_at).to_pydatetime()
        bet = PaperBet(
            portfolio_id=portfolio.id, match_id=row.match_id, model=row.model, market=row.market,
            line=row.line, selection=row.selection, probability=float(row.probability),
            sigma=float(row.sigma), odds=float(row.best_price), bookmaker=row.best_bookmaker,
            price_status=executability(False, match.status, observed, now), stake=float(stake),
            bankroll_before=bankroll, placed_at=now,
        )
        session.add(bet)
        placed.append(bet)
    session.commit()
    return placed


def settle(engine: Engine, session: Session, name: str, now: datetime) -> int:
    """Settle open paper bets whose matches have finished. Returns how many."""
    portfolio, _, _ = _get(session, name)
    closing = compare.consensus(compare.load_quotes(engine), "closing").set_index(compare.SELECTION_KEY).fair_prob
    count = 0
    open_bets = session.scalars(
        select(PaperBet).where(PaperBet.portfolio_id == portfolio.id, PaperBet.status == "open")).all()
    for bet in open_bets:
        match = session.get(Match, bet.match_id)
        if match.status != "finished":
            continue
        won = bool(_won(bet.market, bet.line, bet.selection,
                        pd.Series([match.home_goals]), pd.Series([match.away_goals])).iloc[0])
        bet.status = "won" if won else "lost"
        bet.profit = bet.stake * (bet.odds - 1.0) if won else -bet.stake
        key = (bet.match_id, bet.market, bet.line, bet.selection)
        bet.closing_fair_prob = float(closing[key]) if key in closing.index else None
        bet.settled_at = now
        count += 1
    session.commit()
    return count


def status(engine: Engine, session: Session, name: str) -> dict:
    portfolio, config, cfg = _get(session, name)
    led = ledger(engine, portfolio.id)
    out = {"portfolio": name, "kind": "paper trading (no real money)", "initial_bankroll": portfolio.initial_bankroll,
           "open_bets": 0, "open_exposure": 0.0, "settled_bets": 0, "bankroll": portfolio.initial_bankroll}
    if led.empty:
        return {**out, "note": "no paper bets recorded yet"}
    settled, open_ = led[led.status != "open"], led[led.status == "open"]
    bankroll = portfolio.initial_bankroll + settled.profit.sum()
    out.update(open_bets=int(len(open_)), open_exposure=round(float(open_.stake.sum()), 2),
               settled_bets=int(len(settled)), bankroll=round(float(bankroll), 2))
    if len(settled):
        equity = np.r_[portfolio.initial_bankroll, portfolio.initial_bankroll + settled.profit.cumsum().to_numpy()]
        dd = monitoring.drawdowns(equity)
        longest, current = monitoring.losing_streaks(settled.won)
        out.update(
            staked=round(float(settled.stake.sum()), 2), profit=round(float(settled.profit.sum()), 2),
            roi_pct=round(100 * float(settled.profit.sum() / settled.stake.sum()), 2),
            win_rate_pct=round(100 * float(settled.won.mean()), 1),
            max_drawdown_pct=round(100 * float(dd.max()), 2), current_drawdown_pct=round(100 * float(dd[-1]), 2),
            longest_losing_streak=longest, current_losing_streak=current,
            expected_longest_streak=round(
                monitoring.expected_longest_losing_streak(len(settled), settled.won.mean()), 1),
        )
    out["stake_review"] = monitoring.scaling_evidence(settled, cfg.min_bets_to_scale)
    return out
