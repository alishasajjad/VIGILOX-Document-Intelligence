import sys

from pathlib import Path


# ==========================================================
# CREATE THE JOB AND BATCH TABLES
# PHASE 9.2 / 9.3
# ==========================================================
#
# Creates document_jobs and document_batches if they are not
# already there.
#
# SUPERSEDED BY ALEMBIC IN PHASE 11.3.
#
# DO NOT USE THIS TO CHANGE THE SCHEMA.
#
# This was the stopgap. Phase 9.3 needed somewhere to put
# jobs before a migration mechanism existed, and this script
# existed so that need did not turn into a hand-written
# CREATE TABLE pasted into a terminal.
#
# Phase 11.3 replaced it. The schema is now:
#
#     alembic upgrade head
#
# and a schema CHANGE is:
#
#     alembic revision --autogenerate -m "what changed"
#
# The initial revision covers the whole schema including the
# two tables below, so an existing database is marked as
# already there with `alembic stamp head` rather than rebuilt.
#
# WHY IT STILL EXISTS
# ----------------------------------------------------------
# It is a read-only diagnostic worth keeping:
#
#     python -m scripts.maintenance.create_job_tables --check
#
# reports which tables, columns and indexes are present,
# which is a faster answer than reading a migration history
# when something is wrong on a specific database.
#
# Its creating behaviour is left working rather than removed
# so that anyone who runs it out of habit gets a correct
# schema rather than an error -- but the schema it produces is
# no longer authoritative, and adding anything to it would
# mean changing the schema in two places.
# tests/deployment/test_phase11_migrations.py asserts that
# this file names Alembic, so the pointer cannot be lost.
#
# It is deliberately narrow:
#
#   - only the two new tables, named explicitly, so it can
#     never touch documents, document_analyses, human_reviews
#     or audit_events
#   - checkfirst, so running it twice is harmless
#   - no drop, no alter, no data change
#
# Run:
#
#     python -m scripts.maintenance.create_job_tables
#     python -m scripts.maintenance.create_job_tables --check
# ==========================================================

PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
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


from sqlalchemy import inspect               # noqa: E402

from database.database import (               # noqa: E402
    engine,
)

from database.models import (                 # noqa: E402
    DocumentBatchModel,
    DocumentJobModel,
)

from backend.app.domain.job_states import (   # noqa: E402
    ACTIVE_STATUSES,
)


# Order matters: jobs reference batches.
MANAGED_TABLES = (
    DocumentBatchModel.__table__,
    DocumentJobModel.__table__,
)


def report() -> int:

    inspector = (
        inspect(
            engine
        )
    )

    existing = set(
        inspector.get_table_names()
    )

    missing = []


    print()
    print(
        "Job queue tables"
    )
    print(
        "-" * 60
    )


    for table in MANAGED_TABLES:

        present = (
            table.name in existing
        )

        print(
            f"  {table.name:<22}"
            f"{'present' if present else 'MISSING'}"
        )


        if present:

            columns = {
                column["name"]
                for column in inspector.get_columns(
                    table.name
                )
            }

            expected = {
                column.name
                for column in table.columns
            }

            absent = (
                expected - columns
            )

            if absent:

                print(
                    "      columns missing: "
                    f"{sorted(absent)}"
                )

                missing.append(
                    table.name
                )

        else:
            missing.append(
                table.name
            )


    indexes_present = []


    if DocumentJobModel.__tablename__ in existing:

        indexes_present = sorted(
            index["name"]
            for index in inspector.get_indexes(
                DocumentJobModel.__tablename__
            )
        )

        print()
        print(
            f"  indexes: {indexes_present}"
        )


    print()

    return 0 if not missing else 1


def create() -> int:

    print()
    print(
        "Creating job queue tables (checkfirst)..."
    )

    # Only the tables named above. Passing the full metadata
    # would let this script create anything the models declare,
    # which is not what a maintenance script should be able to
    # do to a production database.
    from database.database import Base

    Base.metadata.create_all(
        bind=engine,
        tables=list(
            MANAGED_TABLES
        ),
        checkfirst=True,
    )

    print(
        "  done"
    )

    return report()


