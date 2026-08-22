"""
==========================================================
PHASE 11.3 - SCHEMA MIGRATIONS
==========================================================

WHAT REPLACED WHAT
----------------------------------------------------------
The schema was built by
scripts/maintenance/create_job_tables.py: a create_all()
plus a list of hand-written ALTER statements, run by hand.
That got the project from Phase 6 to Phase 10 and cannot be
what ships. It has no version, no ordering, no record of what
has been applied to a given database, and no way back.

Alembic replaces it. This suite is what makes the
replacement trustworthy.


WHAT THIS SUITE IS PROTECTING

  1. THE MIGRATION REPRODUCES THE MODELS.
     Applied to an empty database, autogenerating again must
     produce NOTHING. A migration that is merely close to
     database/models.py is a migration that will fail on
     somebody's fresh deployment.

  2. THE MODELS HAVE NOT DRIFTED AHEAD OF THE MIGRATIONS.
     A column added to a model with no migration written
     works perfectly on every developer machine that already
     has the column, and breaks the first fresh deployment.
     `alembic check` catches exactly that.

  3. THE CONSTRAINTS ARE REAL IN POSTGRESQL, NOT JUST IN
     PYTHON.
     Two constraints carry release-critical behaviour:

       uq_document_jobs_active_source
           the PARTIAL unique index that makes duplicate
           detection race-free. Phase 10.3 chose database
           enforcement over check-then-insert precisely
           because six simultaneous uploads of the same bytes
           cannot all lose a check-then-insert race.

       uq_human_reviews_document_id
           closes the duplicate-review hole Phase 7C found in
           concurrent submission.

     Both are tested by trying to VIOLATE them. An index
     asserted to exist in pg_indexes proves it was created;
     an insert that PostgreSQL refuses proves it works.

  4. NO CREDENTIALS IN THE COMMITTED CONFIGURATION.


WHY A THROWAWAY DATABASE
----------------------------------------------------------
Testing migrations means running `downgrade base`, which
drops every table. Doing that to the working database would
destroy real stored documents and every review decision.

So each run creates its own database and drops it again. If
the connected role cannot create databases, this suite
reports that it could not run rather than pretending to pass
-- and rather than falling back to the real database, which
is the one thing it must never touch.
"""

import os
import re
import subprocess
import sys

from pathlib import Path


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


from dotenv import load_dotenv  # noqa: E402

load_dotenv(
    PROJECT_ROOT
    / ".env"
)

import sqlalchemy as sa  # noqa: E402

import uuid  # noqa: E402

from sqlalchemy.orm import sessionmaker  # noqa: E402

from database.models import (  # noqa: E402
    Base,
    DocumentJobModel,
    DocumentModel,
)


SCRATCH_DATABASE = "vigilox_migration_test"


# ==========================================================
# ASSERTIONS
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
) -> None:

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected!r}\n"
            f"Actual:   {actual!r}"
        )


def assert_true(
    value,
    message: str,
) -> None:

    if not value:
        raise AssertionError(
            message
        )


def section(
    title: str,
) -> None:

    print()
    print(
        "-" * 74
    )
    print(
        title
    )
    print(
        "-" * 74
    )


def ok(
    message: str,
) -> None:

    print(
        f"[PASS] {message}"
    )


# ==========================================================
# THE THROWAWAY DATABASE
# ==========================================================

def real_url() -> str:

    url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if not url:

        raise AssertionError(
            "DATABASE_URL is not set, so there is no server "
            "to create a test database on."
        )

    return url


def scratch_url() -> str:

    return (
        real_url().rsplit(
            "/",
            1,
        )[0]
        + f"/{SCRATCH_DATABASE}"
    )


def admin_engine():

    return sa.create_engine(
        real_url().rsplit(
            "/",
            1,
        )[0]
        + "/postgres",
        isolation_level="AUTOCOMMIT",
    )


