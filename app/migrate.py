"""Run Alembic migrations at startup.

Early deploys created the schema via Base.metadata.create_all() (see app/db.py)
rather than Alembic, so the database has real tables but no alembic_version
row. A plain `alembic upgrade head` on such a database tries to recreate
tables that already exist and crashes. If we detect that situation — no
alembic_version table, but the schema is already there — we stamp the
database at the last revision whose schema create_all() actually produced,
then upgrade normally from that point.
"""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import PROJECT_ROOT, settings

# Last revision whose schema matches what Base.metadata.create_all() builds
# for a database that has never been touched by Alembic.
LEGACY_BASELINE_REVISION = "51e0075e25f5"
LEGACY_MARKER_TABLE = "words"


def _sqlite_file_path(database_url: str) -> str | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    return database_url[len(prefix) :]


def run_migrations() -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    db_path = _sqlite_file_path(settings.database_url)
    if db_path and Path(db_path).exists():
        conn = sqlite3.connect(db_path)
        try:
            has_alembic_version = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            has_legacy_schema = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (LEGACY_MARKER_TABLE,),
            ).fetchone()
        finally:
            conn.close()

        if not has_alembic_version and has_legacy_schema:
            print(f"Legacy pre-Alembic database detected — stamping at {LEGACY_BASELINE_REVISION}.")
            command.stamp(cfg, LEGACY_BASELINE_REVISION)

    command.upgrade(cfg, "head")


if __name__ == "__main__":
    run_migrations()
