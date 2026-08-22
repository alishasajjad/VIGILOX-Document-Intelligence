import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid

from datetime import datetime, timezone
from pathlib import Path


# ==========================================================
# PHASE 11.12 - BACKUP AND RESTORE
# ==========================================================
#
# A backup script that has never been restored from is not a
# backup, it is a directory of files that are believed to be a
# backup. The difference is discovered exactly once.
#
# So this restores. Round trip, end to end, and it checks the
# documents come back byte for byte and still pair with their
# rows.
#
#
# NOTHING HERE TOUCHES REAL DATA
# ----------------------------------------------------------
# This is the part worth being careful about, because a
# restore test that gets its target wrong destroys the thing
# it was protecting.
#
#   The database is a throwaway -- vigilox_backup_test --
#   dropped and recreated at the start and dropped at the
#   end. The live database is opened once, read-only, to
#   find the server, and never written.
#
#   The documents are synthetic PNG bytes generated here.
#   No real document, no sample, no user upload.
#
#   Both storage roots are fresh temporary directories.
#   The configured roots are never read and never written.
#
# Every subprocess gets DATABASE_URL, DOCUMENT_STORAGE_DIR and
# DOCUMENT_PENDING_DIR pointing at those throwaways, and TEST
# 0 proves the redirection took effect before anything else
# runs. Without that proof the whole suite could be quietly
# operating on the real deployment and still pass.
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


from dotenv import load_dotenv  # noqa: E402

load_dotenv(
    PROJECT_ROOT
    / ".env"
)

import sqlalchemy as sa  # noqa: E402

from sqlalchemy.orm import sessionmaker  # noqa: E402


SCRATCH_DATABASE = "vigilox_backup_test"

BACKUP_SCRIPT = (
    PROJECT_ROOT
    / "scripts"
    / "maintenance"
    / "backup.py"
)

RESTORE_SCRIPT = (
    PROJECT_ROOT
    / "scripts"
    / "maintenance"
    / "restore.py"
)


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


def assert_in(
    needle: str,
    haystack: str,
    message: str,
) -> None:

    if needle not in haystack:

        raise AssertionError(
            f"{message}\n"
            f"Looked for: {needle!r}\n"
            f"In:\n{haystack[-3000:]}"
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


def reset_scratch() -> None:

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

    except Exception as error:

        print(
            f"       (could not drop the test database: "
            f"{type(error).__name__})"
        )


# ==========================================================
# RUNNING THE SCRIPTS
# ==========================================================
#
# In a subprocess, with the throwaway configuration in the
# environment. Not by importing them: backup.py's inventory
# reads database/database.py, whose engine is built at import
# time from DATABASE_URL. Importing it in this process would
# bind it to the REAL database, and no amount of later
# reassignment would unbind it.
#
# A subprocess is the only way to be certain which database
# the code under test is talking to.
# ==========================================================

class Sandbox:

    def __init__(
        self,
        directory: Path,
    ) -> None:

        self.root = directory

        self.storage = (
            directory
            / "documents"
        )

        self.pending = (
            directory
            / "pending"
        )

        self.backups = (
            directory
            / "backups"
        )

        self.restored_storage = (
            directory
            / "restored-documents"
        )

        self.restored_pending = (
            directory
            / "restored-pending"
        )

        for path in (
            self.storage,
            self.pending,
            self.backups,
            self.restored_storage,
            self.restored_pending,
        ):
            path.mkdir(
                parents=True,
                exist_ok=True,
            )


    def environment(
        self,
        *,
        storage: Path | None = None,
        pending: Path | None = None,
    ) -> dict:

        environment = dict(
            os.environ
        )

        environment["PYTHONPATH"] = str(
            PROJECT_ROOT
        )

        # THE REDIRECTION. TEST 0 proves it works.
        environment["DATABASE_URL"] = scratch_url()

        environment["DOCUMENT_STORAGE_DIR"] = str(
            storage
            if storage is not None
            else self.storage
        )

        environment["DOCUMENT_PENDING_DIR"] = str(
            pending
            if pending is not None
            else self.pending
        )

        # PaddleOCR is irrelevant to a backup and costs
        # seconds and hundreds of megabytes to load.
        environment["VIGILOX_API_EAGER_PIPELINE"] = "false"

        return environment


    def run(
        self,
        script: Path,
        *arguments: str,
        storage: Path | None = None,
        pending: Path | None = None,
    ) -> subprocess.CompletedProcess:

        return subprocess.run(
            [
                sys.executable,
                str(
                    script
                ),
                *arguments,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            cwd=str(
                PROJECT_ROOT
            ),
            env=self.environment(
                storage=storage,
                pending=pending,
            ),
        )


def alembic_upgrade(
    sandbox: Sandbox,
) -> None:

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(
            PROJECT_ROOT
        ),
        env=sandbox.environment(),
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The throwaway database must be migrated to head "
            "before anything is inserted into it.\n"
            f"{completed.stdout[-2000:]}\n"
            f"{completed.stderr[-2000:]}"
        ),
    )


# ==========================================================
# SYNTHETIC DATA
# ==========================================================
#
# A minimal valid PNG per document, with distinct bytes so a
# restore that swapped two files would be caught. Deliberately
# not a real document: this suite writes to a temporary
# directory and drops a database, and neither is somewhere a
# real document should ever be.
# ==========================================================

PNG_HEADER = bytes(
    [
        0x89,
        0x50,
        0x4E,
        0x47,
        0x0D,
        0x0A,
        0x1A,
        0x0A,
    ]
)


def synthetic_bytes(
    marker: str,
    size: int,
) -> bytes:

    body = (
        f"VIGILOX-SYNTHETIC-{marker}-"
    ).encode(
        "ascii"
    )

    filler = (
        marker.encode(
            "ascii"
        )
        * size
    )

    return (
        PNG_HEADER
        + body
        + filler
    )[:size + len(PNG_HEADER) + len(body)]


