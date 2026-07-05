"""
Central config loader. Reads .env via python-dotenv; loads instruments.yaml.
Import this module; never read os.environ directly elsewhere.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# --- Broker ---
OANDA_ACCOUNT_ID: str = os.environ["OANDA_ACCOUNT_ID"]
OANDA_ACCESS_TOKEN: str = os.environ["OANDA_ACCESS_TOKEN"]
OANDA_ENVIRONMENT: str = os.environ["OANDA_ENVIRONMENT"]

# Prime Directive 2: practice only until Phase 11 config flag + validation report.
if OANDA_ENVIRONMENT != "practice":
    raise RuntimeError(
        f"OANDA_ENVIRONMENT='{OANDA_ENVIRONMENT}' — only 'practice' is permitted "
        "until the Phase 11 live gate is explicitly passed."
    )

# --- Database ---
DATABASE_URL: str = os.environ["DATABASE_URL"]

# --- Dashboard auth ---
FLASK_SECRET_KEY: str = os.environ["FLASK_SECRET_KEY"]
DASHBOARD_USER: str = os.environ["DASHBOARD_USER"]
DASHBOARD_PASSWORD: str = os.environ["DASHBOARD_PASSWORD"]

# --- Instruments ---
_INSTRUMENTS_PATH = Path(__file__).parent / "bot" / "config" / "instruments.yaml"

with open(_INSTRUMENTS_PATH) as _f:
    _raw = yaml.safe_load(_f)

INSTRUMENT_DEFAULTS: dict = _raw.get("defaults", {})
INSTRUMENTS: dict = _raw.get("instruments", {})
