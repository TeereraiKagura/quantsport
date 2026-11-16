"""Engine/session helpers and reference-data seeding."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from quantsport.data.leagues import DATA_SOURCES, LEAGUES
from quantsport.db.models import Base, DataSource, League


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create tables and seed leagues and data sources. Safe to re-run."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        known_sources = set(session.scalars(select(DataSource.key)))
        for src in DATA_SOURCES.values():
            if src.key not in known_sources:
                session.add(
                    DataSource(key=src.key, name=src.name, url=src.url, license_note=src.license_note)
                )
        known_leagues = set(session.scalars(select(League.code)))
        for lg in LEAGUES.values():
            if lg.code not in known_leagues:
                session.add(
                    League(code=lg.code, name=lg.name, country=lg.country, season_type=lg.season_type)
                )
        session.commit()