def seed(
    sandbox: Sandbox,
    *,
    document_count: int = 4,
    pending_count: int = 2,
) -> dict:

    """
    Write synthetic documents and rows into the throwaway
    database and the throwaway storage root.

    Uses the real DocumentStorageService, with the root passed
    explicitly, so the files land where the application would
    put them.

    That matters more here than it looks. There is no
    storage_path column: the documents table holds an id, and
    the path is DERIVED from it as

        <root>/<id>/original<suffix>

    A test that laid the files out by hand would be asserting
    against its own guess at that convention, and a restore
    that put every file one directory too deep would pass.
    """

    from backend.app.services.document_storage_service import (
        DocumentStorageService,
    )

    from database.models import (
        DocumentJobModel,
        DocumentModel,
    )

    # The root is passed explicitly rather than through the
    # environment. This process's environment still points at
    # the real deployment, and it must stay that way -- the
    # subprocesses are what get redirected.
    storage = DocumentStorageService(
        storage_root=sandbox.storage,
    )

    engine = sa.create_engine(
        scratch_url()
    )

    session_factory = sessionmaker(
        bind=engine
    )

    documents = {}

    with tempfile.TemporaryDirectory() as staging:

        with session_factory() as session:

            for index in range(
                document_count
            ):

                document_id = str(
                    uuid.uuid4()
                )

                payload = synthetic_bytes(
                    str(
                        index
                    ),
                    600 + index * 37,
                )

                # save_original copies from a source path,
                # the way an upload does.
                source = (
                    Path(
                        staging
                    )
                    / f"upload-{index}.png"
                )

                source.write_bytes(
                    payload
                )

                stored = storage.save_original(
                    document_id=document_id,
                    source_path=source,
                    content_type="image/png",
                )

                documents[document_id] = {
                    "bytes": payload,
                    "relative": str(
                        stored.relative_to(
                            sandbox.storage
                        )
                    ).replace(
                        "\\",
                        "/",
                    ),
                }

                session.add(
                    DocumentModel(
                        id=document_id,
                        original_filename=(
                            f"synthetic-{index}.png"
                        ),
                        content_type="image/png",
                        document_type="SIA_BADGE",
                        processing_status="COMPLETED",
                    )
                )

            session.commit()

    # Unfinished jobs with their pending sources, so the
    # queue-without-sources case is real rather than
    # hypothetical.
    pending = {}

    with session_factory() as session:

        for index in range(
            pending_count
        ):

            source_name = (
                f"pending-{index}-"
                f"{uuid.uuid4().hex[:8]}.png"
            )

            payload = synthetic_bytes(
                f"P{index}",
                300 + index * 11,
            )

            (
                sandbox.pending
                / source_name
            ).write_bytes(
                payload
            )

            pending[source_name] = payload

            session.add(
                DocumentJobModel(
                    id=str(
                        uuid.uuid4()
                    ),
                    status="QUEUED",
                    original_filename=source_name,
                    content_type="image/png",
                    size_bytes=len(
                        payload
                    ),
                    source_name=source_name,
                )
            )

        session.commit()

    engine.dispose()

    return {
        "documents": documents,
        "pending": pending,
    }


# ==========================================================
# TEST 0 - THE REDIRECTION ACTUALLY REDIRECTS
# ==========================================================

