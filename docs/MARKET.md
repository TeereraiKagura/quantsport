# Market intelligence (Phase 3)

Code: `src/quantsport/market/`. `pricing.py` holds the formulas, `compare.py`
applies them to stored odds and forecasts, `report.py` writes the report.
Nothing here is stored: every figure is recomputed from the stored quotes and
the insert-only forecasts, so results are reproducible.

## Definitions

With decimal odds `o` and model probability `p`:

| Quantity | Definition |
|---|---|
| Implied probability | `q = 1 / o` |
| Booksum | `B = sum of q` over all outcomes of one bookmaker's market |
| Overround (margin) | `B - 1` |
| Fair probability, proportional | `f_i = q_i / B` (default) |
| Fair probability, power | `f_i = q_i^k`, `k` chosen so the `f_i` sum to 1 |
| Expected value | `EV = p * o - 1`, profit per unit staked if `p` is right |
| Edge | `p - f`, model minus market in probability |
| Closing line value | `CLV = o_taken * f_close - 1`, the bet valued by the closing market's fair probability |
| Price CLV | `o_taken / o_close - 1` |
| Best price | highest price among individual bookmakers for a selection |
| Cross-book booksum | booksum using the best price on each outcome |
| Movement | closing consensus fair probability minus pre-closing |

- **Consensus** means the provider's market-average odds with the margin
  removed proportionally. Proportional removal tends to leave long shots
  slightly overestimated; the power method is available as an alternative.
- Only **complete sets** (every outcome priced by the same bookmaker at the
  same snapshot) are used for margins and fair probabilities.
- **Aggregates** ("Market maximum", "Market average") are never eligible as a
  best price.
- The **betting exchange** is excluded from best prices by default: its quotes
  are before commission, and the data contains illiquid, implausible exchange
  prices.

## Theoretical versus executable

Every price carries a status from `pricing.executability`:

| Status | Meaning |
|---|---|
| `aggregate` | not a price at any single bookmaker |
| `historical` | the match is no longer upcoming |
| `indicative` | pre-match, but no collection time or a stale one |
| `current` | pre-match and observed within 15 minutes |

Only `current` may be called an executable opportunity, and stake limits and
account restrictions are still not modelled. The present data source supplies
no collection times, so nothing in the system can reach `current` yet: all
expected value shown is theoretical.

## Commands

```
python -m quantsport market-report
python -m quantsport value --kind walk_forward --min-ev 0.05 --min-odds 1.5
python -m quantsport value            # live forecasts for upcoming matches
```

## How to read the value screen

A model that says "EV +20%" is only right if the market later moves toward
it. The screen therefore reports the CLV of the selections a model flags,
next to the CLV of taking the best price on every selection. If the two are
alike, the model's "value" is its own error. The `base_rate` model, which
knows nothing about teams, is included as a control: any CLV improvement it
also shows comes from which prices get selected, not from forecasting skill.

## Limitations

- Pre-closing prices are not opening prices and have no timestamps, so odds
  movement is approximate and best prices across bookmakers may never have
  been available at the same moment.
- Over/Under 2.5 has at most two individual bookmakers (one in 2026/27), so
  "best price" there is nearly a single book.
- No pre-closing prices for Switzerland and Norway; no BTTS prices anywhere.
- CLV uses the closing market average as the reference, not a sharp
  bookmaker; Pinnacle prices are absent from the 2026/27 files.
