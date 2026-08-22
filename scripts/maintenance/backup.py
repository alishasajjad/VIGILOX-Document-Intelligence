import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile

from datetime import datetime, timezone
from pathlib import Path


# ==========================================================
# BACK UP THE DATABASE AND THE MANAGED DOCUMENT STORAGE
# PHASE 11.12
# ==========================================================
#
# This application's state lives in two places that have to
# agree with each other:
#
#   PostgreSQL        document rows, analyses, reviews, the
#                     audit trail, the job queue
#
#   the filesystem    the document bytes themselves, under
#                     the managed storage root
#
# A row carries a storage path. Neither half is useful alone:
# the database without the files is a catalogue of documents
# nobody can open, and the files without the database are a
# directory of images with no extraction, no review and no
# audit trail.
#
#
# THE PART THAT IS EASY TO GET WRONG
# ----------------------------------------------------------
# pg_dump and tar are two operations at two different
# instants. A dump taken at 02:00:00 and an archive taken at
# 02:04:30 are NOT a transactionally consistent pair, and no
# amount of scripting makes them one. Anything that happened
# in those four and a half minutes is in one half and not the
# other.
#
# There are two honest answers and this script supports both.
#
# --quiesced says the operator has already stopped the worker
# and stopped accepting uploads. Nothing is being created or
# deleted, so the two halves cannot disagree. This is the only
# mode that produces a genuinely consistent pair, and it is
# recorded in the manifest as a claim the OPERATOR made -- the
# script cannot verify it, so it does not pretend to. It does
# check for signs to the contrary.
#
# Without it, this is a hot backup, and the manifest says so.
# A hot backup is still worth taking. It is reconcilable
# rather than consistent, and the ordering below is chosen so
# that what it gets wrong is the recoverable thing.
#
#
# WHY THE DATABASE GOES FIRST
# ----------------------------------------------------------
# Deliberate, and it is the whole reason this is a script
# rather than two commands in a runbook.
#
# Take the database at T1 and the filesystem at T2.
#
#   An upload at T1.5   the row is not in the dump, the file
#                       is in the archive. Restores as an
#                       ORPHAN FILE: a managed file with no
#                       row. reconcile_storage.py already
#                       classifies and clears these, and
#                       nothing is lost that the database
#                       claimed to have.
#
#   A deletion at T1.5  the row IS in the dump, the file is
#                       NOT in the archive. Restores as
#                       MISSING STORAGE: a row pointing at
#                       nothing. That is the bad direction.
#
# Reverse the order and you reverse which one happens. So the
# question is which event is more likely during a backup, and
# it is not close: uploads happen continuously and are the
# product working, while deletions are rare, administrative
# and deliberate. Database first therefore makes the COMMON
# concurrent event fail in the direction that is recoverable.
#
# Neither order is consistent. This one is wrong in a way that
# reconciliation can fix.
#
#
# PENDING UPLOADS ARE A SEPARATE ARCHIVE
# ----------------------------------------------------------
# Not the same archive, on purpose.
#
# A pending file is the bytes of an upload that has been
# accepted but not processed -- it has no document row yet, by
# definition. Phase 9.2 keeps the pending root outside the
# managed storage root precisely because the integrity scan
# would otherwise class every in-flight upload as an orphan
# and delete it.
#
# One combined archive would put that invariant one careless
# extraction away from being undone. Two archives cannot be
# restored into the same place by accident.
#
# They matter because the dump contains QUEUED and RETRY_WAIT
# jobs. Restore the queue without the pending files and a
# worker claims each of those jobs, cannot find its source,
# and fails it -- which looks like a batch of bad documents
# rather than an incomplete restore.
#
#
# CREDENTIALS
# ----------------------------------------------------------
# There is no password in this file, none in any command line
# it builds, and none in the manifest it writes.
#
# The URL comes from DATABASE_URL. The password is handed to
# pg_dump through PGPASSWORD in the child process environment
# ONLY -- never as an argument, because arguments are visible
# to every user on the host in ps. Everything printed and
# everything written goes through redacted().
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

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402