def test_the_sandbox_is_really_a_sandbox(
    sandbox: Sandbox,
) -> None:

    section(
        "TEST 0 - THE SUITE IS POINTED AT THROWAWAYS, NOT AT "
        "THE REAL DEPLOYMENT"
    )

    # ------------------------------------------------------
    # This runs FIRST and everything else depends on it.
    #
    # If DOCUMENT_STORAGE_DIR did not take effect -- a
    # different variable name, load_dotenv overriding it, a
    # service caching a root at import -- then every later
    # test would be reading and writing the real deployment's
    # storage, and they would all still pass. The suite would
    # look like a successful restore test and be a
    # destructive operation on live data.
    # ------------------------------------------------------

    probe = """
import json

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)
from backend.app.services.job_source_store import JobSourceStore
from database.database import DATABASE_URL

print(
    json.dumps(
        {
            "storage": str(DocumentStorageService().storage_root),
            "pending": str(JobSourceStore().pending_root),
            "database": DATABASE_URL,
        }
    )
)
"""

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "probe.py"
        )

        script.write_text(
            probe,
            encoding="utf-8",
        )

        completed = sandbox.run(
            script
        )

    assert_equal(
        completed.returncode,
        0,
        (
            "The probe must run.\n"
            f"{completed.stdout[-2000:]}\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    observed = json.loads(
        [
            line
            for line in completed.stdout.splitlines()
            if line.strip().startswith(
                "{"
            )
        ][-1]
    )

    assert_equal(
        Path(
            observed["storage"]
        ).resolve(),
        sandbox.storage.resolve(),
        (
            "DOCUMENT_STORAGE_DIR did not take effect. "
            "REFUSING to continue: every later test in this "
            "file writes to whatever this resolves to, and "
            "if that is the real storage root then this "
            "suite is a destructive operation on live "
            "documents that reports PASS."
        ),
    )

    assert_equal(
        Path(
            observed["pending"]
        ).resolve(),
        sandbox.pending.resolve(),
        "DOCUMENT_PENDING_DIR did not take effect.",
    )

    assert_true(
        SCRATCH_DATABASE in observed["database"],
        (
            "DATABASE_URL did not take effect in the child "
            "process. This suite drops its target database. "
            "REFUSING to continue.\n"
            "Target reported: "
            + observed["database"].rsplit(
                "@",
                1,
            )[-1]
        ),
    )

    ok(
        "storage, pending and database all resolve to "
        "throwaways inside the temporary directory"
    )

    # And the real roots are untouched by construction --
    # asserted, because "by construction" is what people say
    # right before it is not.

    real_storage = (
        PROJECT_ROOT
        / "storage"
        / "documents"
    )

    assert_true(
        sandbox.storage.resolve() != real_storage.resolve(),
        "The sandbox must not be the real storage root.",
    )

    ok(
        f"the real storage root ({real_storage}) is not a "
        "target of this suite"
    )


# ==========================================================
# TEST 1 - A BACKUP RUNS AND ITS MANIFEST IS HONEST
# ==========================================================

def test_backup_produces_a_verifiable_manifest(
    sandbox: Sandbox,
    seeded: dict,
) -> Path:

    section(
        "TEST 1 - THE BACKUP RUNS AND WRITES A MANIFEST THAT "
        "DESCRIBES WHAT IT DID"
    )

    completed = sandbox.run(
        BACKUP_SCRIPT,
        "--output",
        str(
            sandbox.backups
        ),
        "--all",
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The backup must succeed.\n"
            f"{completed.stdout[-4000:]}\n"
            f"{completed.stderr[-4000:]}"
        ),
    )

    produced = sorted(
        sandbox.backups.iterdir()
    )

    assert_equal(
        len(
            produced
        ),
        1,
        "Exactly one backup directory must be produced.",
    )

    backup = produced[0]

    manifest = json.loads(
        (
            backup
            / "MANIFEST.json"
        ).read_text(
            encoding="utf-8",
        )
    )

    assert_true(
        manifest["complete"],
        (
            "The manifest must record complete=true.\n"
            f"{completed.stdout[-4000:]}"
        ),
    )

    assert_equal(
        manifest["failed_parts"],
        [],
        "No part may have failed.",
    )

    assert_equal(
        sorted(
            part["part"]
            for part in manifest["parts"]
        ),
        [
            "database",
            "documents",
            "pending",
        ],
        "--all must produce all three parts.",
    )

    ok(
        "all 3 parts written, manifest records complete=true"
    )

    # ------------------------------------------------------
    # THE INVENTORY MATCHES WHAT WAS SEEDED
    # ------------------------------------------------------

    inventory = manifest["database"]["inventory"]

    assert_equal(
        inventory["documents"],
        len(
            seeded["documents"]
        ),
        (
            "The manifest inventory must count the documents "
            "that are actually there. It is what a restore "
            "gets checked against."
        ),
    )

    assert_equal(
        inventory["unfinished_jobs"],
        len(
            seeded["pending"]
        ),
        (
            "The unfinished job count is what warns an "
            "operator that pending sources matter."
        ),
    )

    assert_true(
        inventory["alembic_revision"],
        (
            "The manifest must record the schema revision. "
            "Restoring a dump under code at a different "
            "revision is a failure that presents as query "
            "errors rather than as a restore problem."
        ),
    )

    ok(
        f"inventory records {inventory['documents']} "
        f"documents, {inventory['unfinished_jobs']} "
        f"unfinished jobs, alembic "
        f"{inventory['alembic_revision']}"
    )

    # ------------------------------------------------------
    # THE ORDERING IS RECORDED, AND IT IS THE SAFE ONE
    # ------------------------------------------------------

    assert_equal(
        manifest["ordering"],
        "database-then-filesystem",
        (
            "The ordering must be recorded, and it must be "
            "database first. An upload concurrent with the "
            "backup then restores as an orphan file, which "
            "reconciliation clears. The other order restores "
            "it as a row pointing at a file that does not "
            "exist."
        ),
    )

    assert_equal(
        manifest["consistency"],
        "hot",
        (
            "Without --quiesced the manifest must say hot. "
            "A pair of snapshots taken at different instants "
            "is not consistent, and labelling it consistent "
            "is worse than not taking it, because the label "
            "is what gets trusted at restore time."
        ),
    )

    assert_in(
        "NOT a transactionally consistent pair",
        manifest["consistency_note"],
        (
            "The manifest must state the limitation in "
            "words, not only in a one-word field."
        ),
    )

    ok(
        "manifest records consistency=hot with the "
        "limitation spelled out, and ordering="
        "database-then-filesystem with the reason"
    )

    return backup


# ==========================================================
# TEST 2 - NO CREDENTIALS ANYWHERE
# ==========================================================

