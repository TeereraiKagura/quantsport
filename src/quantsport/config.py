"""Environment-driven configuration. Secrets only ever come from the environment."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str
    raw_dir: Path
    log_dir: Path
    reports_dir: Path
    http_timeout: float
    http_max_retries: int
    request_delay: float
    oddalerts_token: str | None


@lru_cache
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    data_dir = PROJECT_ROOT / "data"
    default_db = f"sqlite:///{(data_dir / 'quantsport.db').as_posix()}"
    return Settings(
        database_url=os.getenv("QUANTSPORT_DATABASE_URL") or default_db,
        raw_dir=data_dir / "raw",
        log_dir=PROJECT_ROOT / "logs",
        reports_dir=PROJECT_ROOT / "reports",
        http_timeout=float(os.getenv("QUANTSPORT_HTTP_TIMEOUT") or 30),
        http_max_retries=int(os.getenv("QUANTSPORT_HTTP_MAX_RETRIES") or 4),
        request_delay=float(os.getenv("QUANTSPORT_REQUEST_DELAY") or 1.0),
        oddalerts_token=os.getenv("ODDALERTS_API_TOKEN") or None,
    )


def configure_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(settings.log_dir / "quantsport.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
