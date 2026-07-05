"""
Flask application factory for the Regime Trader dashboard.
Flask-SQLAlchemy uses the shared DeclarativeBase from bot.journal.models
so Flask-Migrate sees all tables without the bot depending on Flask.
WAL mode is set on every new SQLite connection via SQLAlchemy event.
"""

import sqlite3
from pathlib import Path

from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

from bot.journal.models import Base

db = SQLAlchemy(model_class=Base)
migrate = Migrate()
login_manager = LoginManager()


@event.listens_for(Engine, "connect")
def _set_wal_mode(dbapi_connection, _record):
    """Enable WAL mode on every new SQLite connection (TRADING-RULES §stack)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)

    # instance/ lives at repo root — same location both processes use
    instance_path = Path(__file__).parent.parent.parent / "instance"
    instance_path.mkdir(exist_ok=True)

    import config as cfg

    app.config["SECRET_KEY"] = cfg.FLASK_SECRET_KEY

    # Resolve relative sqlite:/// URLs to absolute so Alembic env.py always finds the file
    # regardless of working directory.
    db_url = cfg.DATABASE_URL
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////"):
        rel = db_url[len("sqlite:///"):]
        abs_path = (Path(__file__).parent.parent.parent / rel).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{abs_path}"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}}
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Import all models so Alembic autogenerate detects them
    import bot.journal.models  # noqa: F401

    return app