def test_no_credentials_escape(
    sandbox: Sandbox,
    backup: Path,
) -> None:

    section(
        "TEST 2 - THE PASSWORD IS NOT IN THE OUTPUT, THE "
        "MANIFEST, OR ANY COMMAND LINE"
    )

    from sqlalchemy.engine import make_url

    password = make_url(
        real_url()
    ).password

    if not password:

        print(
            "       (the configured database has no "
            "password, so there is nothing to leak; the "
            "redaction path is still exercised below)"
        )

    # ------------------------------------------------------
    # THE MANIFEST
    # ------------------------------------------------------

    manifest_text = (
        backup
        / "MANIFEST.json"
    ).read_text(
        encoding="utf-8",
    )

    if password:

        assert_true(
            str(
                password
            ) not in manifest_text,
            (
                "The manifest contains the database "
                "password. A backup directory is copied to "
                "object storage, to a laptop, to a ticket "
                "attachment -- it is the last place a "
                "credential should be."
            ),
        )

    assert_in(
        "***",
        manifest_text,
        (
            "The manifest must record the redacted URL, so "
            "an operator can tell WHICH database a backup "
            "came from without the credential being there."
        ),
    )

    ok(
        "the manifest names the database and host with the "
        "password masked"
    )

    # ------------------------------------------------------
    # THE OUTPUT
    # ------------------------------------------------------

    completed = sandbox.run(
        BACKUP_SCRIPT,
        "--output",
        str(
            sandbox.backups
        ),
        "--database",
    )

    combined = (
        completed.stdout
        + completed.stderr
    )

    if password:

        assert_true(
            str(
                password
            ) not in combined,
            (
                "The password appears in the script's "
                "output. Backup output goes to a scheduler's "
                "log, which is kept for a long time and read "
                "by more people than the database is.\n"
                + combined[-2000:]
            ),
        )

    ok(
        "nothing printed by the backup contains the "
        "password"
    )

    # ------------------------------------------------------
    # THE SOURCE
    # ------------------------------------------------------
    #
    # The user's rule for 11.12 was explicit: no credentials
    # in the scripts. Asserted against the files rather than
    # trusted.

    for script in (
        BACKUP_SCRIPT,
        RESTORE_SCRIPT,
    ):

        source = script.read_text(
            encoding="utf-8",
        )

        if password:

            assert_true(
                str(
                    password
                ) not in source,
                f"{script.name} contains a real password.",
            )

        # PGPASSWORD must be set in an environment, never
        # placed on a command line where ps can read it.
        assert_true(
            "PGPASSWORD" in source,
            (
                f"{script.name} must pass the password "
                "through PGPASSWORD."
            ),
        )

        # --------------------------------------------
        # THE PASSWORD MUST NEVER REACH AN ARGUMENT
        # --------------------------------------------
        #
        # Checked against argv CONSTRUCTION, not against the
        # word "password" appearing anywhere in the file.
        #
        # The first version of this check was a substring
        # scan, and it failed on the line
        #
        #     hide_password=True,
        #
        # which is the redaction helper -- the opposite of a
        # leak. A rule loose enough to flag its own safety
        # measure teaches whoever hits it to loosen the rule.
        #
        # So: every line that appends to the argument list,
        # or sits inside the argument list literal, is
        # examined; and PGPASSWORD is required to appear only
        # as an environment assignment.

        argv_lines = [
            line
            for line in source.splitlines()
            if not line.strip().startswith(
                "#"
            )
            and (
                "arguments.append" in line
                or re.match(
                    r"^\s+(f?\"--|\"--)",
                    line,
                )
            )
        ]

        assert_true(
            argv_lines,
            (
                f"The argv detector found no argument "
                f"construction in {script.name}. It is "
                "looking in the wrong place, and a check "
                "that cannot see the code it guards passes "
                "for the wrong reason."
            ),
        )

        leaking = [
            line.strip()
            for line in argv_lines
            if "password" in line.lower()
        ]

        assert_equal(
            leaking,
            [],
            (
                f"{script.name} puts a password on a "
                "command line. Command lines are readable "
                "by every user on the host through ps, and "
                "by anything that logs a subprocess "
                "invocation."
            ),
        )

        # And PGPASSWORD only ever as an environment entry.

        pgpassword_lines = [
            line.strip()
            for line in source.splitlines()
            if "PGPASSWORD" in line
            and not line.strip().startswith(
                "#"
            )
        ]

        for line in pgpassword_lines:

            assert_true(
                line.startswith(
                    'environment["PGPASSWORD"]'
                ),
                (
                    f"{script.name} mentions PGPASSWORD "
                    "somewhere other than an environment "
                    f"assignment: {line}"
                ),
            )

        assert_true(
            pgpassword_lines,
            (
                f"{script.name} must set PGPASSWORD. It is "
                "the only channel that keeps the password "
                "out of both the file and the command line."
            ),
        )

    # ----------------------------------------------------------
    # AND THE DETECTOR IS CHECKED AGAINST A CONSTRUCTED CASE
    # ----------------------------------------------------------
    #
    # The rule above passed on the first attempt for the wrong
    # reason once already. This proves it can still fail.

    planted = [
        line.strip()
        for line in (
            'arguments.append(\n',
            '    f"--password={parsed.password}"\n',
        )
        if "arguments.append" in line
        or re.match(
            r"^\s*(f?\"--|\"--)",
            line,
        )
    ]

    assert_true(
        any(
            "password" in line.lower()
            for line in planted
        ),
        (
            "The argv detector does not flag a deliberately "
            "planted --password argument, so its passing "
            "above proves nothing."
        ),
    )

    ok(
        "the argv detector flags a planted --password "
        "argument, so its verdict on the real scripts means "
        "something"
    )

    ok(
        "both scripts pass the password through the child "
        "environment, and neither builds it into an argument"
    )


# ==========================================================
# TEST 3 - VERIFICATION CATCHES A DAMAGED BACKUP
# ==========================================================

def test_verification_catches_corruption(
    sandbox: Sandbox,
    backup: Path,
) -> None:

    section(
        "TEST 3 - A DAMAGED ARCHIVE IS REFUSED BEFORE "
        "ANYTHING IS WRITTEN"
    )

    # ------------------------------------------------------
    # First: the dry run passes on a good backup.
    # ------------------------------------------------------

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            backup
        ),
        "--all",
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "Verification of an intact backup must pass.\n"
            f"{completed.stdout[-3000:]}\n"
            f"{completed.stderr[-3000:]}"
        ),
    )

    assert_in(
        "Nothing was written",
        completed.stdout,
        (
            "Without --confirm the restore must verify and "
            "change nothing. A restore tool whose default "
            "action is to restore gets run by accident "
            "exactly once."
        ),
    )

    ok(
        "without --confirm the restore verifies and states "
        "that nothing was written"
    )

    # ------------------------------------------------------
    # Then: corrupt a copy and watch it refuse.
    # ------------------------------------------------------

    damaged = (
        sandbox.root
        / "damaged-backup"
    )

    if damaged.exists():
        shutil.rmtree(
            damaged
        )

    shutil.copytree(
        backup,
        damaged,
    )

    target = (
        damaged
        / "documents.tar.gz"
    )

    original = target.read_bytes()

    # One byte in the middle. Not a truncation -- the size
    # stays the same, so only the checksum can catch it. That
    # is the case worth testing: a size check would miss it
    # and extraction would fail halfway through, having
    # already written files.
    middle = len(
        original
    ) // 2

    target.write_bytes(
        original[:middle]
        + bytes(
            [
                original[middle]
                ^ 0xFF
            ]
        )
        + original[middle + 1:]
    )

    assert_equal(
        target.stat().st_size,
        len(
            original
        ),
        (
            "The damaged archive must be the same SIZE, or "
            "this tests a size check rather than a checksum."
        ),
    )

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            damaged
        ),
        "--all",
        "--confirm",
        "--storage-root",
        str(
            sandbox.restored_storage
        ),
        "--pending-root",
        str(
            sandbox.restored_pending
        ),
    )

    assert_equal(
        completed.returncode,
        1,
        (
            "A checksum mismatch must fail.\n"
            f"{completed.stdout[-3000:]}"
        ),
    )

    assert_in(
        "does not match its recorded sha256",
        completed.stdout,
        "The failure must name the reason.",
    )

    assert_equal(
        sorted(
            entry.name
            for entry in sandbox.restored_storage.iterdir()
        ),
        [],
        (
            "Nothing may have been written. Verification "
            "runs before extraction precisely so a damaged "
            "archive does not leave the target holding half "
            "a backup."
        ),
    )

    ok(
        "a single flipped byte is caught by checksum, and "
        "the target is still empty"
    )

    # ------------------------------------------------------
    # And an incomplete backup is not restorable at all.
    # ------------------------------------------------------

    incomplete = (
        sandbox.root
        / "incomplete-backup"
    )

    if incomplete.exists():
        shutil.rmtree(
            incomplete
        )

    shutil.copytree(
        backup,
        incomplete,
    )

    manifest_path = (
        incomplete
        / "MANIFEST.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8",
        )
    )

    manifest["complete"] = False
    manifest["failed_parts"] = [
        "documents",
    ]

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
        ),
        encoding="utf-8",
    )

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            incomplete
        ),
        "--all",
    )

    assert_equal(
        completed.returncode,
        1,
        "An incomplete backup must be refused.",
    )

    assert_in(
        "complete=false",
        completed.stdout,
        (
            "The refusal must say the manifest recorded the "
            "backup as incomplete."
        ),
    )

    ok(
        "a backup whose manifest records complete=false is "
        "refused rather than partially restored"
    )


