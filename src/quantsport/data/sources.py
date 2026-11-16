"""Data-provider access. Only documented download links and APIs are used."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date

import requests
import truststore

# Verify TLS against the operating system's certificate store. The provider's
# server omits an intermediate certificate, which the bundled CA list alone
# cannot resolve; the OS store can. Verification stays fully enabled.
truststore.inject_into_ssl()

from quantsport.config import Settings
from quantsport.data.leagues import LeagueDef, seasons_in_scope

log = logging.getLogger(__name__)

FOOTBALL_DATA_BASE = "https://www.football-data.co.uk"
USER_AGENT = "QuantSport-research/0.1"


class SourceNotConfigured(RuntimeError):
    """Raised when a provider needs credentials that have not been supplied."""


@dataclass(frozen=True)
class RemoteFile:
    url: str
    season_hint: str | None  # season label for single-season files
    allowed_seasons: set[str] | None  # filter for multi-season files


def football_data_files(league: LeagueDef, today: date, seasons_back: int = 1) -> list[RemoteFile]:
    """Download links covering the current season and `seasons_back` before it."""
    seasons = seasons_in_scope(league, today, seasons_back)
    if league.layout == "extra":
        return [RemoteFile(f"{FOOTBALL_DATA_BASE}/new/{league.code}.csv", None, set(seasons))]
    files = []
    for label in seasons:
        start = int(label[:4])
        code = f"{start % 100:02d}{(start + 1) % 100:02d}"
        files.append(RemoteFile(f"{FOOTBALL_DATA_BASE}/mmz4281/{code}/{league.code}.csv", label, None))
    return files


def football_data_fixtures_url() -> str:
    """Upcoming fixtures (with current prices) for the main-layout leagues."""
    return f"{FOOTBALL_DATA_BASE}/fixtures.csv"


def fetch(url: str, settings: Settings) -> bytes:
    """GET with exponential backoff on network errors, 429 and 5xx responses."""
    last_error: Exception | None = None
    for attempt in range(settings.http_max_retries):
        if attempt:
            time.sleep(min(2**attempt, 30))
        try:
            resp = requests.get(url, timeout=settings.http_timeout, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as exc:
            last_error = exc
            log.warning("Fetch failed (%s), attempt %d: %s", url, attempt + 1, exc)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                time.sleep(min(int(retry_after), 60))
            last_error = RuntimeError(f"HTTP {resp.status_code}")
            log.warning("Fetch got HTTP %d (%s), attempt %d", resp.status_code, url, attempt + 1)
            continue
        resp.raise_for_status()  # other 4xx: retrying will not help
        time.sleep(settings.request_delay)  # stay polite to the provider
        return resp.content
    raise RuntimeError(f"Giving up on {url}: {last_error}")


def require_oddalerts(settings: Settings) -> str:
    """OddAlerts is a paid API. Its integration is deliberately not implemented
    until a token is available and the endpoint documentation and terms can be
    read with that account; the public website is never scraped."""
    if not settings.oddalerts_token:
        raise SourceNotConfigured(
            "OddAlerts needs ODDALERTS_API_TOKEN (Advanced plan or API day pass)."
        )
    raise NotImplementedError("OddAlerts client is planned; see docs/DATA_SOURCES.md.")
