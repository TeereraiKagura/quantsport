# Data sources and licensing

## Collection policy

Changed by the project owner on 16 November 2026. The original rule was "Do
not scrape websites in violation of their terms". It no longer applies: this
is a personal research project, nothing is sold, and collected data is not
redistributed (raw files and the database are git-ignored).

What still holds, whatever a site's terms say:

- **No bypassing of access controls.** A site that answers with a bot check,
  a CAPTCHA, a login wall or a paywall is not collected from.
- **No paid content without paying for it.**
- **Polite collection.** One request per file or feed per run, a pause
  between requests, unchanged files not re-processed.
- **Provenance is unchanged.** Every row still traces to a source and an
  ingestion run, and nothing is estimated or typed in.

Sites tested on 16 November 2026 with a plain request:

| Site | Wanted for | Result |
|---|---|---|
| fixturedownload.com | fixtures | works; now in use (below) |
| understat.com | xG history | offline ("We will come back soon"); retry later |
| fbref.com | xG, statistics | bot check; not collected |
| worldfootball.net | fixtures for Switzerland, Norway | bot check; not collected |
| sofascore.com API | lineups, statistics | refused (HTTP 403); not collected |

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

### openfootball/football.json (fixtures only)

- **What:** public-domain (CC0) season schedules on GitHub, one JSON file per
  league and season. Used only for upcoming fixtures: who plays whom, and
  when. No odds, no statistics.
- **Why:** football-data.co.uk publishes fixtures only a few days ahead, and
  not at all during international breaks.
- **Coverage:** Premier League, La Liga, Bundesliga, Serie A, Eredivisie.
  **Not** the Turkish, Swiss or Norwegian leagues.
- **Team names** differ from the stored ones. They are matched on spelling and
  then verified against the schedule: a mapping is kept only if that team's
  already-played fixtures in the file line up with stored results. Teams that
  cannot be verified are left unmapped and their fixtures skipped.
- **Dates can be provisional.** The files are pre-season schedules and are not
  always updated when matches move for television. Each load reports how
  often the file's date matched the real one on matches already played; on
  16 November 2026 that was 100% for the Bundesliga, Serie A and Eredivisie,
  94% for the Premier League and 85% for La Liga. La Liga fixtures had no
  kick-off times at all.
- A fixture loaded from here keeps its identity when football-data.co.uk later
  supplies the real date, the prices and the result.

```
python -m quantsport ingest-openfootball --days-ahead 8
python -m quantsport predict-upcoming
python -m quantsport upcoming
```

### fixturedownload.com (fixtures only)

- **What:** one JSON feed per league and season with kick-off times in UTC,
  kept up to date as matches are rescheduled and played. Used only for
  upcoming fixtures. No odds, no statistics.
- **Coverage:** Premier League, La Liga, Bundesliga, Serie A, Eredivisie and
  the Turkish Super Lig. **Not** Switzerland or Norway.
- **Terms:** the site publishes these feeds for download; its terms page says
  nothing either way about collection by program. Collected under the policy
  above, one request per league per run.
- **Team names** go through the same spelling-then-schedule verification as
  the openfootball files.
- **Date quality:** on 16 November 2026 the feed's date matched the real one
  on every already-played match in all six leagues (617 matches). The first
  load corrected the date or time of 20 fixtures that had come from the
  openfootball files and added 9 Turkish fixtures. In the daily job it runs
  first, and openfootball is only a fallback for a league this feed failed
  to load.

```
python -m quantsport ingest-fixturedownload --days-ahead 8
```

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
- The data pages need a paid plan, so nothing is collected from the website
  (see the collection policy). The source is registered but disabled
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

### Understat

Permitted under the collection policy above, but the site was offline on
16 November 2026. It is the candidate source for xG history in the Premier
League, La Liga, Bundesliga and Serie A.
