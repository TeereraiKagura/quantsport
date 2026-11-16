"""Phase 1 database schema (Module A: data engine).

All timestamps are stored as naive datetimes in UTC.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class DataSource(Base):
    """Where a piece of data came from (source attribution)."""

    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500))
    license_note: Mapped[str | None] = mapped_column(Text)


class League(Base):
    __tablename__ = "leagues"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(100))
    season_type: Mapped[str] = mapped_column(String(10))  # "split" (Aug-May) or "calendar"


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("name", "country"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(100))


class TeamAlias(Base):
    """Maps a provider's team spelling onto the canonical team."""

    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("source_id", "alias", "team_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    alias: Mapped[str] = mapped_column(String(100))


class IngestionRun(Base):
    """One attempt to load one file. The audit trail for every stored row."""

    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id"))
    origin: Mapped[str] = mapped_column(String(500))  # URL or uploaded file name
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    # running | success | skipped_unchanged | failed
    status: Mapped[str] = mapped_column(String(20), default="running")
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    raw_path: Mapped[str | None] = mapped_column(String(500))
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_out_of_scope: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    matches_inserted: Mapped[int] = mapped_column(Integer, default=0)
    matches_updated: Mapped[int] = mapped_column(Integer, default=0)
    matches_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("league_id", "home_team_id", "away_team_id", "match_date"),
        Index("ix_matches_league_season", "league_id", "season"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    season: Mapped[str] = mapped_column(String(9))  # "2025/2026" or "2026"
    match_date: Mapped[date] = mapped_column(Date)
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime)  # NULL = time unknown
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    # finished | scheduled | awaiting_result
    status: Mapped[str] = mapped_column(String(20))
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    ht_home_goals: Mapped[int | None] = mapped_column(Integer)
    ht_away_goals: Mapped[int | None] = mapped_column(Integer)
    referee: Mapped[str | None] = mapped_column(String(100))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    first_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))
    last_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))
    payload_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MatchStats(Base):
    """Team match statistics. NULL always means 'not provided by the source'."""

    __tablename__ = "match_stats"
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    home_shots: Mapped[int | None] = mapped_column(Integer)
    away_shots: Mapped[int | None] = mapped_column(Integer)
    home_sot: Mapped[int | None] = mapped_column(Integer)
    away_sot: Mapped[int | None] = mapped_column(Integer)
    home_corners: Mapped[int | None] = mapped_column(Integer)
    away_corners: Mapped[int | None] = mapped_column(Integer)
    home_fouls: Mapped[int | None] = mapped_column(Integer)
    away_fouls: Mapped[int | None] = mapped_column(Integer)
    home_yellow: Mapped[int | None] = mapped_column(Integer)
    away_yellow: Mapped[int | None] = mapped_column(Integer)
    home_red: Mapped[int | None] = mapped_column(Integer)
    away_red: Mapped[int | None] = mapped_column(Integer)
    home_xg: Mapped[float | None] = mapped_column(Float)
    away_xg: Mapped[float | None] = mapped_column(Float)
    home_possession: Mapped[float | None] = mapped_column(Float)
    away_possession: Mapped[float | None] = mapped_column(Float)


class OddsQuote(Base):
    """One bookmaker price for one selection at one snapshot.

    market "1X2": selections H/D/A, line 0.0.
    market "OU":  selections over/under, line e.g. 2.5.
    snapshot_type "pre_close" (collected days before kick-off) or "closing".
    observed_at is NULL when the provider gives no collection timestamp.
    """

    __tablename__ = "odds_quotes"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "bookmaker", "market", "line", "selection", "snapshot_type"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker: Mapped[str] = mapped_column(String(40))
    is_aggregate: Mapped[bool] = mapped_column(Boolean, default=False)  # market max/avg
    market: Mapped[str] = mapped_column(String(10))
    line: Mapped[float] = mapped_column(Float, default=0.0)
    selection: Mapped[str] = mapped_column(String(10))
    snapshot_type: Mapped[str] = mapped_column(String(12))
    price: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)