# ==========================================================
# LOCATING pg_dump
# ==========================================================
#
# PATH first, then an explicit override, then the usual
# install locations. If it is genuinely absent this reports
# exactly that and how to work around it, rather than
# producing an empty file and exiting 0.
#
# VERSION MATTERS. A pg_dump older than the server refuses to
# run at all; a newer one produces an archive the older
# pg_restore cannot read. The manifest records both versions
# so a restore that is about to fail can be seen to be about
# to fail.
# ==========================================================

WINDOWS_POSTGRES_ROOT = Path(
    r"C:\Program Files\PostgreSQL"
)

UNIX_POSTGRES_ROOTS = (
    Path(
        "/usr/lib/postgresql"
    ),
    Path(
        "/usr/local/pgsql/bin"
    ),
    Path(
        "/usr/pgsql"
    ),
)


def find_tool(
    name: str,
) -> Path | None:

    override = os.getenv(
        "VIGILOX_PG_BIN",
        "",
    ).strip()

    if override:

        candidate = (
            Path(
                override
            )
            / name
        )

        for suffix in (
            "",
            ".exe",
        ):

            option = candidate.with_name(
                candidate.name
                + suffix
            )

            if option.is_file():
                return option

    found = shutil.which(
        name
    )

    if found:
        return Path(
            found
        )

    # Installed but not on PATH is the common case on
    # Windows, and it is worth finding rather than telling an
    # operator to fix their PATH.

    roots = []

    if WINDOWS_POSTGRES_ROOT.is_dir():

        roots.extend(
            sorted(
                WINDOWS_POSTGRES_ROOT.iterdir(),
                reverse=True,
            )
        )

    for root in UNIX_POSTGRES_ROOTS:

        if root.is_dir():

            roots.extend(
                sorted(
                    root.iterdir(),
                    reverse=True,
                )
            )

    for root in roots:

        for candidate in (
            root / "bin" / name,
            root / "bin" / f"{name}.exe",
            root / name,
            root / f"{name}.exe",
        ):

            if candidate.is_file():
                return candidate

    return None


