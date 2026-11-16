# Phase 2 walk-forward evaluation

Generated 2026-11-15 22:51 UTC. Every forecast was made by a model refitted only on matches played before the match date. These are reconstructions made after the event (kind `walk_forward`), not live predictions, and say nothing yet about betting profit: no stakes, prices or costs are involved.

## Pooled across leagues

Lower log loss and Brier are better. `ll_minus_ref` is the model's mean log loss minus the reference's on the same matches; the 95% interval is a paired bootstrap over matches. A match is scored only if every model produced a forecast for it, so early-season matches and newly promoted teams are excluded. Over/Under 2.5 excludes Switzerland and Norway, where no closing price exists to compare with.

| market | model | n_matches | log_loss | brier | reference | ll_minus_ref | ci95_low | ci95_high | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1X2 | market_close | 801 | 0.9462 | 0.5587 | market_close | 0.0 | 0.0 | 0.0 | reference |
| 1X2 | dixon_coles | 801 | 0.9733 | 0.5757 | market_close | 0.0271 | 0.0113 | 0.0439 | worse than reference |
| 1X2 | poisson | 801 | 0.9703 | 0.5746 | market_close | 0.0241 | 0.0092 | 0.0393 | worse than reference |
| 1X2 | bayesian | 801 | 0.9793 | 0.5814 | market_close | 0.0331 | 0.0178 | 0.0493 | worse than reference |
| 1X2 | logistic | 801 | 1.0139 | 0.6049 | market_close | 0.0677 | 0.0458 | 0.0907 | worse than reference |
| 1X2 | base_rate | 801 | 1.0594 | 0.6408 | market_close | 0.1132 | 0.087 | 0.1395 | worse than reference |
| BTTS | dixon_coles | 801 | 0.6749 | 0.2408 | base_rate | -0.0015 | -0.0155 | 0.0131 | not distinguishable |
| BTTS | poisson | 801 | 0.672 | 0.2396 | base_rate | -0.0044 | -0.0177 | 0.0092 | not distinguishable |
| BTTS | bayesian | 801 | 0.671 | 0.2391 | base_rate | -0.0053 | -0.0169 | 0.0066 | not distinguishable |
| BTTS | logistic | 801 | 0.6829 | 0.2446 | base_rate | 0.0065 | -0.0039 | 0.0168 | not distinguishable |
| BTTS | base_rate | 801 | 0.6764 | 0.2417 | base_rate | 0.0 | 0.0 | 0.0 | reference |
| OU2.5 | market_close | 532 | 0.6426 | 0.2258 | market_close | 0.0 | 0.0 | 0.0 | reference |
| OU2.5 | dixon_coles | 532 | 0.6665 | 0.237 | market_close | 0.0239 | 0.0041 | 0.0437 | worse than reference |
| OU2.5 | poisson | 532 | 0.6663 | 0.2371 | market_close | 0.0237 | 0.0051 | 0.0427 | worse than reference |
| OU2.5 | bayesian | 532 | 0.6715 | 0.2395 | market_close | 0.0289 | 0.011 | 0.0473 | worse than reference |
| OU2.5 | logistic | 532 | 0.6688 | 0.238 | market_close | 0.0262 | 0.0114 | 0.0411 | worse than reference |
| OU2.5 | base_rate | 532 | 0.6717 | 0.2395 | market_close | 0.0291 | 0.014 | 0.0441 | worse than reference |

## Log loss by league

Samples per league are small; differences here are not individually tested.