def can_create_databases() -> bool:

    try:
        with admin_engine().connect() as connection:

            return bool(
                connection.execute(
                    sa.text(
                        "select rolcreatedb or rolsuper "
                        "from pg_roles "
                        "where rolname = current_user"
                    )
                ).scalar()
            )

    except Exception:
        return False


def reset_scratch() -> None:

    """
    Drop and recreate, so a previous interrupted run cannot
    leave a half-migrated database that makes this one pass
    or fail for the wrong reason.
    """

    with admin_engine().connect() as connection:

        # Anything still connected would block the drop.
        connection.execute(
            sa.text(
                "select pg_terminate_backend(pid) "
                "from pg_stat_activity "
                "where datname = :name "
                "and pid <> pg_backend_pid()"
            ),
            {
                "name": SCRATCH_DATABASE,
            },
        )

        connection.execute(
            sa.text(
                f'drop database if exists '
                f'"{SCRATCH_DATABASE}"'
            )
        )

        connection.execute(
            sa.text(
                f'create database "{SCRATCH_DATABASE}"'
            )
        )


def drop_scratch() -> None:

    try:
        with admin_engine().connect() as connection:

            connection.execute(
                sa.text(
                    "select pg_terminate_backend(pid) "
                    "from pg_stat_activity "
                    "where datname = :name "
                    "and pid <> pg_backend_pid()"
                ),
                {
                    "name": SCRATCH_DATABASE,
                },
            )

            connection.execute(
                sa.text(
                    f'drop database if exists '
                    f'"{SCRATCH_DATABASE}"'
                )
            )

    except Exception as exc:

        print(
            f"       (could not drop the test database: "
            f"{type(exc).__name__})"
        )


def alembic(
    *arguments: str,
    url: str | None = None,
) -> subprocess.CompletedProcess:

    """
    Run alembic against a chosen database.

    DATABASE_URL is set for the child process, because that is
    where migrations/env.py reads it from -- the same variable
    the application uses, so a migration cannot be applied to
    a database the code is not configured for.
    """

    environment = dict(
        os.environ
    )

    environment["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    environment["DATABASE_URL"] = (
        url
        or scratch_url()
    )

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            *arguments,
        ],
        cwd=str(
            PROJECT_ROOT
        ),
        capture_output=True,
        text=True,
        timeout=600,
        env=environment,
    )


def require_alembic(
    *arguments: str,
    url: str | None = None,
) -> str:

    completed = alembic(
        *arguments,
        url=url,
    )

    assert_equal(
        completed.returncode,
        0,
        (
            f"alembic {' '.join(arguments)} must succeed.\n"
            f"{completed.stdout[-3000:]}\n"
            f"{completed.stderr[-3000:]}"
        ),
    )

    return (
        completed.stdout
        + completed.stderr
    )


def public_tables(
    url: str,
) -> list[str]:

    engine = sa.create_engine(
        url
    )

    try:
        with engine.connect() as connection:

            return sorted(
                row[0]
                for row in connection.execute(
                    sa.text(
                        "select tablename from pg_tables "
                        "where schemaname = 'public'"
                    )
                )
            )

    finally:
        engine.dispose()


# ==========================================================
# TEST 1 - UPGRADE FROM NOTHING
# ==========================================================