# ==========================================================
# TEST 4 - THE ROUND TRIP
# ==========================================================

def test_round_trip(
    sandbox: Sandbox,
    seeded: dict,
    backup: Path,
) -> None:

    section(
        "TEST 4 - THE DOCUMENTS AND THEIR ROWS COME BACK, "
        "BYTE FOR BYTE AND STILL PAIRED"
    )

    # ------------------------------------------------------
    # DESTROY THE ORIGINALS
    # ------------------------------------------------------
    #
    # A restore test that leaves the originals in place
    # proves nothing: every assertion afterwards would pass
    # against data that was never removed.

    shutil.rmtree(
        sandbox.storage
    )

    sandbox.storage.mkdir(
        parents=True
    )

    with sa.create_engine(
        scratch_url(),
        isolation_level="AUTOCOMMIT",
    ).connect() as connection:

        for table in (
            "audit_events",
            "human_reviews",
            "document_analyses",
            "document_jobs",
            "documents",
        ):

            connection.execute(
                sa.text(
                    f"truncate table {table} cascade"
                )
            )

    with sa.create_engine(
        scratch_url()
    ).connect() as connection:

        remaining = connection.execute(
            sa.text(
                "select count(*) from documents"
            )
        ).scalar_one()

    assert_equal(
        remaining,
        0,
        (
            "The originals must actually be gone before the "
            "restore, or this test proves nothing."
        ),
    )

    assert_equal(
        list(
            sandbox.storage.iterdir()
        ),
        [],
        "The storage root must actually be empty.",
    )

    ok(
        f"{len(seeded['documents'])} documents and every row "
        "deleted; the restore has something to prove"
    )

    # ------------------------------------------------------
    # RESTORE
    # ------------------------------------------------------
    #
    # --force because the database still has its tables: the
    # truncate emptied them, it did not drop them. That is
    # exactly the real case -- a restore almost always goes
    # into a database that already has a schema -- so it is
    # worth exercising rather than avoiding.

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            backup
        ),
        "--all",
        "--confirm",
        "--force",
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The restore must succeed.\n"
            f"{completed.stdout[-5000:]}\n"
            f"{completed.stderr[-5000:]}"
        ),
    )

    ok(
        "restore reported success"
    )

    # ------------------------------------------------------
    # THE FILES: BYTE FOR BYTE
    # ------------------------------------------------------

    for document_id, expected in seeded[
        "documents"
    ].items():

        path = (
            sandbox.storage
            / expected["relative"]
        )

        assert_true(
            path.is_file(),
            (
                f"{document_id} did not come back at "
                f"{expected['relative']}. Its row may have; "
                "a row without its file is a document nobody "
                "can open."
            ),
        )

        actual = path.read_bytes()

        assert_equal(
            len(
                actual
            ),
            len(
                expected["bytes"]
            ),
            f"{document_id} came back a different size.",
        )

        assert_true(
            actual == expected["bytes"],
            (
                f"{document_id} came back with different "
                "bytes. Same length, different content -- "
                "which is what a restore that swapped two "
                "files would look like."
            ),
        )

    ok(
        f"all {len(seeded['documents'])} document files "
        "restored byte for byte, at the paths the storage "
        "service derives from their ids"
    )

    # ------------------------------------------------------
    # THE PAIRING, ASKED OF THE APPLICATION ITSELF
    # ------------------------------------------------------
    #
    # The whole point of the exercise. A database restore and
    # a filesystem restore that each succeed separately can
    # still leave rows pointing at nothing.
    #
    # This does not re-derive the pairing rule. It runs
    # StorageIntegrityService -- the same scan the operational
    # tooling uses -- against the restored pair, in a
    # subprocess so it is bound to the throwaway database and
    # the throwaway root. A test that computed the expected
    # paths itself would agree with its own mistake.

    probe = """
import json

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)
from backend.app.services.storage_integrity_service import (
    StorageIntegrityService,
)

report = StorageIntegrityService(
    storage_service=DocumentStorageService(),
).scan()

print(json.dumps(report["summary"]))
"""

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "integrity.py"
        )

        script.write_text(
            probe,
            encoding="utf-8",
        )

        scanned = sandbox.run(
            script
        )

    assert_equal(
        scanned.returncode,
        0,
        (
            "The integrity scan must run.\n"
            f"{scanned.stdout[-2000:]}\n"
            f"{scanned.stderr[-2000:]}"
        ),
    )

    summary = json.loads(
        [
            line
            for line in scanned.stdout.splitlines()
            if line.strip().startswith(
                "{"
            )
        ][-1]
    )

    assert_equal(
        summary["database_documents"],
        len(
            seeded["documents"]
        ),
        "Every document row must come back.",
    )

    assert_equal(
        summary["missing_storage"],
        0,
        (
            "A row whose file is missing is the failure this "
            "whole exercise exists to catch, and the one "
            "reconciliation deliberately will not fix: "
            "deleting the row would destroy the last record "
            "that the document existed."
        ),
    )

    assert_equal(
        summary["invalid_storage"],
        0,
        (
            "A restored row whose stored path does not "
            "validate means the restore produced something "
            "the application refuses to read."
        ),
    )

    assert_equal(
        summary["orphan_storage"],
        0,
        (
            "A restored file with no row would be deleted by "
            "reconciliation. In a quiesced round trip there "
            "should be none: every file archived had a row in "
            "the dump."
        ),
    )

    assert_equal(
        summary["issue_count"],
        0,
        (
            "The application's own integrity scan must "
            "report the restored pair as healthy. This is "
            "the assertion that means the restore worked, "
            "rather than that the files and rows both "
            "happen to exist."
        ),
    )

    ok(
        "the application's own integrity scan reports "
        f"{summary['healthy_documents']} healthy documents, "
        "0 missing, 0 invalid, 0 orphaned"
    )

    # ------------------------------------------------------
    # THE PENDING SOURCES, IN THEIR OWN TREE
    # ------------------------------------------------------

    for name, expected in seeded[
        "pending"
    ].items():

        path = (
            sandbox.pending
            / name
        )

        assert_true(
            path.is_file(),
            (
                f"pending source {name} did not come back. "
                "The dump contains its job, so a worker will "
                "claim it and fail."
            ),
        )

        assert_true(
            path.read_bytes() == expected,
            f"pending source {name} came back altered.",
        )

    assert_equal(
        sorted(
            entry.name
            for entry in sandbox.pending.iterdir()
        ),
        sorted(
            seeded["pending"]
        ),
        (
            "The pending tree must contain exactly the "
            "pending sources -- no managed document may have "
            "landed in it."
        ),
    )

    ok(
        f"all {len(seeded['pending'])} pending sources "
        "restored into the pending tree, and nothing else "
        "landed there"
    )

    # ------------------------------------------------------
    # THE TWO TREES STAYED SEPARATE
    # ------------------------------------------------------
    #
    # Phase 9.2. If a pending source ended up under managed
    # storage, the integrity scan would classify it as an
    # orphan and reconciliation would delete it.

    managed_names = {
        entry.name
        for entry in sandbox.storage.rglob(
            "*"
        )
        if entry.is_file()
    }

    overlap = managed_names & set(
        seeded["pending"]
    )

    assert_equal(
        sorted(
            overlap
        ),
        [],
        (
            "A pending source was restored into managed "
            "storage. It has no document row by definition, "
            "so the integrity scan would class it as an "
            "orphan and reconciliation would delete it."
        ),
    )

    ok(
        "no pending source landed under the managed storage "
        "root"
    )

    # ------------------------------------------------------
    # AND THE RESTORE SAID WHAT TO DO NEXT
    # ------------------------------------------------------

    assert_in(
        "reconcile_storage.py",
        completed.stdout,
        (
            "After a hot backup the two halves may disagree "
            "slightly. The restore must point at the tool "
            "that reports that, rather than leaving the "
            "operator to remember."
        ),
    )

    assert_in(
        "unfinished",
        completed.stdout,
        (
            "The restore must mention the unfinished jobs it "
            "just put back in the queue."
        ),
    )

    ok(
        "the restore names the reconciliation step and warns "
        "about the requeued unfinished jobs"
    )


