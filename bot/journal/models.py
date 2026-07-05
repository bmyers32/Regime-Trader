"""
SQLAlchemy 2.x journal models shared between bot and dashboard.
Uses DeclarativeBase so Flask-SQLAlchemy can import this Base without
depending on Flask — bot writes via plain sessionmaker, dashboard via Flask-SQLAlchemy.
All timestamps are UTC. JSON columns use SQLAlchemy's built-in JSON type.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BotHeartbeat(Base):
    """One row per bot cycle. Dashboard uses latest row age as run-status indicator."""

    __tablename__ = "bot_heartbeat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    active_pairs: Mapped[dict] = mapped_column(JSON, nullable=False)    # list of instrument strings
    cycle_ms: Mapped[int] = mapped_column(Integer, nullable=False)      # wall-clock ms for cycle
    flags_seen: Mapped[dict] = mapped_column(JSON, nullable=False)      # snapshot of ControlFlag values
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegimeSnapshot(Base):
    """One row per instrument per bot cycle."""

    __tablename__ = "regime_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    regime: Mapped[str] = mapped_column(String(32), nullable=False)     # RegimeState enum value
    bars_in_regime: Mapped[int] = mapped_column(Integer, nullable=False)
    candles_fresh: Mapped[bool] = mapped_column(Boolean, nullable=False)


class SignalLog(Base):
    """
    Every strategy evaluation — both fired signals and near-misses.
    Near-misses (score below threshold) are written with fired=False and vetoes populated.
    This is the 'why no trade' source of truth.
    """

    __tablename__ = "signal_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)   # "long" | "short"
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    fired: Mapped[bool] = mapped_column(Boolean, nullable=False)
    vetoes: Mapped[dict] = mapped_column(JSON, nullable=False)          # list of veto reason strings
    indicator_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)  # raw indicator values at eval time


class Order(Base):
    """
    Every order submitted to OANDA, including rejections.
    Rejections must be journaled loudly (TRADING-RULES §1.3).
    """

    __tablename__ = "order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    signal_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("signal_log.id"), nullable=True)
    units: Mapped[float] = mapped_column(Float, nullable=False)
    entry: Mapped[float] = mapped_column(Float, nullable=False)
    sl: Mapped[float] = mapped_column(Float, nullable=False)
    tp: Mapped[float | None] = mapped_column(Float, nullable=True)      # nullable — trend playbook trails
    oanda_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)     # "filled" | "rejected" | "cancelled"
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    spread_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)


class Trade(Base):
    """Filled order lifecycle: open → close with PnL."""

    __tablename__ = "trade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("order.id"), nullable=False)
    oanda_trade_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    open_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_px: Mapped[float] = mapped_column(Float, nullable=False)
    exit_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    units: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)        # account currency
    pnl_r: Mapped[float | None] = mapped_column(Float, nullable=True)      # R-multiple (pnl / initial risk)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "sl" | "tp" | "trail" | "manual"
    regime_at_entry: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EquitySnapshot(Base):
    """Periodic account snapshot for equity sparkline and daily PnL."""

    __tablename__ = "equity_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=False)           # net asset value (balance + open PnL)
    open_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    margin_used: Mapped[float] = mapped_column(Float, nullable=False)


class BacktestRun(Base):
    """
    Queued and completed backtest runs.
    Dashboard writes a row with status='queued'; bot worker updates to 'running'/'complete'/'error'.
    metrics JSON includes per-regime attribution (TRADING-RULES §5.5).
    """

    __tablename__ = "backtest_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requested_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False)          # instrument, strategy, date range, etc.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # populated on completion
    equity_curve_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class ControlFlag(Base):
    """
    Key/value control plane written by dashboard, read by bot each cycle.
    Keys: trading_paused, kill_switch.
    Dashboard writes ONLY to this table and InstrumentControl — never to trading tables.
    """

    __tablename__ = "control_flag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("key", name="uq_control_flag_key"),)


class InstrumentControl(Base):
    """
    Per-pair enable/disable written by dashboard, read by bot each cycle.
    Enabling a pair not in instruments.yaml → bot refuses + journals the attempt.
    Disabling → no new entries; open positions managed to completion.
    """

    __tablename__ = "instrument_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_positions_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("instrument", name="uq_instrument_control_instrument"),)