def test_upgrade_from_empty():

    section(
        "TEST 1 - AN EMPTY DATABASE UPGRADES TO THE FULL "
        "SCHEMA"
    )

    reset_scratch()

    before = public_tables(
        scratch_url()
    )

    assert_equal(
        before,
        [],
        (
            "The test database must start empty, or nothing "
            "below proves the migration built anything."
        ),
    )

    require_alembic(
        "upgrade",
        "head",
    )

    after = public_tables(
        scratch_url()
    )

    # DERIVED FROM THE MODELS, NOT TYPED OUT.
    #
    # An earlier version of this test listed the seven tables
    # literally. Adding worker_heartbeats in 11.11 then failed
    # it, which was the guard working -- but the fix was to
    # edit the list, and a list that gets edited every time it
    # fires only ever proves that somebody edited it.
    #
    # Deriving the expectation from Base.metadata asserts the
    # thing actually worth asserting: the migrations build the
    # schema the application's models describe. A model added
    # without a migration now fails here, which the literal
    # list could never catch.
    expected = sorted(
        [
            "alembic_version",
        ]
        + list(
            Base.metadata.tables
        )
    )

    assert_equal(
        after,
        expected,
        (
            "Upgrading an empty database must produce exactly "
            "the application schema plus Alembic's own "
            "version table."
        ),
    )

    current = require_alembic(
        "current",
    )

    assert_true(
        "(head)" in current,
        (
            "After upgrading, the database must report itself "
            "at head. Anything else means the version table "
            "and the schema disagree."
        ),
    )

    ok(
        f"empty database -> {len(after)} tables "
        f"({', '.join(t for t in after if t != 'alembic_version')})"
        f", reported at head"
    )


# ==========================================================
# TEST 2 - THE MIGRATION REPRODUCES THE MODELS
# ==========================================================

def test_upgrade_from_a_populated_earlier_revision():

    section(
        "TEST 1b - A POPULATED DATABASE AT AN EARLIER "
        "REVISION UPGRADES TO HEAD"
    )

    # ------------------------------------------------------
    # THE CASE A REAL DEPLOYMENT ACTUALLY PERFORMS
    # ------------------------------------------------------
    #
    # TEST 1 upgrades an EMPTY database to head. That proves
    # the chain runs, and it is not the same thing as this.
    #
    # A deployed system sits at some earlier revision with
    # rows in it. The next migration runs against those rows,
    # and that is where an additive migration goes wrong in
    # ways an empty database never shows:
    #
    #   a NOT NULL column with no server_default fails on the
    #     first existing row
    #   a new unique index fails if the existing data already
    #     violates it
    #   a type change fails on data the new type cannot hold
    #
    # Every one of those passes empty -> head and fails on a
    # real deployment, at the worst moment.
    #
    # So: stop at the first revision, put representative rows
    # in, upgrade to head, and check the rows are still there
    # and still readable.
    # ------------------------------------------------------

    revisions = revision_chain()

    if len(
        revisions
    ) < 2:

        print(
            "       (only one revision exists, so there is "
            "no earlier revision to upgrade from; this "
            "becomes meaningful at the second migration)"
        )
        return

    first = revisions[0]

    head = revisions[-1]

    reset_scratch()

    require_alembic(
        "upgrade",
        first,
    )

    tables_at_first = public_tables(
        scratch_url()
    )

    assert_true(
        "documents" in tables_at_first,
        (
            f"Revision {first} must create the core schema."
        ),
    )

    ok(
        f"stopped at {first}: "
        f"{len(tables_at_first)} table(s)"
    )

    # ------------------------------------------------------
    # REPRESENTATIVE ROWS, THROUGH THE MODELS
    # ------------------------------------------------------
    #
    # Only the tables that exist at this revision, and only
    # the columns the models declare -- so the test cannot be
    # wrong about the schema it is inserting into.

    engine = sa.create_engine(
        scratch_url()
    )

    document_id = str(
        uuid.uuid4()
    )

    job_id = str(
        uuid.uuid4()
    )

    try:

        factory = sessionmaker(
            bind=engine
        )

        with factory() as session:

            session.add(
                DocumentModel(
                    id=document_id,
                    original_filename=(
                        "pre-upgrade.png"
                    ),
                    content_type="image/png",
                    document_type="SIA_BADGE",
                    processing_status="COMPLETED",
                )
            )

            session.add(
                DocumentJobModel(
                    id=job_id,
                    status="QUEUED",
                    original_filename=(
                        "pre-upgrade.png"
                    ),
                    content_type="image/png",
                    size_bytes=1234,
                    source_name=(
                        f"{job_id}.png"
                    ),
                )
            )

            session.commit()

        ok(
            "inserted a document row and a queued job row at "
            f"{first}, so the next migration runs against "
            "real data rather than an empty table"
        )

        # --------------------------------------------------
        # NOW UPGRADE
        # --------------------------------------------------

        require_alembic(
            "upgrade",
            "head",
        )

        after = public_tables(
            scratch_url()
        )

        assert_equal(
            after,
            sorted(
                [
                    "alembic_version",
                ]
                + list(
                    Base.metadata.tables
                )
            ),
            (
                "Upgrading a populated earlier revision must "
                "reach exactly the same schema as upgrading "
                "an empty one."
            ),
        )

        new_tables = sorted(
            set(
                after
            )
            - set(
                tables_at_first
            )
        )

        ok(
            f"upgraded {first} -> {head}, adding "
            + (
                ", ".join(
                    new_tables
                )
                if new_tables
                else "no tables"
            )
        )

        # --------------------------------------------------
        # AND THE DATA SURVIVED
        # --------------------------------------------------
        #
        # The whole point. A migration that reaches the right
        # schema by dropping and recreating a table would
        # pass every structural assertion above and lose
        # every row.

        with factory() as session:

            document = session.get(
                DocumentModel,
                document_id,
            )

            assert_true(
                document is not None,
                (
                    "The document row inserted before the "
                    "upgrade must still exist. A migration "
                    "that reaches the right schema by "
                    "recreating a table passes every "
                    "structural check and loses every row."
                ),
            )

            assert_equal(
                document.original_filename,
                "pre-upgrade.png",
                (
                    "The row must be unchanged, not merely "
                    "present."
                ),
            )

            job = session.get(
                DocumentJobModel,
                job_id,
            )

            assert_true(
                job is not None,
                (
                    "The queued job must survive the "
                    "upgrade. Losing the queue during a "
                    "deploy silently drops accepted work."
                ),
            )

            assert_equal(
                job.status,
                "QUEUED",
                (
                    "The job must still be claimable after "
                    "the upgrade."
                ),
            )

        ok(
            "both rows survived the upgrade unchanged, "
            "including the queued job"
        )

        # --------------------------------------------------
        # AND NO DRIFT
        # --------------------------------------------------

        completed = alembic(
            "check",
        )

        assert_equal(
            completed.returncode,
            0,
            (
                "After upgrading a populated database, "
                "alembic check must report no drift.\n"
                f"{completed.stdout[-1500:]}\n"
                f"{completed.stderr[-1500:]}"
            ),
        )

        ok(
            "alembic check reports no drift after the "
            "populated upgrade"
        )

    finally:
        engine.dispose()


