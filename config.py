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

# --- External data (TRADING-RULES §6 slot 2, carry hearing) ---
# Historical policy-rate signal source, scripts/fetch_policy_rates.py -- the project's
# first non-OANDA data dependency. Free key: fredaccount.stlouisfed.org/apikeys.
# Optional (unlike OANDA/DB/dashboard secrets above): only scripts/fetch_policy_rates.py
# needs it, not the bot/dashboard/test suite -- hard-requiring it here would break every
# unrelated import of this module for anyone who hasn't fetched rates yet. That script
# validates its own presence and fails loudly there instead.
FRED_API_KEY: str | None = os.environ.get("FRED_API_KEY")

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
ACCOUNT_CURRENCY: str = _raw.get("account_currency", "USD")
