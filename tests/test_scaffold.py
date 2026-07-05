"""Phase 1 exit-criteria tests (PROMPTS.md §4 row 1)."""

import sqlite3
from pathlib import Path

import pytest

import config as cfg
from dashboard.app import create_app


EXPECTED_TABLES = {
    "bot_heartbeat",
    "regime_snapshot",
    "signal_log",
    "order",
    "trade",
    "equity_snapshot",
    "backtest_run",
    "control_flag",
    "instrument_control",
}


@pytest.fixture(scope="module")
def app():
    return create_app()


def test_oanda_environment_is_practice():
    assert cfg.OANDA_ENVIRONMENT == "practice", (
        "Prime Directive 2: OANDA_ENVIRONMENT must be 'practice' until Phase 11 gate"
    )


def test_all_tables_exist(app):
    with app.app_context():
        from dashboard.app import db
        engine = db.engine
        with engine.connect() as conn:
            result = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'alembic_%'"
            )
            tables = {row[0] for row in result}
    assert tables == EXPECTED_TABLES, (
        f"Missing tables: {EXPECTED_TABLES - tables} | Extra: {tables - EXPECTED_TABLES}"
    )


def test_wal_mode(app):
    with app.app_context():
        from dashboard.app import db
        engine = db.engine
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA journal_mode")
            mode = result.fetchone()[0]
    assert mode == "wal", f"Expected WAL mode, got: {mode}"


def test_instruments_yaml_has_all_pairs():
    expected = {"GBP_JPY", "EUR_USD", "USD_JPY", "GBP_USD", "AUD_USD", "EUR_GBP"}
    assert set(cfg.INSTRUMENTS.keys()) == expected


def test_all_instruments_disabled_by_default():
    for instrument, conf in cfg.INSTRUMENTS.items():
        assert conf.get("enabled") is False, (
            f"{instrument} must be disabled until calibrated (TRADING-RULES §4.9)"
        )