def revision_chain() -> list[str]:

    """
    Revision ids from base to head, in order.

    Read from the migration scripts rather than listed here,
    so a new migration is picked up without editing a test.
    """

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    directory = ScriptDirectory.from_config(
        Config(
            str(
                PROJECT_ROOT
                / "alembic.ini"
            )
        )
    )

    ordered = [
        script.revision
        for script in directory.walk_revisions()
    ]

    # walk_revisions yields head first.
    ordered.reverse()

    return ordered


def test_no_drift_after_upgrade():

    section(
        "TEST 2 - AFTER UPGRADING, THE MODELS AND THE "
        "DATABASE AGREE EXACTLY"
    )

    # `alembic check` is autogenerate without writing a file:
    # it compares database/models.py against the connected
    # database and fails if there is anything to do.
    #
    # This is the assertion that a fresh deployment will work.
    # A migration that is merely CLOSE to the models passes
    # every test on a machine that already has the schema.
    completed = alembic(
        "check",
    )

    combined = (
        completed.stdout
        + completed.stderr
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The migrated database does not match "
            "database/models.py:\n"
            f"{combined[-4000:]}\n"
            "Either the migration is incomplete or a model "
            "changed without one being written."
        ),
    )

    assert_true(
        "No new upgrade operations detected"
        in combined,
        (
            "alembic check must explicitly report no "
            "operations. A silent pass could mean it "
            "compared nothing."
        ),
    )

    ok(
        "alembic check on the freshly migrated database: no "
        "new upgrade operations"
    )


