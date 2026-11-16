# Data sources and licensing

## In use

### football-data.co.uk

- **What:** CSV downloads of results, match statistics and bookmaker odds.
- **How accessed:** the site's published download links only
  (`/mmz4281/<season>/<div>.csv`, `/new/<code>.csv`, `/fixtures.csv`). No page
  scraping. One request per file, a one-second pause between requests, and a
  file whose bytes have not changed is not re-processed.
- **Licence:** the site states no explicit licence; the files are offered free
  for download and analysis. QuantSport treats them as personal research data:
  raw files and the database are git-ignored and are not redistributed.
- **Times:** kick-off times are UK local time and are converted to UTC.

What the provider actually supplies, measured on 16 November 2026
(see `reports/` for the current figures):

| Data | EPL, La Liga, Bundesliga, Serie A, Eredivisie, Super Lig | Swiss Super League, Eliteserien |
|---|---|---|
| Results, kick-off time | yes | yes |
| Half-time score, shots, shots on target, corners, fouls, cards | yes | **no** |
| xG | 2026/27 only; **not** 2025/26 | **no** |
| Possession | **no** | **no** |
| 1X2 odds, closing | yes | yes |
| 1X2 odds, pre-closing | yes | **no** |
| Over/Under 2.5 odds (pre-closing and closing) | yes | **no** |
| Upcoming fixtures file | yes (empty for these leagues during international breaks) | **no** |

Consequences that later phases must respect:

- Over/Under 2.5 cannot be priced or backtested for Switzerland and Norway with
  this source. Models can still produce probabilities there, but no expected
  value can be claimed.
- "Pre-closing" odds are collected by the provider some days before kick-off.
  They are **not** true opening prices and carry no timestamp, so
  `observed_at` is NULL. Opening-to-close movement is therefore approximate.
- "Market maximum" and "Market average" are aggregates, flagged
  `is_aggregate`. They are not prices available at one bookmaker and are never
  treated as executable.
- Betfair Exchange pre-closing prices are sometimes illiquid; the validator
  flagged 108 such price sets with an implausible booksum.

### CSV upload

`python -m quantsport ingest-csv <file> --league <code> [--season 2025/2026]`
accepts either football-data.co.uk layout and runs the same validation.
Licensing of uploaded data is the uploader's responsibility.

## Not yet connected

### OddAlerts (oddalerts.com)

- The public site describes a paid REST API (fixtures, stats, odds,
  predictions) on the Advanced plan or an API day pass. The API page refused
  automated access (HTTP 403), so endpoint details and usage terms could not be
  read.
- QuantSport does not scrape the website. The source is registered but disabled
  until `ODDALERTS_API_TOKEN` is set, and the client will be written against
  the documentation available to that account, after its terms on storage and
  reuse are checked.
- If connected, it is the candidate source for the gaps above: xG history,
  Over/Under odds for Switzerland and Norway, timestamped odds movement and
  fixtures.
- Feature ideas noted from its public pages for later phases: value-bet
  screens comparing model probability with odds, dropping-odds and Pinnacle
  line-movement views, match simulation, and filterable alerts.

### Player availability and lineups

No licensed source is connected. The tables exist and are empty. No model may
assume anything about injuries, suspensions or lineups until a source with
acceptable terms is added.

### Understat and similar

Not used: there is no official API and access would mean scraping.
