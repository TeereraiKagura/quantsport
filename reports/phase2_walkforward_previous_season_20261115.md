# Phase 2 walk-forward evaluation

Generated 2026-11-15 23:04 UTC. Every forecast was made by a model refitted only on matches played before the match date. These are reconstructions made after the event (kind `walk_forward`), not live predictions, and say nothing yet about betting profit: no stakes, prices or costs are involved.

## Pooled across leagues

Lower log loss and Brier are better. `ll_minus_ref` is the model's mean log loss minus the reference's on the same matches; the 95% interval is a paired bootstrap over matches. A match is scored only if every model produced a forecast for it, so early-season matches and newly promoted teams are excluded. Over/Under 2.5 excludes Switzerland and Norway, where no closing price exists to compare with.

| market | model | n_matches | log_loss | brier | reference | ll_minus_ref | ci95_low | ci95_high | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1X2 | market_close | 1356 | 0.9751 | 0.5803 | market_close | 0.0 | 0.0 | 0.0 | reference |
| 1X2 | dixon_coles | 1356 | 1.008 | 0.6 | market_close | 0.033 | 0.0183 | 0.0474 | worse than reference |
| 1X2 | poisson | 1356 | 1.0048 | 0.5987 | market_close | 0.0297 | 0.0163 | 0.0431 | worse than reference |
| 1X2 | bayesian | 1356 | 1.0228 | 0.6122 | market_close | 0.0478 | 0.035 | 0.0605 | worse than reference |
| 1X2 | logistic | 1356 | 1.0387 | 0.6215 | market_close | 0.0636 | 0.043 | 0.0828 | worse than reference |
| 1X2 | base_rate | 1356 | 1.0762 | 0.6512 | market_close | 0.1011 | 0.0808 | 0.12 | worse than reference |
| BTTS | dixon_coles | 1356 | 0.686 | 0.2462 | base_rate | 0.0113 | -0.0003 | 0.023 | not distinguishable |
| BTTS | poisson | 1356 | 0.6876 | 0.2469 | base_rate | 0.0128 | 0.0009 | 0.0248 | worse than reference |
| BTTS | bayesian | 1356 | 0.6828 | 0.2448 | base_rate | 0.008 | -0.002 | 0.0184 | not distinguishable |
| BTTS | logistic | 1356 | 0.6886 | 0.2473 | base_rate | 0.0138 | 0.0059 | 0.0222 | worse than reference |
| BTTS | base_rate | 1356 | 0.6748 | 0.2409 | base_rate | 0.0 | 0.0 | 0.0 | reference |
| OU2.5 | market_close | 1167 | 0.6731 | 0.2403 | market_close | 0.0 | 0.0 | 0.0 | reference |
| OU2.5 | dixon_coles | 1167 | 0.7004 | 0.2529 | market_close | 0.0273 | 0.0149 | 0.0398 | worse than reference |
| OU2.5 | poisson | 1167 | 0.6989 | 0.2523 | market_close | 0.0258 | 0.0138 | 0.038 | worse than reference |
| OU2.5 | bayesian | 1167 | 0.6982 | 0.252 | market_close | 0.0251 | 0.0121 | 0.0379 | worse than reference |
| OU2.5 | logistic | 1167 | 0.6938 | 0.2498 | market_close | 0.0207 | 0.0093 | 0.0325 | worse than reference |
| OU2.5 | base_rate | 1167 | 0.6865 | 0.2467 | market_close | 0.0134 | 0.0036 | 0.0227 | worse than reference |

## Log loss by league

Samples per league are small; differences here are not individually tested.