# ==========================================================
# TEST 5 - THE REFUSALS
# ==========================================================

def test_the_refusals(
    sandbox: Sandbox,
    backup: Path,
) -> None:

    section(
        "TEST 5 - THE RESTORE REFUSES THE FOUR WAYS THIS "
        "GOES WRONG"
    )

    # ------------------------------------------------------
    # 1. A NON-EMPTY TARGET WITHOUT --force
    # ------------------------------------------------------
    #
    # sandbox.storage is now populated by TEST 4.

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            backup
        ),
        "--documents",
        "--confirm",
    )

    assert_equal(
        completed.returncode,
        1,
        (
            "Restoring documents into a non-empty tree "
            "without --force must be refused.\n"
            f"{completed.stdout[-2000:]}"
        ),
    )

    assert_in(
        "REFUSING",
        completed.stdout,
        "The refusal must be explicit.",
    )

    ok(
        "extracting on top of an existing document tree is "
        "refused without --force"
    )

    # ------------------------------------------------------
    # 2. OVERLAPPING ROOTS
    # ------------------------------------------------------

    nested = (
        sandbox.restored_storage
        / "pending-inside"
    )

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            backup
        ),
        "--all",
        "--confirm",
        "--force",
        "--storage-root",
        str(
            sandbox.restored_storage
        ),
        "--pending-root",
        str(
            nested
        ),
    )

    assert_equal(
        completed.returncode,
        1,
        (
            "A pending root nested inside managed storage "
            "must be refused.\n"
            f"{completed.stdout[-2000:]}"
        ),
    )

    assert_in(
        "overlap",
        completed.stdout,
        (
            "The refusal must name the problem. Phase 9.2 "
            "keeps these separate because the integrity scan "
            "deletes managed files with no row, and every "
            "pending file has no row."
        ),
    )

    assert_equal(
        sorted(
            entry.name
            for entry in sandbox.restored_storage.iterdir()
        ),
        [],
        (
            "The overlap must be caught BEFORE anything is "
            "written."
        ),
    )

    ok(
        "a pending root nested inside managed storage is "
        "refused before any file is written"
    )

    # ------------------------------------------------------
    # 3. A SCHEMA REVISION THAT DOES NOT MATCH
    # ------------------------------------------------------

    mismatched = (
        sandbox.root
        / "mismatched-backup"
    )

    if mismatched.exists():
        shutil.rmtree(
            mismatched
        )

    shutil.copytree(
        backup,
        mismatched,
    )

    manifest_path = (
        mismatched
        / "MANIFEST.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8",
        )
    )

    manifest["database"]["inventory"][
        "alembic_revision"
    ] = "0000deadbeef"

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
        ),
        encoding="utf-8",
    )

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            mismatched
        ),
        "--database",
        "--confirm",
        "--force",
    )

    assert_equal(
        completed.returncode,
        1,
        (
            "A dump from a different schema revision must "
            "be refused.\n"
            f"{completed.stdout[-2000:]}"
        ),
    )

    assert_in(
        "revision mismatch",
        completed.stdout,
        (
            "The refusal must name the reason. Restoring an "
            "older dump under newer code produces confusing "
            "query errors, and the connection to the restore "
            "is not obvious hours later."
        ),
    )

    ok(
        "a dump whose recorded revision differs from the "
        "code's head is refused, naming both revisions"
    )

    # ------------------------------------------------------
    # 4. AN ARCHIVE THAT TRIES TO ESCAPE ITS DESTINATION
    # ------------------------------------------------------
    #
    # An archive is untrusted input even when the matching
    # script produced the last one. This is the classic tar
    # traversal, and the fact that a manifest lists the file
    # does not make its members safe -- a manifest is a JSON
    # file anybody can edit, as the two cases above just did.

    hostile = (
        sandbox.root
        / "hostile-backup"
    )

    if hostile.exists():
        shutil.rmtree(
            hostile
        )

    hostile.mkdir()

    archive_path = (
        hostile
        / "documents.tar.gz"
    )

    escape_target = (
        sandbox.root
        / "ESCAPED.txt"
    )

    payload = (
        hostile
        / "payload.txt"
    )

    payload.write_text(
        "this must never be written outside the "
        "destination\n",
        encoding="utf-8",
    )

    with tarfile.open(
        archive_path,
        "w:gz",
    ) as archive:

        archive.add(
            payload,
            arcname="../../ESCAPED.txt",
        )

    from scripts.maintenance.backup import sha256_of

    (
        hostile
        / "MANIFEST.json"
    ).write_text(
        json.dumps(
            {
                "product": "VIGILOX Document Intelligence",
                "manifest_version": 1,
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "label": "hostile",
                "consistency": "hot",
                "consistency_note": (
                    "NOT a transactionally consistent pair"
                ),
                "ordering": "database-then-filesystem",
                "complete": True,
                "failed_parts": [],
                "parts": [
                    {
                        "part": "documents",
                        "file": "documents.tar.gz",
                        "label": "managed",
                        "archive_bytes": (
                            archive_path.stat().st_size
                        ),
                        "sha256": sha256_of(
                            archive_path
                        ),
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    completed = sandbox.run(
        RESTORE_SCRIPT,
        "--input",
        str(
            hostile
        ),
        "--documents",
        "--confirm",
        "--force",
        "--storage-root",
        str(
            sandbox.restored_storage
        ),
    )

    assert_true(
        not escape_target.exists(),
        (
            "The archive wrote outside its destination. That "
            "is a path traversal: an archive is untrusted "
            "input, and a matching checksum only proves it "
            "is the archive the manifest describes -- the "
            "manifest being a JSON file anybody can write."
        ),
    )

    assert_equal(
        completed.returncode,
        1,
        (
            "An escaping member must fail rather than being "
            "silently skipped.\n"
            f"{completed.stdout[-2000:]}"
        ),
    )

    assert_in(
        "escapes the destination",
        completed.stdout,
        "The refusal must name the reason.",
    )

    ok(
        "an archive member named ../../ESCAPED.txt is "
        "refused, and nothing was written outside the "
        "destination"
    )


# ==========================================================
# TEST 6 - THE QUIESCE CLAIM IS CHECKED
# ==========================================================

def test_quiesce_claim(
    sandbox: Sandbox,
) -> None:

    section(
        "TEST 6 - --quiesced IS RECORDED AS A CLAIM AND "
        "CHECKED AGAINST WHAT CAN BE OBSERVED"
    )

    # The throwaway database has no worker heartbeat and no
    # PROCESSING job, so the claim is consistent with what is
    # observable and the backup should proceed.

    completed = sandbox.run(
        BACKUP_SCRIPT,
        "--output",
        str(
            sandbox.root
            / "quiesced"
        ),
        "--database",
        "--quiesced",
        "--label",
        "phase-11-12-restore-test",
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "With no worker and nothing PROCESSING, "
            "--quiesced must be accepted.\n"
            f"{completed.stdout[-3000:]}\n"
            f"{completed.stderr[-3000:]}"
        ),
    )

    produced = sorted(
        (
            sandbox.root
            / "quiesced"
        ).iterdir()
    )[0]

    manifest = json.loads(
        (
            produced
            / "MANIFEST.json"
        ).read_text(
            encoding="utf-8",
        )
    )

    assert_equal(
        manifest["consistency"],
        "quiesced",
        "The claim must be recorded.",
    )

    assert_in(
        "the operator asserted",
        manifest["consistency_note"],
        (
            "The manifest must attribute the claim to the "
            "operator. The script cannot prove no other "
            "process is about to write, and a manifest that "
            "implied it had is worse than one that says who "
            "said so."
        ),
    )

    assert_equal(
        manifest["label"],
        "phase-11-12-restore-test",
        "The operator's label must be recorded.",
    )

    ok(
        "--quiesced is recorded as an operator claim, "
        "attributed, with the label kept"
    )

    # ------------------------------------------------------
    # AND IT IS REFUSED WHEN THE EVIDENCE CONTRADICTS IT
    # ------------------------------------------------------
    #
    # A PROCESSING job means a pipeline is mid-document and
    # will write when it finishes -- so the two halves cannot
    # be captured consistently, whatever the operator
    # believes about the worker.

    # Through the ORM model, not hand-written SQL.
    #
    # The first version of this spelled out an INSERT with
    # column names taken from memory -- job_id, file_size_bytes,
    # source_path, submitted_at -- and not one of the four
    # exists. The real columns are id, size_bytes, source_name
    # and created_at.
    #
    # Using the model means the test cannot be wrong about
    # the schema, and a column rename breaks it loudly at the
    # rename rather than quietly here.
    from database.models import DocumentJobModel

    engine = sa.create_engine(
        scratch_url()
    )

    session_factory = sessionmaker(
        bind=engine
    )

    job_id = str(
        uuid.uuid4()
    )

    try:

        with session_factory() as session:

            session.add(
                DocumentJobModel(
                    id=job_id,
                    status="PROCESSING",
                    original_filename="mid.png",
                    content_type="image/png",
                    size_bytes=10,
                    source_name="mid.png",
                )
            )

            session.commit()

        completed = sandbox.run(
            BACKUP_SCRIPT,
            "--output",
            str(
                sandbox.root
                / "refused"
            ),
            "--database",
            "--quiesced",
        )

        assert_equal(
            completed.returncode,
            1,
            (
                "A PROCESSING job contradicts the quiesce "
                "claim and must be refused.\n"
                f"{completed.stdout[-3000:]}"
            ),
        )

        assert_in(
            "PROCESSING",
            completed.stdout,
            "The refusal must name the evidence.",
        )

        assert_true(
            not (
                sandbox.root
                / "refused"
            ).exists(),
            (
                "The check must run before the output "
                "directory is created, so a refused backup "
                "leaves nothing behind to be mistaken for "
                "one."
            ),
        )

        ok(
            "a PROCESSING job refuses --quiesced, names the "
            "evidence, and writes nothing"
        )

    finally:

        with session_factory() as session:

            session.query(
                DocumentJobModel
            ).filter(
                DocumentJobModel.id == job_id
            ).delete()

            session.commit()

        engine.dispose()


# ==========================================================
# TEST 7 - THE PROCEDURE IS WRITTEN DOWN
# ==========================================================

def test_the_procedure_is_documented() -> None:

    section(
        "TEST 7 - THE OPERATIONAL PROCEDURE IS DOCUMENTED"
    )

    path = (
        PROJECT_ROOT
        / "docs"
        / "operations"
        / "backup-restore.md"
    )

    assert_true(
        path.is_file(),
        (
            "docs/operations/backup-restore.md must exist. A "
            "restore is run by whoever is on call, not by "
            "whoever wrote the script."
        ),
    )

    document = path.read_text(
        encoding="utf-8",
    )

    for topic, needle in (
        (
            "the consistency limitation",
            "not a transactionally consistent",
        ),
        (
            "the quiesce window",
            "quiesce",
        ),
        (
            "restoring the database",
            "restore.py",
        ),
        (
            "pending sources",
            "pending",
        ),
        (
            "reconciliation afterwards",
            "reconcile_storage",
        ),
        (
            "the container procedure",
            "docker compose",
        ),
        (
            "verifying a backup without restoring",
            "--confirm",
        ),
    ):

        assert_true(
            needle.lower() in document.lower(),
            (
                f"The document must cover {topic} "
                f"(looked for {needle!r})."
            ),
        )

    # ------------------------------------------------------
    # AND IT MUST NOT CONTAIN A CREDENTIAL
    # ------------------------------------------------------

    from sqlalchemy.engine import make_url

    password = make_url(
        real_url()
    ).password

    if password:

        assert_true(
            str(
                password
            ) not in document,
            (
                "The runbook contains the real database "
                "password. A runbook is the most widely read "
                "file in an incident."
            ),
        )

    ok(
        f"backup-restore.md covers 7 topics and contains no "
        f"credential ({len(document.splitlines())} lines)"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.12 - BACKUP AND RESTORE"
    )
    print(
        "=" * 74
    )

    from scripts.maintenance.backup import find_tool

    if find_tool(
        "pg_dump"
    ) is None or find_tool(
        "pg_restore"
    ) is None:

        print()
        print(
            "EXTERNAL_BLOCKED: the PostgreSQL client tools "
            "are not available in this environment."
        )
        print()
        print(
            "  pg_dump and pg_restore were not found on "
            "PATH, in VIGILOX_PG_BIN, or in the usual "
            "install locations."
        )
        print(
            "  Set VIGILOX_PG_BIN to the directory "
            "containing them and re-run."
        )
        print()
        print(
            "  NOT PASSING. A backup and restore suite that "
            "skips when it cannot restore is exactly the "
            "reassurance nobody should have."
        )
        return 1

    directory = tempfile.mkdtemp(
        prefix="vigilox-backup-test-",
    )

    sandbox = Sandbox(
        Path(
            directory
        )
    )

    print(
        f"  sandbox: {sandbox.root}"
    )

    try:

        # TEST 0 FIRST, ALWAYS. Nothing below is safe to run
        # until the redirection is proven.
        test_the_sandbox_is_really_a_sandbox(
            sandbox
        )

        reset_scratch()

        alembic_upgrade(
            sandbox
        )

        seeded = seed(
            sandbox
        )

        print(
            f"  seeded {len(seeded['documents'])} synthetic "
            f"documents and {len(seeded['pending'])} pending "
            "sources"
        )

        backup = test_backup_produces_a_verifiable_manifest(
            sandbox,
            seeded,
        )

        test_no_credentials_escape(
            sandbox,
            backup,
        )

        test_verification_catches_corruption(
            sandbox,
            backup,
        )

        test_round_trip(
            sandbox,
            seeded,
            backup,
        )

        test_the_refusals(
            sandbox,
            backup,
        )

        test_quiesce_claim(
            sandbox
        )

        test_the_procedure_is_documented()

    finally:

        drop_scratch()

        shutil.rmtree(
            sandbox.root,
            ignore_errors=True,
        )

        print()
        print(
            "  cleaned up: throwaway database dropped, "
            "sandbox removed"
        )

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.12 BACKUP AND RESTORE TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