# ==========================================================
# TEST 3 - THE MODELS HAVE NOT DRIFTED AHEAD
# ==========================================================

def test_working_database_matches_migrations():

    section(
        "TEST 3 - THE WORKING DATABASE IS AT HEAD AND MATCHES "
        "THE MODELS"
    )

    # Read-only. `current` and `check` do not modify anything,
    # which is why this one is allowed to look at the real
    # database.
    current = require_alembic(
        "current",
        url=real_url(),
    )

    assert_true(
        "(head)" in current,
        (
            "The working database must be stamped at head.\n"
            "It was built before Alembic existed, so it is "
            "marked as already at the initial revision with\n"
            "    alembic stamp head\n"
            "rather than upgraded -- upgrading would try to "
            "create tables that are already there."
        ),
    )

    completed = alembic(
        "check",
        url=real_url(),
    )

    combined = (
        completed.stdout
        + completed.stderr
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The working database has drifted from "
            "database/models.py:\n"
            f"{combined[-4000:]}\n"
            "This is the failure that only ever appears on "
            "somebody else's fresh deployment: a model change "
            "with no migration written works fine on every "
            "machine that already has the column."
        ),
    )

    ok(
        "the working database is at head with no drift from "
        "the models"
    )


# ==========================================================
# TEST 4 - THE CONSTRAINTS ACTUALLY ENFORCE
# ==========================================================