| league | season | market | finished_matches | scored_matches | market_close | dixon_coles | poisson | bayesian | logistic | base_rate |
|---|---|---|---|---|---|---|---|---|---|---|
| E0 | 2026/2027 | 1X2 | 100 | 86 | 1.0086 | 1.0475 | 1.0434 | 1.0585 | 1.0943 | 1.0905 |
| E0 | 2026/2027 | BTTS | 100 | 86 | n/a | 0.708 | 0.6932 | 0.6893 | 0.7032 | 0.6969 |
| E0 | 2026/2027 | OU2.5 | 100 | 86 | 0.6896 | 0.6861 | 0.6803 | 0.6712 | 0.7177 | 0.7034 |
| SP1 | 2026/2027 | 1X2 | 119 | 105 | 0.8899 | 0.9321 | 0.9316 | 0.9717 | 0.9764 | 1.0838 |
| SP1 | 2026/2027 | BTTS | 119 | 105 | n/a | 0.7035 | 0.6972 | 0.6998 | 0.6906 | 0.6935 |
| SP1 | 2026/2027 | OU2.5 | 119 | 105 | 0.6333 | 0.6654 | 0.6573 | 0.6779 | 0.6815 | 0.6924 |
| D1 | 2026/2027 | 1X2 | 81 | 67 | 0.9522 | 0.9361 | 0.9339 | 0.9218 | 1.0485 | 1.0329 |
| D1 | 2026/2027 | BTTS | 81 | 67 | n/a | 0.6324 | 0.632 | 0.6409 | 0.6766 | 0.6547 |
| D1 | 2026/2027 | OU2.5 | 81 | 67 | 0.5656 | 0.5646 | 0.5661 | 0.5756 | 0.6026 | 0.5999 |
| I1 | 2026/2027 | 1X2 | 110 | 96 | 0.8879 | 0.9016 | 0.8978 | 0.9055 | 0.9101 | 1.049 |
| I1 | 2026/2027 | BTTS | 110 | 96 | n/a | 0.6983 | 0.6958 | 0.7016 | 0.7203 | 0.7065 |
| I1 | 2026/2027 | OU2.5 | 110 | 96 | 0.6752 | 0.7441 | 0.7476 | 0.7407 | 0.6971 | 0.7069 |
| N1 | 2026/2027 | 1X2 | 108 | 93 | 1.0179 | 1.0508 | 1.0574 | 1.0592 | 1.0891 | 1.1081 |
| N1 | 2026/2027 | BTTS | 108 | 93 | n/a | 0.6377 | 0.6411 | 0.6337 | 0.6191 | 0.6278 |
| N1 | 2026/2027 | OU2.5 | 108 | 93 | 0.6181 | 0.645 | 0.65 | 0.6488 | 0.6317 | 0.6227 |
| T1 | 2026/2027 | 1X2 | 99 | 85 | 0.9104 | 0.9568 | 0.9384 | 0.9362 | 1.0267 | 1.0597 |
| T1 | 2026/2027 | BTTS | 99 | 85 | n/a | 0.7087 | 0.7094 | 0.6977 | 0.6935 | 0.7018 |
| T1 | 2026/2027 | OU2.5 | 99 | 85 | 0.6572 | 0.664 | 0.6682 | 0.6862 | 0.6645 | 0.6847 |
| SWZ | 2026/2027 | 1X2 | 78 | 73 | 1.0158 | 1.0347 | 1.0418 | 1.0566 | 1.09 | 1.0739 |
| SWZ | 2026/2027 | BTTS | 78 | 73 | n/a | 0.6215 | 0.6209 | 0.6375 | 0.6671 | 0.6448 |
| SWZ | 2026/2027 | OU2.5 | 78 | 73 | n/a | 0.6088 | 0.6096 | 0.6107 | 0.6212 | 0.5931 |
| NOR | 2026 | 1X2 | 208 | 196 | 0.931 | 0.9584 | 0.9529 | 0.9566 | 0.9681 | 1.0182 |
| NOR | 2026 | BTTS | 208 | 196 | n/a | 0.671 | 0.6687 | 0.6617 | 0.6854 | 0.6747 |
| NOR | 2026 | OU2.5 | 208 | 196 | n/a | 0.6484 | 0.6477 | 0.6479 | 0.6487 | 0.6491 |
