# HANDOFF — 2026-07-04T21:30Z
Phase: 1 — Scaffold   Status: COMPLETE

Done this session:
- requirements.txt: 29 packages pinned, Python 3.13.5; numpy 2.4.6 (2.5.1 blocked by freshness gate — released same day)
- .env.example committed with 7 keys; .env gitignored and not tracked
- config.py: loads .env via python-dotenv, OANDA_ENVIRONMENT enforced == "practice" at import time, loads instruments.yaml
- bot/journal/models.py: all 9 journal models using SQLAlchemy 2.x DeclarativeBase (no Flask dependency in bot layer)
- dashboard/app/__init__.py: Flask factory, Flask-SQLAlchemy with shared Base, Flask-Migrate, WAL pragma via engine event, sqlite:/// resolved to absolute path to survive Alembic's CWD ambiguity
- dashboard/run.py: local dev entrypoint
- bot/config/instruments.yaml: 6 pairs (GBP_JPY, EUR_USD, USD_JPY, GBP_USD, AUD_USD, EUR_GBP), all disabled/uncalibrated
- migrations/: init + initial schema migration applied; all 9 tables created
- tests/test_scaffold.py: 5/5 exit criteria tests passing
- Committed: 91855d5

Not done / next action:
- Phase 2: data layer — complete-candle fetch, cache, incremental update, precision registry
- Kickoff: load CLAUDE.md, TRADING-RULES.md, HANDOFF.md, PROMPTS.md §4 row for Phase 2

Open tensions:
- sqlite:/// relative URL in .env works but only because create_app() resolves it to absolute; if a future process uses DATABASE_URL directly without going through create_app() it will fail. Bot's journal writer (Phase 4) must use the same resolution logic or an absolute URL.
- Dashboard auth (Flask-Login) is init'd but no User model or login routes exist yet — Phase 9 work. The login_manager is wired but has no user_loader; unauthenticated route protection deferred.

Files touched:
- requirements.txt, .env.example, config.py
- bot/__init__.py, bot/config/__init__.py, bot/config/instruments.yaml
- bot/journal/__init__.py, bot/journal/models.py
- dashboard/__init__.py, dashboard/app/__init__.py, dashboard/run.py
- migrations/ (full directory)
- tests/__init__.py, tests/test_scaffold.py

Do NOT redo:
- Do not re-run flask db init (migrations/ already exists)
- Do not change journal model column names without a new migration
- Do not add packages without checking freshness gate (pip index versions <pkg> + PyPI JSON API date check)