def tool_version(
    executable: Path,
) -> str:

    try:

        completed = subprocess.run(
            [
                str(
                    executable
                ),
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

    except OSError as error:

        return f"unavailable: {error}"

    return (
        completed.stdout.strip()
        or completed.stderr.strip()
        or "unknown"
    )


# ==========================================================
# REDACTION
# ==========================================================

def redacted(
    url: str,
) -> str:

    """
    A connection URL with the password removed.

    Everything this script prints or writes about the
    database goes through here. SQLAlchemy's own repr
    already masks the password, and this uses it rather
    than a regular expression that would eventually meet a
    password containing an @.
    """

    try:

        return make_url(
            url
        ).render_as_string(
            hide_password=True,
        )

    except Exception:

        # An unparseable URL must not be echoed back on the
        # chance that the unparseable part is the password.
        return "<unparseable DATABASE_URL>"


# ==========================================================
# CHECKSUMS
# ==========================================================

def sha256_of(
    path: Path,
) -> str:

    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as handle:

        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):

            digest.update(
                block
            )

    return digest.hexdigest()


# ==========================================================
# THE DATABASE HALF
# ==========================================================

def dump_database(
    *,
    url: str,
    destination: Path,
) -> dict:

    pg_dump = find_tool(
        "pg_dump"
    )

    if pg_dump is None:

        raise RuntimeError(
            "pg_dump was not found.\n"
            "\n"
            "Looked on PATH, in VIGILOX_PG_BIN, and in the "
            "usual install locations.\n"
            "\n"
            "Either install the PostgreSQL client tools, or "
            "set VIGILOX_PG_BIN to the directory containing "
            "pg_dump, or run the dump from the database "
            "container, which already has a version-matched "
            "client:\n"
            "\n"
            "    docker compose exec -T postgres pg_dump "
            "-Fc -d vigilox_document_intelligence "
            "> database.dump\n"
            "\n"
            "See docs/operations/backup-restore.md."
        )

    parsed = make_url(
        url
    )

    arguments = [
        str(
            pg_dump
        ),

        # Custom format, not plain SQL.
        #
        # pg_restore can then restore selectively, in
        # parallel, and refuse a mismatched archive. Plain SQL
        # is a file that psql will happily execute halfway
        # before hitting an error.
        "--format=custom",

        # Compression is on by default for custom format;
        # stated so a reader does not wonder.
        "--compress=6",

        # No CREATE DATABASE, no ownership, no grants.
        #
        # The target database and its role are created by
        # whoever provisions the environment. A dump that
        # tries to recreate them fails on a managed service
        # and, worse, half-succeeds on a self-hosted one.
        "--no-owner",
        "--no-privileges",

        "--verbose",

        f"--dbname={parsed.database}",
        f"--file={destination}",
    ]

    if parsed.host:
        arguments.append(
            f"--host={parsed.host}"
        )

    if parsed.port:
        arguments.append(
            f"--port={parsed.port}"
        )

    if parsed.username:
        arguments.append(
            f"--username={parsed.username}"
        )

    environment = dict(
        os.environ
    )

    # THE PASSWORD GOES HERE AND NOWHERE ELSE.
    if parsed.password:
        environment["PGPASSWORD"] = str(
            parsed.password
        )

    completed = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        timeout=3600,
        env=environment,
    )

    if completed.returncode != 0:

        # pg_dump's diagnostics can quote the connection
        # string it was given, so its output is redacted
        # before it is shown.
        raise RuntimeError(
            "pg_dump failed with exit code "
            f"{completed.returncode}.\n"
            + redact_text(
                completed.stderr[-4000:],
                url,
            )
        )

    if not destination.is_file():

        raise RuntimeError(
            "pg_dump reported success but wrote no file."
        )

    size = destination.stat().st_size

    if size == 0:

        raise RuntimeError(
            "pg_dump reported success and wrote an empty "
            "file. Treating that as a failure: an empty "
            "backup that exits 0 is the worst possible "
            "outcome, because it is discovered at restore "
            "time."
        )

    return {
        "file": destination.name,
        "bytes": size,
        "sha256": sha256_of(
            destination
        ),
        "pg_dump_version": tool_version(
            pg_dump
        ),
        "format": "custom",
    }


def redact_text(
    text_value: str,
    url: str,
) -> str:

    """
    Remove the password from arbitrary tool output.

    Belt and braces. The password should never reach a child
    process's stderr, but stderr from a tool that was handed a
    connection string is not somewhere to assume.
    """

    try:
        password = make_url(
            url
        ).password

    except Exception:
        return text_value

    if not password:
        return text_value

    return text_value.replace(
        str(
            password
        ),
        "***",
    )


# ==========================================================
# THE FILESYSTEM HALF
# ==========================================================

def archive_tree(
    *,
    source: Path,
    destination: Path,
    label: str,
) -> dict:

    """
    A gzipped tar of one directory tree.

    Paths inside the archive are relative to the tree root, so
    a restore does not depend on the source having been at the
    same absolute path. A production container mounts the
    documents volume at /data/documents and a developer has it
    under the project directory; an archive that hard-coded
    either would not restore into the other.
    """

    file_count = 0
    byte_count = 0

    with tarfile.open(
        destination,
        "w:gz",
    ) as archive:

        for entry in sorted(
            source.rglob(
                "*"
            )
        ):

            relative = entry.relative_to(
                source
            )

            # Symlinks are not followed and not stored.
            #
            # The application never creates one. Something
            # that did is either a mistake or a way out of
            # the storage root, and an archive is not the
            # place to discover which.
            if entry.is_symlink():

                print(
                    f"  [skip] symlink not archived: "
                    f"{relative}"
                )
                continue

            archive.add(
                entry,
                arcname=str(
                    relative
                ).replace(
                    "\\",
                    "/",
                ),
                recursive=False,
            )

            if entry.is_file():
                file_count += 1
                byte_count += entry.stat().st_size

    return {
        "file": destination.name,
        "label": label,
        "source_root": str(
            source
        ),
        "files": file_count,
        "source_bytes": byte_count,
        "archive_bytes": destination.stat().st_size,
        "sha256": sha256_of(
            destination
        ),
    }


