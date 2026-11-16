"""Database backups."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from quantsport.config import Settings
from quantsport.db.models import utcnow

KEEP = 14


def backup_database(settings: Settings, keep: int = KEEP) -> Path:
    """Copy the SQLite database to data/backups using SQLite's online backup
    API (safe while the database is in use), keeping the newest `keep` copies.

    For PostgreSQL this raises: use pg_dump from the server's own tooling.
    """
    url = settings.database_url
    if not url.startswith("sqlite:///") or ":memory:" in url:
        raise RuntimeError("Automatic backup supports file-based SQLite only; use pg_dump for PostgreSQL.")
    source = Path(url.removeprefix("sqlite:///"))
    if not source.exists():
        raise FileNotFoundError(source)
    folder = source.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{source.stem}_{utcnow():%Y%m%d_%H%M%S}.db"
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    for old in sorted(folder.glob(f"{source.stem}_*.db"))[:-keep]:
        old.unlink()
    return target
