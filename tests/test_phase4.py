"""Phase 4 tests. Bets and prices here are SYNTHETIC, chosen so every figure
can be checked by hand."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantsport.backtest.engine import (
    BacktestConfig, _won, max_drawdown, roi_interval, select_bets, simulate, summarize,
)

CFG = BacktestConfig(min_ev=0.0, initial_bankroll=1000.0, stake_pct=0.01)


def cands(rows):
    cols = ["match_id", "match_date", "selection", "probability", "price", "closing_fair_prob", "won"]
    df = pd.DataFrame(rows, columns=cols)
    df["match_date"] = pd.to_datetime(df.match_date)
    return df


BASE = cands([
    # match 1: over has EV +10%, under EV -24%  -> bet over, wins
    (1, "2026-09-01", "over", 0.55, 2.00, 0.52, True),
    (1, "2026-09-01", "under", 0.45, 1.70, 0.48, False),
    # match 2, same day: under EV +5%, loses
    (2, "2026-09-01", "over", 0.40, 2.20, 0.45, True),
    (2, "2026-09-01", "under", 0.60, 1.75, 0.55, False),
    # match 3: nothing positive
    (3, "2026-09-02", "over", 0.50, 1.90, 0.50, True),
    (3, "2026-09-02", "under", 0.50, 1.90, 0.50, False),
    # match 4: no price at all
    (4, "2026-09-03", "over", 0.90, np.nan, 0.50, True),
    # match 5: over EV +20%, loses
    (5, "2026-09-04", "over", 0.50, 2.40, 0.40, False),
])


def test_selection_rule_one_bet_per_match_highest_ev_and_skips_missing_prices():
    bets = select_bets(BASE, CFG)
    assert list(bets.match_id) == [1, 2, 5]
    assert list(bets.selection) == ["over", "under", "over"]
    assert bets.ev.tolist() == pytest.approx([0.10, 0.05, 0.20])
    assert list(select_bets(BASE, replace(CFG, min_ev=0.07)).match_id) == [1, 5]
    assert list(select_bets(BASE, replace(CFG, max_odds=2.1)).match_id) == [1, 2]


def test_flat_staking_ledger_and_summary_by_hand():
    ledger = simulate(select_bets(BASE, CFG), CFG)
    assert ledger.stake.tolist() == [10.0, 10.0, 10.0]
    assert ledger.profit.tolist() == pytest.approx([10.0, -10.0, -10.0])
    assert ledger.bankroll_after.tolist() == pytest.approx([1000.0, 1000.0, 990.0])  # day 1 nets to zero
    s = summarize(ledger, CFG)
    assert (s["bets"], s["wins"], s["losses"], s["staked"], s["profit"]) == (3, 1, 2, 30.0, -10.0)
    assert s["roi_pct"] == pytest.approx(-33.33)
    assert s["mean_clv_pct"] == pytest.approx(100 * np.mean([2.0 * 0.52 - 1, 1.75 * 0.55 - 1, 2.4 * 0.40 - 1]), abs=0.01)
    assert s["max_drawdown_pct"] == pytest.approx(1.0)
    assert s["verdict"].startswith("insufficient sample") and s["roi_ci95_low"] is None


def test_percent_and_kelly_stakes_use_start_of_day_bankroll():
    pct = simulate(select_bets(BASE, replace(CFG, staking="percent")), replace(CFG, staking="percent"))
    assert pct.stake.tolist() == pytest.approx([10.0, 10.0, 10.0])  # bankroll back at 1000 after day 1
    kelly_cfg = replace(CFG, staking="kelly", kelly_fraction=0.5, max_stake_pct=0.05)
    k = simulate(select_bets(BASE, kelly_cfg), kelly_cfg)
    # full Kelly: (0.55*2-1)/1 = 0.10 ; (0.6*1.75-1)/0.75 = 0.0667 ; (0.5*2.4-1)/1.4 = 0.1429
    assert k.stake.iloc[0] == pytest.approx(0.05 * 1000)            # 0.5*0.10 = 5%, at the cap
    assert k.stake.iloc[1] == pytest.approx(0.5 * 0.0666667 * 1000, rel=1e-4)
    after_day1 = 1000 + 50 * 1.0 - k.stake.iloc[1]
    assert k.bankroll_before.iloc[2] == pytest.approx(after_day1)
    assert k.stake.iloc[2] == pytest.approx(0.05 * after_day1)      # 0.5*0.1429 > cap


def test_commission_reduces_winnings_only():
    cfg = replace(CFG, commission=0.05)
    ledger = simulate(select_bets(BASE, cfg), cfg)
    assert ledger.profit.tolist() == pytest.approx([9.5, -10.0, -10.0])


def test_outcome_and_closing_price_cannot_influence_selection_or_stakes():
    """Look-ahead guard: flip every result and closing price; the bets chosen
    and the stakes sized on the first day must be identical."""
    tampered = BASE.assign(won=~BASE.won, closing_fair_prob=0.99)
    for staking in ("flat", "percent", "kelly"):
        cfg = replace(CFG, staking=staking)
        a, b = select_bets(BASE, cfg), select_bets(tampered, cfg)
        assert a[["match_id", "selection", "price", "ev"]].equals(b[["match_id", "selection", "price", "ev"]])
        la, lb = simulate(a, cfg), simulate(b, cfg)
        assert la.stake.iloc[:2].tolist() == lb.stake.iloc[:2].tolist()


def test_max_drawdown():
    ledger = pd.DataFrame({"match_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
                           "bankroll_after": [1100.0, 880.0, 990.0, 1200.0]})
    assert max_drawdown(ledger, 1000.0) == pytest.approx(0.2)  # 1100 -> 880


def test_stakes_never_exceed_bankroll():
    rows = [(i, "2026-09-01", "over", 0.9, 3.0, 0.5, False) for i in range(1, 41)]
    cfg = replace(CFG, staking="kelly", kelly_fraction=1.0, max_stake_pct=0.05)
    ledger = simulate(select_bets(cands(rows), cfg), cfg)
    assert ledger.stake.sum() == pytest.approx(1000.0)  # 40 x 5% scaled down to the bankroll
    assert ledger.bankroll_after.iloc[-1] == pytest.approx(0.0)


def test_roi_interval_and_verdict_on_a_known_edge():
    rng = np.random.default_rng(1)
    n = 2000
    won = rng.random(n) < 0.55  # true win probability 0.55 at odds 2.0: true ROI +10%
    df = cands([(i, "2026-09-01", "over", 0.55, 2.0, 0.5, bool(w)) for i, w in enumerate(won)])
    df["match_date"] = pd.Timestamp("2026-01-01") + pd.to_timedelta(np.arange(n) // 10, unit="D")
    ledger = simulate(select_bets(df, CFG), CFG)
    lo, hi = roi_interval(ledger)
    assert lo < 0.10 < hi and hi - lo < 0.12
    assert summarize(ledger, CFG)["verdict"] == "profitable beyond chance"
    fair = df.assign(won=rng.random(n) < 0.5)  # no edge
    assert summarize(simulate(select_bets(fair, CFG), CFG), CFG)["verdict"] == "not distinguishable from break-even"


def test_settlement_rules():
    hg, ag = pd.Series([2, 0, 1, 3]), pd.Series([1, 0, 1, 0])
    assert _won("OU", 2.5, "over", hg, ag).tolist() == [True, False, False, True]
    assert _won("OU", 2.5, "under", hg, ag).tolist() == [False, True, True, False]
    assert _won("1X2", 0.0, "D", hg, ag).tolist() == [False, True, True, False]
    assert _won("BTTS", 0.0, "yes", hg, ag).tolist() == [True, False, True, False]


def test_no_bets_is_reported_not_invented():
    s = summarize(simulate(select_bets(BASE, replace(CFG, min_ev=5.0)), CFG), CFG)
    assert s["bets"] == 0 and s["verdict"] == "no bets" and s["roi_pct"] is None