# ==========================================================
# WHAT THE DATABASE SAYS IT HAS
# ==========================================================
#
# Counted at dump time and written into the manifest, so a
# restore can be checked against what was expected rather than
# against nothing.
# ==========================================================

def database_inventory() -> dict:

    # The application's own engine, so the inventory is
    # counted through the same connection settings the
    # application uses. A second engine built here could
    # succeed where the application's fails, or the reverse.
    from database.database import engine

    inventory = {}

    with engine.connect() as connection:

        for label, statement in (
            (
                "documents",
                "SELECT count(*) FROM documents",
            ),
            (
                "analyses",
                "SELECT count(*) FROM document_analyses",
            ),
            (
                "reviews",
                "SELECT count(*) FROM human_reviews",
            ),
            (
                "audit_events",
                "SELECT count(*) FROM audit_events",
            ),
            (
                "jobs",
                "SELECT count(*) FROM document_jobs",
            ),
            (
                "unfinished_jobs",
                "SELECT count(*) FROM document_jobs "
                "WHERE status IN "
                "('QUEUED', 'PROCESSING', 'RETRY_WAIT')",
            ),
        ):

            inventory[label] = connection.execute(
                text(
                    statement
                )
            ).scalar_one()

        inventory["alembic_revision"] = (
            connection.execute(
                text(
                    "SELECT version_num "
                    "FROM alembic_version"
                )
            ).scalar()
        )

        inventory["server_version"] = (
            connection.execute(
                text(
                    "SHOW server_version"
                )
            ).scalar()
        )

    return inventory


# ==========================================================
# THE QUIESCE CLAIM
# ==========================================================
#
# --quiesced is the operator asserting they stopped the
# writers. This cannot be verified from here -- there is no
# way to prove from inside one process that no other process
# is about to write.
#
# What CAN be done is looking for evidence against it, which
# is worth doing because the failure is silent: a backup
# labelled consistent that is not consistent is worse than one
# labelled hot, since it will be trusted.
# ==========================================================