def test_constraints_enforce():

    section(
        "TEST 4 - THE TWO RELEASE-CRITICAL CONSTRAINTS ARE "
        "ENFORCED BY POSTGRESQL"
    )

    from backend.app.domain.job_states import (
        ACTIVE_STATUSES,
    )

    engine = sa.create_engine(
        scratch_url()
    )

    try:

        # --------------------------------------------------
        # IT EXISTS, AND IT IS PARTIAL
        # --------------------------------------------------

        with engine.connect() as connection:

            definition = connection.execute(
                sa.text(
                    "select indexdef from pg_indexes "
                    "where indexname = "
                    "'uq_document_jobs_active_source'"
                )
            ).scalar()

        assert_true(
            definition is not None,
            (
                "uq_document_jobs_active_source must exist in "
                "the migrated database. It is what makes "
                "duplicate detection race-free."
            ),
        )

        assert_true(
            "UNIQUE INDEX" in definition,
            "It must be UNIQUE.",
        )

        assert_true(
            "WHERE" in definition,
            (
                "It must be PARTIAL. Without the WHERE "
                "clause, source_sha256 becomes globally "
                "unique and the same bytes could never be "
                "deliberately reprocessed -- which Phase 10.3 "
                "specifically allows."
            ),
        )

        for status in ACTIVE_STATUSES:

            assert_true(
                status in definition,
                (
                    f"The index predicate must cover "
                    f"{status}. It is generated from "
                    f"ACTIVE_STATUSES so the index, the "
                    f"queries and the tests cannot disagree "
                    f"about what 'active' means."
                ),
            )

        ok(
            f"partial unique index present, predicate covers "
            f"all {len(ACTIVE_STATUSES)} active statuses"
        )


        # --------------------------------------------------
        # AND IT REFUSES THE SECOND ROW
        # --------------------------------------------------
        # An index in pg_indexes proves it was created. An
        # insert PostgreSQL rejects proves it works.
        #
        # Written through the ORM models rather than as raw
        # SQL. A hand-written INSERT has to name every column,
        # which means guessing at them -- the first version of
        # this test guessed "attempts" for what is actually
        # "attempt_count" and failed for a reason that had
        # nothing to do with the constraint. Going through the
        # models means the test cannot be wrong about the
        # schema, and stays correct when a column is added.
        # --------------------------------------------------

        from sqlalchemy.orm import Session

        from database.models import (
            DocumentJobModel,
            DocumentModel,
            HumanReviewModel,
        )

        fingerprint = "a" * 64

        def new_job(
            identifier: str,
            status: str,
        ) -> DocumentJobModel:

            return DocumentJobModel(
                id=identifier,
                status=status,
                original_filename=(
                    f"{identifier}.jpg"
                ),
                content_type="image/jpeg",
                source_name=(
                    f"{identifier}.jpg"
                ),
                source_sha256=fingerprint,
            )

        with Session(
            engine
        ) as session:

            session.add(
                new_job(
                    "job-active-1",
                    ACTIVE_STATUSES[0],
                )
            )

            session.commit()

        rejected = False

        with Session(
            engine
        ) as session:

            session.add(
                new_job(
                    "job-active-2",
                    ACTIVE_STATUSES[0],
                )
            )

            try:
                session.commit()

            except sa.exc.IntegrityError:
                rejected = True
                session.rollback()

        assert_true(
            rejected,
            (
                "PostgreSQL accepted a SECOND active job for "
                "the same source fingerprint.\n"
                "This is the race Phase 10.3 exists to close: "
                "six simultaneous uploads of identical bytes "
                "must produce one job and five duplicate "
                "responses. Without this constraint they can "
                "all pass a check-then-insert and all create "
                "a job."
            ),
        )

        ok(
            "a second ACTIVE job with the same fingerprint is "
            "refused by the database"
        )


        # --------------------------------------------------
        # BUT A FINISHED JOB DOES NOT BLOCK A REPROCESS
        # --------------------------------------------------
        # The other half of the rule, and the reason the index
        # is partial. Asserting only the rejection above would
        # pass just as well for a GLOBAL unique index, which
        # would be wrong -- it would make deliberate
        # reprocessing of identical bytes impossible forever.
        # --------------------------------------------------

        with Session(
            engine
        ) as session:

            finished = session.get(
                DocumentJobModel,
                "job-active-1",
            )

            finished.status = "COMPLETED"

            session.commit()

        with Session(
            engine
        ) as session:

            session.add(
                new_job(
                    "job-active-3",
                    ACTIVE_STATUSES[0],
                )
            )

            session.commit()

        with engine.connect() as connection:

            count = connection.execute(
                sa.text(
                    "select count(*) from document_jobs "
                    "where source_sha256 = :fingerprint"
                ),
                {
                    "fingerprint": fingerprint,
                },
            ).scalar()

        assert_equal(
            count,
            2,
            (
                "Once the earlier job is COMPLETED, the same "
                "bytes must be allowed again. A GLOBAL unique "
                "index would pass the rejection test above "
                "and fail this one."
            ),
        )

        ok(
            "once the earlier job is COMPLETED the same "
            "fingerprint is accepted again, so the index is "
            "genuinely partial rather than global"
        )


        # --------------------------------------------------
        # ONE REVIEW PER DOCUMENT
        # --------------------------------------------------

        with Session(
            engine
        ) as session:

            session.add(
                DocumentModel(
                    id="doc-unique-1",
                    original_filename="x.jpg",
                    content_type="image/jpeg",
                    processing_status="PROCESSED",
                )
            )

            session.commit()

        def new_review(
            identifier: str,
        ) -> HumanReviewModel:

            return HumanReviewModel(
                id=identifier,
                document_id="doc-unique-1",
                reviewer_id="reviewer-1",
                human_action="APPROVED",
            )

        with Session(
            engine
        ) as session:

            session.add(
                new_review(
                    "review-1"
                )
            )

            session.commit()

        duplicate_rejected = False

        with Session(
            engine
        ) as session:

            session.add(
                new_review(
                    "review-2"
                )
            )

            try:
                session.commit()

            except sa.exc.IntegrityError:
                duplicate_rejected = True
                session.rollback()

        assert_true(
            duplicate_rejected,
            (
                "PostgreSQL accepted a SECOND review for one "
                "document.\n"
                "Phase 7C found this was reachable through "
                "concurrent submission, and a table "
                "constraint is the only thing that closes it "
                "-- an application check has the same race "
                "the review submission itself had."
            ),
        )

        ok(
            "a second human review for the same document is "
            "refused by the database"
        )

    finally:
        engine.dispose()


