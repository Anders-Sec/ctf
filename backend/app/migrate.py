"""Run Alembic migrations under a Postgres advisory lock.

The backend runs more than one replica, and every pod runs migrations at
startup. Without a lock they race `alembic upgrade head` and either deadlock on
the same DDL or both try to create the same table.

An advisory lock is the right tool: it is held on a Postgres session rather than
a row, it is released automatically if the pod dies mid-migration, and the
losing pod simply waits and then finds there is nothing to do.
"""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.logging import configure_logging, get_logger

logger = get_logger(__name__)

#: Arbitrary but fixed. Any other process taking this same id is, by
#: definition, another copy of this migration runner.
MIGRATION_LOCK_ID = 4_919_170_001

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings.sync_database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            logger.info("migration_waiting_for_lock")
            connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
            try:
                logger.info("migration_started")
                config = Config(str(BACKEND_ROOT / "alembic.ini"))
                config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
                config.set_main_option("sqlalchemy.url", settings.sync_database_url)
                command.upgrade(config, "head")
                logger.info("migration_complete")
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID}
                )
    except Exception:
        # Loud and non-zero: the entrypoint must not start a server against a
        # database it failed to migrate.
        logger.exception("migration_failed")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