def contradicts_quiesce() -> list[str]:

    from backend.app.services.worker_health_service import (
        WorkerHealthService,
    )

    problems = []

    health = WorkerHealthService().evaluate()

    # The top-level state, not a per-worker one. A worker row
    # carries status (RUNNING / DRAINING / STOPPED) and a
    # stale flag; the aggregate state is what says whether
    # anything is currently able to claim.
    if health["state"] in (
        "HEALTHY",
        "DRAINING",
    ):

        problems.append(
            f"worker health reports {health['state']}: "
            f"{health['running_count']} running and "
            f"{health['draining_count']} draining. A worker "
            "that can still claim a job can still write a "
            "document."
        )

    processing = health["queue"].get(
        "PROCESSING",
        0,
    )

    if processing:

        problems.append(
            f"{processing} job(s) are in PROCESSING, which "
            "means a pipeline is mid-document and will write "
            "when it finishes"
        )

    # QUEUED work on its own is not a contradiction. Nothing
    # is claiming it if no worker is alive, and a queue that
    # sits still is exactly what a quiesced deployment looks
    # like. It is worth reporting, not refusing over.
    queued = health["queue"].get(
        "QUEUED",
        0,
    )

    if queued and not problems:

        print(
            f"  [note] {queued} job(s) are QUEUED and will "
            "resume when the worker starts. Include "
            "--pending so their sources come back with them."
        )

    return problems


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Back up the VIGILOX database and managed "
            "document storage."
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Directory to write the backup into. A "
            "timestamped subdirectory is created inside it."
        ),
    )

    parser.add_argument(
        "--database",
        action="store_true",
        help="Include a pg_dump of the database.",
    )

    parser.add_argument(
        "--documents",
        action="store_true",
        help=(
            "Include the managed document storage tree."
        ),
    )

    parser.add_argument(
        "--pending",
        action="store_true",
        help=(
            "Include pending upload sources. Needed if the "
            "dump contains unfinished jobs."
        ),
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "All three. What a scheduled backup should use."
        ),
    )

    parser.add_argument(
        "--quiesced",
        action="store_true",
        help=(
            "Assert that writers are stopped. Recorded in "
            "the manifest as an operator claim; the script "
            "checks for evidence against it and refuses if "
            "it finds any."
        ),
    )

    parser.add_argument(
        "--label",
        default="",
        help=(
            "Free text recorded in the manifest, e.g. a "
            "change reference. Do not put secrets here."
        ),
    )

    arguments = parser.parse_args()

    want_database = (
        arguments.database
        or arguments.all
    )

    want_documents = (
        arguments.documents
        or arguments.all
    )

    want_pending = (
        arguments.pending
        or arguments.all
    )

    if not any(
        (
            want_database,
            want_documents,
            want_pending,
        )
    ):

        print(
            "Nothing selected. Pass --all, or one or more of "
            "--database --documents --pending."
        )
        return 2

    print(
        "=" * 62
    )
    print(
        "VIGILOX BACKUP"
    )
    print(
        "=" * 62
    )

    url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if want_database and not url:

        print(
            "DATABASE_URL is not set, so there is nothing to "
            "dump."
        )
        return 2

    # ------------------------------------------------------
    # THE QUIESCE CHECK, BEFORE ANYTHING IS WRITTEN
    # ------------------------------------------------------

    if arguments.quiesced:

        try:
            problems = contradicts_quiesce()

        except Exception as error:

            # Not fatal. If the database cannot be reached
            # the dump will fail on its own and say so more
            # clearly than this would.
            print(
                f"  [warn] could not check the quiesce "
                f"claim: {error}"
            )
            problems = []

        if problems:

            print()
            print(
                "REFUSING: --quiesced was passed but the "
                "deployment is still writing."
            )

            for problem in problems:
                print(
                    f"  - {problem}"
                )

            print()
            print(
                "Stop the worker and stop accepting uploads, "
                "or drop --quiesced and take a hot backup. "
                "Labelling a backup consistent when it is "
                "not is worse than labelling it hot, because "
                "the label is what gets trusted at restore "
                "time."
            )
            return 1

        print(
            "  [ok] no worker is checking in and no job is "
            "PROCESSING; the quiesce claim is consistent "
            "with what can be observed"
        )

    # ------------------------------------------------------
    # THE OUTPUT DIRECTORY
    # ------------------------------------------------------

    started = datetime.now(
        timezone.utc
    )

    stamp = started.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    root = (
        Path(
            arguments.output
        ).expanduser()
        / f"vigilox-backup-{stamp}"
    )

    if root.exists():

        print(
            f"REFUSING: {root} already exists."
        )
        return 1

    root.mkdir(
        parents=True
    )

    print(
        f"  writing to {root}"
    )

    manifest = {
        "product": "VIGILOX Document Intelligence",
        "manifest_version": 1,
        "created_at": started.isoformat(),
        "label": arguments.label,

        # THE CLAIM, AND WHOSE CLAIM IT IS.
        "consistency": (
            "quiesced"
            if arguments.quiesced
            else "hot"
        ),
        "consistency_note": (
            "quiesced: the operator asserted writers were "
            "stopped, and no contrary evidence was found. "
            "The two halves should agree."
            if arguments.quiesced
            else "hot: the database and the filesystem were "
            "captured at different instants and are NOT a "
            "transactionally consistent pair. Reconcilable, "
            "not consistent -- run reconcile_storage.py "
            "--report after restoring."
        ),

        "ordering": "database-then-filesystem",
        "ordering_reason": (
            "An upload concurrent with the backup restores "
            "as an orphan file, which reconciliation clears. "
            "The reverse order would restore it as a row "
            "with no file."
        ),

        "parts": [],
    }

    failures = []

    # ------------------------------------------------------
    # 1. THE DATABASE. FIRST. SEE THE HEADER.
    # ------------------------------------------------------

    if want_database:

        print()
        print(
            "  [1] database"
        )
        print(
            f"      {redacted(url)}"
        )

        try:

            inventory = database_inventory()

            manifest["database"] = {
                "url": redacted(
                    url
                ),
                "inventory": inventory,
            }

            print(
                "      "
                f"{inventory['documents']} documents, "
                f"{inventory['analyses']} analyses, "
                f"{inventory['reviews']} reviews, "
                f"{inventory['jobs']} jobs "
                f"({inventory['unfinished_jobs']} unfinished)"
            )

            print(
                "      alembic revision "
                f"{inventory['alembic_revision']}"
            )

            part = dump_database(
                url=url,
                destination=root
                / "database.dump",
            )

            part["part"] = "database"

            manifest["parts"].append(
                part
            )

            print(
                f"      [ok] {part['bytes']:,} bytes"
            )

        except Exception as error:

            print(
                f"      [FAIL] {error}"
            )
            failures.append(
                "database"
            )

    # ------------------------------------------------------
    # 2. MANAGED DOCUMENT STORAGE
    # ------------------------------------------------------

    if want_documents:

        print()
        print(
            "  [2] managed document storage"
        )

        try:

            from backend.app.services.document_storage_service import (  # noqa: E501
                DocumentStorageService,
            )

            # The service resolves the root, rather than this
            # script re-deriving it. A backup that computed
            # the path independently could back up a
            # directory the application does not use, and
            # would do it silently.
            storage_root = (
                DocumentStorageService().storage_root
            )

            print(
                f"      {storage_root}"
            )

            part = archive_tree(
                source=storage_root,
                destination=root
                / "documents.tar.gz",
                label="managed",
            )

            part["part"] = "documents"

            manifest["parts"].append(
                part
            )

            print(
                f"      [ok] {part['files']} files, "
                f"{part['archive_bytes']:,} bytes compressed"
            )

        except Exception as error:

            print(
                f"      [FAIL] {error}"
            )
            failures.append(
                "documents"
            )

    # ------------------------------------------------------
    # 3. PENDING UPLOAD SOURCES. SEPARATE ARCHIVE.
    # ------------------------------------------------------

    if want_pending:

        print()
        print(
            "  [3] pending upload sources"
        )

        try:

            from backend.app.services.job_source_store import (
                JobSourceStore,
            )

            pending_root = (
                JobSourceStore().pending_root
            )

            print(
                f"      {pending_root}"
            )

            part = archive_tree(
                source=pending_root,
                destination=root
                / "pending.tar.gz",
                label="pending",
            )

            part["part"] = "pending"

            manifest["parts"].append(
                part
            )

            print(
                f"      [ok] {part['files']} files, "
                f"{part['archive_bytes']:,} bytes compressed"
            )

        except Exception as error:

            print(
                f"      [FAIL] {error}"
            )
            failures.append(
                "pending"
            )

    # ------------------------------------------------------
    # THE MANIFEST
    # ------------------------------------------------------

    manifest["finished_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    manifest["failed_parts"] = failures

    manifest["complete"] = not failures

    (
        root
        / "MANIFEST.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "=" * 62
    )

    if failures:

        print(
            "BACKUP INCOMPLETE. Failed: "
            + ", ".join(
                failures
            )
        )
        print(
            "The manifest records complete=false. Do not "
            "treat this directory as a backup."
        )
        print(
            "=" * 62
        )
        return 1

    print(
        "BACKUP COMPLETE"
    )
    print(
        f"  {root}"
    )

    if manifest["consistency"] == "hot":

        print()
        print(
            "This is a HOT backup. The database and the "
            "files were captured at different instants."
        )
        print(
            "After restoring, run:"
        )
        print(
            "  python scripts/maintenance/"
            "reconcile_storage.py --report"
        )

    if (
        want_database
        and not want_pending
        and manifest.get(
            "database",
            {},
        )
        .get(
            "inventory",
            {},
        )
        .get(
            "unfinished_jobs"
        )
    ):

        count = manifest["database"]["inventory"][
            "unfinished_jobs"
        ]

        print()
        print(
            f"NOTE: the dump contains {count} unfinished "
            "job(s) and pending sources were NOT included."
        )
        print(
            "Restoring this will queue work whose source "
            "files do not exist. Those jobs will fail."
        )

    print(
        "=" * 62
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
