"""Run Alembic migrations at startup.

Early deploys created the schema via Base.metadata.create_all() (see app/db.py)
rather than Alembic, so the database has real tables but no alembic_version
row. A plain `alembic upgrade head` on such a database tries to recreate
tables that already exist and fails with "table ... already exists". When
that happens, we stamp the database at the last revision whose schema
create_all() actually produced, then retry the upgrade from that point.
"""

from alembic import command
from alembic.config import Config

from app.config import PROJECT_ROOT, settings

# Last revision whose schema matches what Base.metadata.create_all() builds
# for a database that has never been touched by Alembic.
LEGACY_BASELINE_REVISION = "51e0075e25f5"


def run_migrations() -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - reacting to a specific SQLite message, see below
        if "already exists" not in str(exc):
            raise
        print(
            f"Migration failed with '{exc}' — looks like a legacy pre-Alembic "
            f"database. Stamping at {LEGACY_BASELINE_REVISION} and retrying."
        )
        command.stamp(cfg, LEGACY_BASELINE_REVISION)
        command.upgrade(cfg, "head")


if __name__ == "__main__":
    run_migrations()