# ==========================================================
# TEST 5 - THERE IS A WAY BACK
# ==========================================================

def test_downgrade_and_reupgrade():

    section(
        "TEST 5 - DOWNGRADE REMOVES THE SCHEMA AND UPGRADE "
        "REBUILDS IT"
    )

    require_alembic(
        "downgrade",
        "base",
    )

    remaining = public_tables(
        scratch_url()
    )

    assert_equal(
        remaining,
        [
            "alembic_version",
        ],
        (
            "Downgrading to base must remove every "
            "application table, leaving only Alembic's "
            "bookkeeping.\n"
            "A migration whose downgrade does not work is a "
            "one-way door: the only way back from a bad "
            "deploy is a restore."
        ),
    )

    require_alembic(
        "upgrade",
        "head",
    )

    rebuilt = public_tables(
        scratch_url()
    )

    # Same derivation as test_upgrade_from_empty, and for the
    # same reason: a literal count is a number that gets
    # edited whenever it fires.
    assert_equal(
        rebuilt,
        sorted(
            [
                "alembic_version",
            ]
            + list(
                Base.metadata.tables
            )
        ),
        (
            "Upgrading again must rebuild the whole schema. "
            "Migrations that only work once are migrations "
            "that cannot be tested."
        ),
    )

    completed = alembic(
        "check",
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "And the rebuilt schema must still match the "
            "models:\n"
            f"{(completed.stdout + completed.stderr)[-2000:]}"
        ),
    )

    ok(
        "downgrade to base leaves only alembic_version; "
        f"upgrade rebuilds all {len(Base.metadata.tables)} "
        "application tables with no drift"
    )


# ==========================================================
# TEST 6 - THE CONFIGURATION HOLDS NO SECRETS
# ==========================================================