| league | season | market | finished_matches | scored_matches | market_close | dixon_coles | poisson | bayesian | logistic | base_rate |
|---|---|---|---|---|---|---|---|---|---|---|
| E0 | 2025/2026 | 1X2 | 380 | 230 | 1.0377 | 1.0682 | 1.0741 | 1.0837 | 1.0915 | 1.1091 |
| E0 | 2025/2026 | BTTS | 380 | 230 | n/a | 0.6942 | 0.6975 | 0.7015 | 0.6965 | 0.6843 |
| E0 | 2025/2026 | OU2.5 | 380 | 230 | 0.6859 | 0.7279 | 0.7252 | 0.7281 | 0.6992 | 0.6925 |
| SP1 | 2025/2026 | 1X2 | 380 | 229 | 0.9726 | 1.0128 | 1.0052 | 1.0026 | 1.0137 | 1.0424 |
| SP1 | 2025/2026 | BTTS | 380 | 229 | n/a | 0.6981 | 0.7038 | 0.6999 | 0.6954 | 0.6814 |
| SP1 | 2025/2026 | OU2.5 | 380 | 229 | 0.6905 | 0.7095 | 0.709 | 0.6886 | 0.7037 | 0.6967 |
| D1 | 2025/2026 | 1X2 | 306 | 161 | 0.9682 | 0.9903 | 0.9918 | 1.0102 | 0.9944 | 1.0849 |
| D1 | 2025/2026 | BTTS | 306 | 161 | n/a | 0.6747 | 0.671 | 0.654 | 0.6703 | 0.6507 |
| D1 | 2025/2026 | OU2.5 | 306 | 161 | 0.6254 | 0.6514 | 0.6474 | 0.6522 | 0.6606 | 0.6572 |
| I1 | 2025/2026 | 1X2 | 380 | 230 | 0.9578 | 0.9937 | 0.991 | 1.0161 | 1.0147 | 1.0868 |
| I1 | 2025/2026 | BTTS | 380 | 230 | n/a | 0.705 | 0.7026 | 0.6971 | 0.7045 | 0.6885 |
| I1 | 2025/2026 | OU2.5 | 380 | 230 | 0.7082 | 0.7227 | 0.7207 | 0.7129 | 0.7078 | 0.694 |
| N1 | 2025/2026 | 1X2 | 306 | 159 | 1.0078 | 1.0261 | 1.0135 | 1.0384 | 1.0659 | 1.0938 |
| N1 | 2025/2026 | BTTS | 306 | 159 | n/a | 0.6532 | 0.6495 | 0.6515 | 0.6578 | 0.6553 |
| N1 | 2025/2026 | OU2.5 | 306 | 159 | 0.6512 | 0.6631 | 0.6608 | 0.6872 | 0.6791 | 0.6745 |
| T1 | 2025/2026 | 1X2 | 306 | 158 | 0.9596 | 1.0264 | 1.0201 | 1.0465 | 1.0566 | 1.0711 |
| T1 | 2025/2026 | BTTS | 306 | 158 | n/a | 0.6997 | 0.7102 | 0.6904 | 0.686 | 0.6906 |
| T1 | 2025/2026 | OU2.5 | 306 | 158 | 0.6487 | 0.7023 | 0.7048 | 0.7052 | 0.7001 | 0.6937 |
| SWZ | 2025/2026 | 1X2 | 228 | 94 | 0.9597 | 0.961 | 0.9621 | 0.9894 | 1.0958 | 1.0727 |
| SWZ | 2025/2026 | BTTS | 228 | 94 | n/a | 0.6467 | 0.648 | 0.6624 | 0.7145 | 0.6513 |
| SWZ | 2025/2026 | OU2.5 | 228 | 94 | n/a | 0.6131 | 0.6136 | 0.6312 | 0.6405 | 0.6286 |
| NOR | 2025 | 1X2 | 240 | 95 | 0.8688 | 0.9011 | 0.8935 | 0.9296 | 0.9723 | 1.0193 |
| NOR | 2025 | BTTS | 240 | 95 | n/a | 0.6818 | 0.6812 | 0.6703 | 0.6757 | 0.6725 |
| NOR | 2025 | OU2.5 | 240 | 95 | n/a | 0.6354 | 0.6342 | 0.6371 | 0.6561 | 0.636 |
