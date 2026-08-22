"""
==========================================================
ALEMBIC ENVIRONMENT
PHASE 11.3
==========================================================

WHERE THE DATABASE URL COMES FROM
----------------------------------------------------------
DATABASE_URL, the same environment variable the application
reads. Not alembic.ini, which is committed and must never
hold a password, and not a second setting that could point
somewhere other than where the code is talking.

WHERE THE SCHEMA COMES FROM
----------------------------------------------------------
database.models.Base.metadata. Importing the models module
is what registers every table on it, so the import below is
load-bearing rather than incidental -- without it,
autogenerate would confidently report that every table
should be dropped.

WHAT AUTOGENERATE CANNOT SEE
----------------------------------------------------------
Read every generated migration before applying it.
Autogenerate compares tables, columns, indexes and
constraints. It does not reliably detect:

  - a table or column RENAME, which it reports as a drop and
    an add: applied, that deletes the data
  - a server-side default change
  - a CHECK constraint it was not told to compare
  - anything created outside the ORM metadata

compare_type is on so a column type change is noticed, and
compare_server_default is on so a default change is at least
proposed. Neither makes the output safe to apply unread.
"""

import os
import sys

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool


PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[1]
)


if str(
    PROJECT_ROOT
) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


from dotenv import load_dotenv  # noqa: E402

# Explicit path: alembic may be invoked from anywhere, and
# find_dotenv() searches upward from the CALLER, which is not
# reliably the project root.
load_dotenv(
    PROJECT_ROOT
    / ".env"
)


# Registers every table on Base.metadata. Do not remove: with
# the models unimported, the metadata is empty and
# autogenerate proposes dropping the entire schema.
from database.models import Base  # noqa: E402,F401


config = context.config


if config.config_file_name is not None:

    fileConfig(
        config.config_file_name,
        disable_existing_loggers=False,
    )


target_metadata = Base.metadata


def database_url() -> str:

    url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if not url:

        raise RuntimeError(
            "DATABASE_URL is not set. Alembic reads the same "
            "variable the application does, so a migration "
            "cannot be applied to a database the code is not "
            "configured for. Set it in the environment or in "
            ".env."
        )

    return url


def run_migrations_offline() -> None:

    """
    Emit SQL to stdout instead of connecting.

        alembic upgrade head --sql

    Useful when a DBA applies the change, or for reviewing
    exactly what a migration will do before it does it.
    """

    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:

    """
    Connect and apply.

    NullPool: a migration run is one short-lived connection,
    and a pool would only add connections nobody uses.

    One transaction around the whole run, so a migration that
    fails halfway leaves the schema as it was rather than
    half-changed. PostgreSQL supports transactional DDL, which
    is what makes that possible.
    """

    section = config.get_section(
        config.config_ini_section,
        {},
    )

    section["sqlalchemy.url"] = database_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            transaction_per_migration=False,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()

else:
    run_migrations_online()