def test_configuration_is_safe():

    section(
        "TEST 6 - NO CREDENTIALS IN THE COMMITTED "
        "CONFIGURATION"
    )

    ini = (
        PROJECT_ROOT
        / "alembic.ini"
    ).read_text(
        encoding="utf-8"
    )


    # ------------------------------------------------------
    # sqlalchemy.url MUST BE EMPTY
    # ------------------------------------------------------

    setting = None

    for line in ini.splitlines():

        stripped = line.strip()

        if stripped.startswith(
            "#"
        ):
            continue

        if stripped.startswith(
            "sqlalchemy.url"
        ):
            setting = stripped.split(
                "=",
                1,
            )[1].strip() if "=" in stripped else ""

    assert_equal(
        setting,
        "",
        (
            "alembic.ini is committed. sqlalchemy.url must "
            "stay empty, with migrations/env.py reading "
            "DATABASE_URL from the environment.\n"
            "A real URL here puts a PostgreSQL password in "
            "version control. A placeholder here gives an "
            "operator two places to configure and one of them "
            "wrong."
        ),
    )

    ok(
        "alembic.ini declares sqlalchemy.url empty; the URL "
        "comes from DATABASE_URL"
    )


    # ------------------------------------------------------
    # AND NOTHING SENSITIVE ANYWHERE IN IT
    # ------------------------------------------------------

    live = os.getenv(
        "DATABASE_URL",
        "",
    )

    leaked = []

    for candidate in (
        live,
        "postgresql+psycopg://",
        "gsk_",
    ):

        if candidate and candidate in ini:
            leaked.append(
                candidate
            )

    assert_equal(
        leaked,
        [],
        (
            f"alembic.ini contains something sensitive: "
            f"{leaked}"
        ),
    )

    ok(
        "no connection string and no key anywhere in "
        "alembic.ini"
    )


    # ------------------------------------------------------
    # env.py READS THE SAME VARIABLE THE APPLICATION DOES
    # ------------------------------------------------------

    env_source = (
        PROJECT_ROOT
        / "migrations"
        / "env.py"
    ).read_text(
        encoding="utf-8"
    )

    assert_true(
        'getenv(\n        "DATABASE_URL"' in env_source
        or 'getenv("DATABASE_URL"' in env_source,
        (
            "migrations/env.py must read DATABASE_URL. Any "
            "other source of truth means a migration could be "
            "applied to a database the application is not "
            "talking to."
        ),
    )

    assert_true(
        "from database.models import Base" in env_source,
        (
            "env.py must import the models. Without that "
            "import, Base.metadata is empty and autogenerate "
            "confidently proposes dropping the entire "
            "schema."
        ),
    )

    ok(
        "env.py reads DATABASE_URL and imports the models, so "
        "metadata is populated"
    )


    # ------------------------------------------------------
    # ALEMBIC IS PINNED
    # ------------------------------------------------------

    requirements = (
        PROJECT_ROOT
        / "requirements.txt"
    ).read_text(
        encoding="utf-8"
    )

    import alembic as alembic_package

    assert_true(
        re.search(
            r"(?im)^alembic==",
            requirements,
        )
        is not None,
        (
            "alembic must be pinned in requirements.txt. "
            "Migrations are part of the deployment, so the "
            "tool that applies them is a runtime dependency, "
            "not a developer convenience."
        ),
    )

    pinned = re.search(
        r"(?im)^alembic==([\d.]+)",
        requirements,
    ).group(
        1
    )

    assert_equal(
        pinned,
        alembic_package.__version__,
        (
            "The pinned Alembic version must be the one "
            "actually installed and verified against."
        ),
    )

    ok(
        f"alembic=={pinned} pinned in requirements.txt and "
        f"installed"
    )


# ==========================================================
# TEST 7 - THE OLD MECHANISM POINTS AT THE NEW ONE
# ==========================================================

def test_old_mechanism_defers():

    section(
        "TEST 7 - THE HAND-BUILT SCHEMA SCRIPT DEFERS TO "
        "ALEMBIC"
    )

    script = (
        PROJECT_ROOT
        / "scripts"
        / "maintenance"
        / "create_job_tables.py"
    )

    source = script.read_text(
        encoding="utf-8"
    )

    assert_true(
        "alembic" in source.lower(),
        (
            "create_job_tables.py built the schema before "
            "Alembic existed, and it still runs. Whoever "
            "opens it next has to be told that migrations are "
            "now the mechanism -- otherwise the schema gets "
            "changed in two places and the two disagree on "
            "the first fresh deployment."
        ),
    )

    ok(
        "create_job_tables.py names Alembic as the mechanism "
        "that replaced it"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.3 - SCHEMA MIGRATIONS"
    )
    print(
        "=" * 74
    )

    if not can_create_databases():

        print()
        print(
            "[BLOCKED] The connected PostgreSQL role cannot "
            "create databases."
        )
        print(
            "          Migration testing requires "
            "`downgrade base`, which drops every table."
        )
        print(
            "          Running that against the working "
            "database would destroy real stored documents "
            "and"
        )
        print(
            "          every review decision, so this suite "
            "will not fall back to it."
        )
        print(
            "          Grant CREATEDB to the role in "
            "DATABASE_URL and re-run."
        )

        return 1

    try:
        test_upgrade_from_empty()
        test_upgrade_from_a_populated_earlier_revision()
        test_no_drift_after_upgrade()
        test_working_database_matches_migrations()
        test_constraints_enforce()
        test_downgrade_and_reupgrade()
        test_configuration_is_safe()
        test_old_mechanism_defers()

    finally:
        drop_scratch()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.3 MIGRATION TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