class MatchVersion(Base):
    """Append-only history: the full normalised record at every version."""

    __tablename__ = "match_versions"
    __table_args__ = (UniqueConstraint("match_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ValidationIssue(Base):
    __tablename__ = "validation_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # error (row rejected) | warning | info
    code: Mapped[str] = mapped_column(String(50))
    row_number: Mapped[int | None] = mapped_column(Integer)  # 1-based CSV line incl. header
    field: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)


class ModelVersion(Base):
    """A model fitted on one league's data up to a cut-off date."""

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "league_id", "params_hash", "data_cutoff"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    params_json: Mapped[str] = mapped_column(Text)
    params_hash: Mapped[str] = mapped_column(String(64))  # parameters + code version
    data_cutoff: Mapped[date] = mapped_column(Date)  # trained on matches before this date
    n_train: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Prediction(Base):
    """One model's forecast for one match. Insert-only: never updated or deleted.

    kind "live"         - written before kick-off (enforced on insert).
    kind "walk_forward" - reconstructed afterwards using only data from before
                          the match date. Never to be presented as live.
    """

    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("match_id", "model_version_id", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    kind: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    exp_home_goals: Mapped[float | None] = mapped_column(Float)
    exp_away_goals: Mapped[float | None] = mapped_column(Float)


class PredictionProb(Base):
    __tablename__ = "prediction_probs"
    __table_args__ = (UniqueConstraint("prediction_id", "market", "line", "selection"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    market: Mapped[str] = mapped_column(String(10))
    line: Mapped[float] = mapped_column(Float, default=0.0)
    selection: Mapped[str] = mapped_column(String(10))
    probability: Mapped[float] = mapped_column(Float)


class ImmutableRecordError(RuntimeError):
    pass


def _refuse_change(mapper, connection, target):
    raise ImmutableRecordError(f"{type(target).__name__} rows are insert-only")


for _cls in (ModelVersion, Prediction, PredictionProb, MatchVersion):
    event.listen(_cls, "before_update", _refuse_change)
    event.listen(_cls, "before_delete", _refuse_change)


class Portfolio(Base):
    """A paper-trading portfolio. No real money is involved anywhere."""

    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    initial_bankroll: Mapped[float] = mapped_column(Float)
    config_json: Mapped[str] = mapped_column(Text)  # risk settings and model choice
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaperBet(Base):
    """A hypothetical bet recorded before kick-off. The entry fields are
    written once; only the settlement fields change afterwards."""

    __tablename__ = "paper_bets"
    __table_args__ = (UniqueConstraint("portfolio_id", "match_id", "market", "line"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    model: Mapped[str] = mapped_column(String(40))
    market: Mapped[str] = mapped_column(String(10))
    line: Mapped[float] = mapped_column(Float, default=0.0)
    selection: Mapped[str] = mapped_column(String(10))
    probability: Mapped[float] = mapped_column(Float)
    sigma: Mapped[float] = mapped_column(Float)
    odds: Mapped[float] = mapped_column(Float)
    bookmaker: Mapped[str] = mapped_column(String(40))
    price_status: Mapped[str] = mapped_column(String(12))  # indicative | current
    stake: Mapped[float] = mapped_column(Float)
    bankroll_before: Mapped[float] = mapped_column(Float)
    placed_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | won | lost
    profit: Mapped[float | None] = mapped_column(Float)
    closing_fair_prob: Mapped[float | None] = mapped_column(Float)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)


class JobRun(Base):
    """One step of a scheduled job: what ran, when, and whether it worked."""

    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(20))  # daily | weekly
    step: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10))  # ok | failed
    detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime] = mapped_column(DateTime)


class PlayerAvailability(Base):
    """Injuries and suspensions. No licensed source is connected yet, so this
    table is empty; nothing may be assumed about player availability."""

    __tablename__ = "player_availability"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # injured | suspended | doubtful
    reason: Mapped[str | None] = mapped_column(String(200))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime)


class LineupEntry(Base):
    """Starting lineups. Empty until a licensed source is connected."""

    __tablename__ = "lineup_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_name: Mapped[str] = mapped_column(String(100))
    is_starter: Mapped[bool] = mapped_column(Boolean)
    position: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