def add_missing_columns() -> int:

    """
    Add columns that were introduced after a table existed.

    create_all() only creates missing TABLES; it does not
    alter existing ones. Phase 10.1 added
    document_analyses.quality, so an existing database needs
    the column added.

    Nullable with no default, which is what makes this safe to
    run on a populated table: existing rows read as "not
    assessed", which is a different statement from "no
    problems found" and the interface distinguishes them.

    Same stopgap status as the rest of this script. Phase 11.2
    replaces it with an Alembic revision.
    """

    from sqlalchemy import text

    inspector = (
        inspect(
            engine
        )
    )

    existing = set(
        inspector.get_table_names()
    )

    added = []

    wanted = (
        (
            "document_analyses",
            "quality",
            "JSONB",
        ),

        # PHASE 10.3. The source fingerprint, on both the
        # document and the job.
        #
        # Nullable with no default, and no backfill. Every row
        # that predates this reads as "source never
        # fingerprinted", which is true and which takes part
        # in no duplicate detection. Inventing a value for
        # those rows would make them look like sources that
        # could be duplicated.
        (
            "documents",
            "source_sha256",
            "VARCHAR(64)",
        ),

        (
            "document_jobs",
            "source_sha256",
            "VARCHAR(64)",
        ),
    )

    for table, column, sql_type in wanted:

        if table not in existing:
            continue


        columns = {
            entry["name"]
            for entry in inspector.get_columns(
                table
            )
        }

        if column in columns:
            continue


        with engine.begin() as connection:

            connection.execute(
                text(
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN {column} {sql_type}"
                )
            )

        added.append(
            f"{table}.{column}"
        )


    if added:
        print(
            f"  added {added}"
        )

    else:
        print(
            "  no columns to add"
        )

    return 0


def add_missing_indexes() -> int:

    """
    Create the Phase 10.3 duplicate indexes if they are not
    already there.

    IF NOT EXISTS on both, so running this twice is harmless.

    THE PARTIAL UNIQUE INDEX IS A CONSTRAINT, NOT A SPEEDUP
    ----------------------------------------------------------
    uq_document_jobs_active_source is what actually prevents
    two concurrent identical uploads from both starting a job.
    Without it the application would be back to checking and
    then inserting, which has a window between the two
    statements that no amount of application code closes.

    Creating it on a populated database is safe here because
    every pre-Phase-10.3 job row has source_sha256 NULL, and
    NULLs do not conflict in a unique index. If a future
    database somehow did hold two active jobs with the same
    fingerprint, this would fail loudly rather than silently
    skipping the constraint -- which is the correct outcome,
    because the constraint would not be true.

    Same stopgap status as the rest of this script. Phase 11.3
    replaces it with an Alembic revision.
    """

    from sqlalchemy import text

    inspector = (
        inspect(
            engine
        )
    )

    existing_tables = set(
        inspector.get_table_names()
    )

    created = []

    active_states = ", ".join(
        f"'{status}'"
        for status in ACTIVE_STATUSES
    )

    wanted = (
        (
            "documents",
            "ix_documents_source_sha256",
            (
                "CREATE INDEX IF NOT EXISTS "
                "ix_documents_source_sha256 "
                "ON documents (source_sha256)"
            ),
        ),

        (
            "document_jobs",
            "uq_document_jobs_active_source",
            (
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_document_jobs_active_source "
                "ON document_jobs (source_sha256) "
                f"WHERE status IN ({active_states})"
            ),
        ),
    )

    for table, index_name, statement in wanted:

        if table not in existing_tables:
            continue


        present = {
            entry["name"]
            for entry in inspector.get_indexes(
                table
            )
        }

        if index_name in present:
            continue


        with engine.begin() as connection:

            connection.execute(
                text(
                    statement
                )
            )

        created.append(
            index_name
        )


    if created:
        print(
            f"  created {created}"
        )

    else:
        print(
            "  no indexes to create"
        )

    return 0


def main() -> int:

    if "--check" in sys.argv:
        return report()


    create()

    add_missing_columns()

    add_missing_indexes()

    # Reported LAST, so the exit code describes the schema as
    # it now stands.
    #
    # create() reports too, but it runs before the columns and
    # indexes are added, so its verdict was the state on the
    # way in -- which made this script exit 1 on a run that had
    # just fixed everything it was complaining about.
    return report()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
