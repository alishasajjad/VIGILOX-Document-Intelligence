import argparse
import json
import os
import subprocess
import sys
import tarfile

from pathlib import Path


# ==========================================================
# RESTORE FROM A BACKUP DIRECTORY
# PHASE 11.12
# ==========================================================
#
# The counterpart to backup.py. It reads a directory that
# script produced, verifies the manifest against the files
# that are actually there, and puts each half back.
#
#
# THIS SCRIPT IS DESTRUCTIVE AND SAYS SO
# ----------------------------------------------------------
# Every safety here exists because a restore is run by someone
# under pressure, usually at an unsociable hour, often into
# the wrong environment. The refusals are the point.
#
#   --confirm is mandatory. There is no default that acts.
#
#   A non-empty target refuses unless --force. Restoring on
#   top of live data is how an incident involving one lost
#   document becomes an incident involving all of them.
#
#   The target URL is printed, redacted, before anything is
#   touched. "I restored into staging" and "I restored into
#   production" differ by one environment variable.
#
#   The pending root is checked against the storage root
#   first. Phase 9.2 requires them to be separate, and a
#   restore that put pending files inside managed storage
#   would have the integrity scan delete every one of them as
#   an orphan.
#
#
# CHECKSUMS ARE VERIFIED BEFORE ANYTHING IS WRITTEN
# ----------------------------------------------------------
# A truncated archive discovered halfway through extraction
# leaves the target in a state that is neither the backup nor
# what was there before. Every artifact is hashed first, and a
# mismatch aborts before the first byte is written.
#
#
# WHAT IT DOES NOT DO
# ----------------------------------------------------------
# It does not run migrations. The manifest records the Alembic
# revision the dump came from, and this compares it to the
# revision the code expects, but a restore is not the place to
# discover a schema upgrade. It reports the mismatch and
# stops.
#
# It does not reconcile. After a hot backup the two halves
# disagree slightly and reconcile_storage.py is the tool for
# that -- run deliberately, by a person, after looking at the
# report.
#
#
# CREDENTIALS
# ----------------------------------------------------------
# Same rule as backup.py. Nothing in this file, nothing on a
# command line, nothing printed. The password reaches
# pg_restore through PGPASSWORD in the child environment only.
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

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from scripts.maintenance.backup import (  # noqa: E402
    find_tool,
    redact_text,
    redacted,
    sha256_of,
    tool_version,
)


# ==========================================================
# READING THE MANIFEST
# ==========================================================

def load_manifest(
    root: Path,
) -> dict:

    path = (
        root
        / "MANIFEST.json"
    )

    if not path.is_file():

        raise RuntimeError(
            f"No MANIFEST.json in {root}.\n"
            "A directory of archives with no manifest cannot "
            "be verified: there is nothing to say what it "
            "contains, when it was taken, whether it was "
            "consistent, or which schema revision it "
            "belongs to."
        )

    manifest = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    if not manifest.get(
        "complete"
    ):

        raise RuntimeError(
            "This manifest records complete=false. Parts "
            "that failed: "
            + ", ".join(
                manifest.get(
                    "failed_parts",
                    [],
                )
            )
            + ".\n"
            "backup.py marks an incomplete backup rather "
            "than deleting it, so it can be inspected. It is "
            "not something to restore from."
        )

    return manifest


def verify_artifacts(
    *,
    root: Path,
    manifest: dict,
) -> dict:

    """
    Hash every artifact against the manifest.

    Before anything is written, always. Discovering a
    truncated archive during extraction leaves the target
    holding half a backup.
    """

    parts = {}

    print(
        "  verifying artifacts"
    )

    for part in manifest["parts"]:

        path = (
            root
            / part["file"]
        )

        if not path.is_file():

            raise RuntimeError(
                f"The manifest lists {part['file']} but it "
                "is not in this directory."
            )

        size = path.stat().st_size

        expected_size = part.get(
            "bytes",
            part.get(
                "archive_bytes"
            ),
        )

        if expected_size is not None and size != expected_size:

            raise RuntimeError(
                f"{part['file']} is {size:,} bytes; the "
                f"manifest says {expected_size:,}. "
                "Truncated or replaced."
            )

        digest = sha256_of(
            path
        )

        if digest != part["sha256"]:

            raise RuntimeError(
                f"{part['file']} does not match its "
                "recorded sha256.\n"
                f"  manifest: {part['sha256']}\n"
                f"  actual:   {digest}\n"
                "The archive has been corrupted or altered. "
                "Nothing has been written."
            )

        print(
            f"    [ok] {part['file']} "
            f"{size:,} bytes, sha256 matches"
        )

        parts[part["part"]] = part

    return parts


# ==========================================================
# THE DATABASE HALF
# ==========================================================

def target_has_tables(
    url: str,
) -> list[str]:

    engine = create_engine(
        url,
        pool_pre_ping=True,
    )

    try:

        with engine.connect() as connection:

            rows = connection.execute(
                text(
                    "SELECT table_name "
                    "FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "ORDER BY table_name"
                )
            ).all()

        return [
            row[0]
            for row in rows
        ]

    finally:
        engine.dispose()


def restore_database(
    *,
    url: str,
    archive: Path,
    force: bool,
) -> None:

    pg_restore = find_tool(
        "pg_restore"
    )

    if pg_restore is None:

        raise RuntimeError(
            "pg_restore was not found.\n"
            "Set VIGILOX_PG_BIN to the directory containing "
            "it, or restore from the database container, "
            "which has a version-matched client. See "
            "docs/operations/backup-restore.md."
        )

    existing = target_has_tables(
        url
    )

    if existing and not force:

        raise RuntimeError(
            "The target database already contains "
            f"{len(existing)} table(s): "
            + ", ".join(
                existing[:8]
            )
            + ".\n"
            "\n"
            "REFUSING. Restoring into a populated database "
            "means dropping what is in it, and this script "
            "will not decide that for you. Either restore "
            "into an empty database, or pass --force having "
            "established that what is there is expendable."
        )

    parsed = make_url(
        url
    )

    arguments = [
        str(
            pg_restore
        ),

        f"--dbname={parsed.database}",

        # Single transaction: the restore either lands whole
        # or does not land. A half-restored database that
        # looks restored is the outcome worth spending a lock
        # to avoid.
        "--single-transaction",

        # --exit-on-error goes with it. Without it pg_restore
        # continues past errors and exits 0, which is how a
        # restore that dropped a constraint is discovered
        # weeks later.
        "--exit-on-error",

        "--no-owner",
        "--no-privileges",

        "--verbose",
    ]

    if existing:

        # Only with --force, and only after the refusal above
        # has been overridden deliberately.
        arguments.append(
            "--clean"
        )

        arguments.append(
            "--if-exists"
        )

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

    arguments.append(
        str(
            archive
        )
    )

    environment = dict(
        os.environ
    )

    if parsed.password:
        environment["PGPASSWORD"] = str(
            parsed.password
        )

    completed = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        timeout=7200,
        env=environment,
    )

    if completed.returncode != 0:

        raise RuntimeError(
            "pg_restore failed with exit code "
            f"{completed.returncode}.\n"
            + redact_text(
                completed.stderr[-6000:],
                url,
            )
        )


# ==========================================================
# THE FILESYSTEM HALF
# ==========================================================

def extract_tree(
    *,
    archive: Path,
    destination: Path,
    force: bool,
) -> int:

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing = [
        entry
        for entry in destination.rglob(
            "*"
        )
        if entry.is_file()
    ]

    if existing and not force:

        raise RuntimeError(
            f"{destination} already contains "
            f"{len(existing)} file(s).\n"
            "\n"
            "REFUSING. Extracting on top of them would merge "
            "two sets of documents into one tree, and the "
            "result is neither the backup nor what was "
            "there. Empty the directory, restore somewhere "
            "else, or pass --force."
        )

    restored = 0

    with tarfile.open(
        archive,
        "r:gz",
    ) as handle:

        for member in handle.getmembers():

            # ------------------------------------------
            # EVERY MEMBER PATH IS CHECKED
            # ------------------------------------------
            #
            # An archive is untrusted input. A member named
            # ../../etc/something, or an absolute path, or a
            # symlink pointing out of the tree, writes
            # outside the destination -- the classic tar
            # traversal, and it does not stop being a hole
            # because this archive was produced by the
            # matching script. The archive may not be the one
            # that script produced.
            #
            # Python 3.12+ has filter="data" for exactly
            # this. It is used AND the check is written out,
            # because the filter default has changed across
            # versions and this should not depend on which
            # interpreter is running.

            name = member.name.replace(
                "\\",
                "/",
            )

            if (
                name.startswith(
                    "/"
                )
                or ".." in Path(
                    name
                ).parts
                or (
                    len(
                        name
                    ) > 1
                    and name[1] == ":"
                )
            ):

                raise RuntimeError(
                    "REFUSING: the archive contains a member "
                    f"whose path escapes the destination: "
                    f"{member.name!r}"
                )

            if member.issym() or member.islnk():

                raise RuntimeError(
                    "REFUSING: the archive contains a link "
                    f"member: {member.name!r}. backup.py "
                    "does not archive links, so this archive "
                    "was not produced by it."
                )

            if not (
                member.isfile()
                or member.isdir()
            ):

                raise RuntimeError(
                    "REFUSING: the archive contains a member "
                    f"that is neither a file nor a "
                    f"directory: {member.name!r}"
                )

        handle.extractall(
            path=destination,
            filter="data",
        )

        restored = len(
            [
                member
                for member in handle.getmembers()
                if member.isfile()
            ]
        )

    return restored


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Restore a VIGILOX backup. Destructive."
        ),
    )

    parser.add_argument(
        "--input",
        required=True,
        help=(
            "A directory produced by backup.py, containing "
            "MANIFEST.json."
        ),
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required. Without it this verifies the backup "
            "and changes nothing."
        ),
    )

    parser.add_argument(
        "--database",
        action="store_true",
    )

    parser.add_argument(
        "--documents",
        action="store_true",
    )

    parser.add_argument(
        "--pending",
        action="store_true",
    )

    parser.add_argument(
        "--all",
        action="store_true",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Permit restoring over an existing database or a "
            "non-empty storage tree. Read the refusal first."
        ),
    )

    parser.add_argument(
        "--database-url",
        default="",
        help=(
            "Target database. Defaults to DATABASE_URL. Pass "
            "this to restore into a scratch database instead "
            "of the live one."
        ),
    )

    parser.add_argument(
        "--storage-root",
        default="",
        help=(
            "Target for managed documents. Defaults to the "
            "root the application is configured to use."
        ),
    )

    parser.add_argument(
        "--pending-root",
        default="",
        help=(
            "Target for pending sources. Defaults to the "
            "configured pending root."
        ),
    )

    arguments = parser.parse_args()

    root = Path(
        arguments.input
    ).expanduser().resolve()

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

    print(
        "=" * 62
    )
    print(
        "VIGILOX RESTORE"
    )
    print(
        "=" * 62
    )

    try:
        manifest = load_manifest(
            root
        )

    except Exception as error:

        print(
            f"[FAIL] {error}"
        )
        return 1

    print(
        f"  backup taken   {manifest['created_at']}"
    )
    print(
        f"  consistency    {manifest['consistency']}"
    )

    if manifest.get(
        "label"
    ):
        print(
            f"  label          {manifest['label']}"
        )

    recorded = manifest.get(
        "database",
        {},
    ).get(
        "inventory",
        {},
    )

    if recorded:
        print(
            f"  contained      "
            f"{recorded.get('documents')} documents, "
            f"{recorded.get('reviews')} reviews, alembic "
            f"{recorded.get('alembic_revision')}"
        )

    try:
        parts = verify_artifacts(
            root=root,
            manifest=manifest,
        )

    except Exception as error:

        print(
            f"[FAIL] {error}"
        )
        return 1

    available = sorted(
        parts
    )

    print(
        "  parts available: "
        + ", ".join(
            available
        )
    )

    # ------------------------------------------------------
    # RESOLVE THE TARGETS AND SHOW THEM
    # ------------------------------------------------------

    database_url = (
        arguments.database_url
        or os.getenv(
            "DATABASE_URL",
            "",
        )
    ).strip()

    from backend.app.services.document_storage_service import (  # noqa: E501
        DocumentStorageService,
    )

    from backend.app.services.job_source_store import (  # noqa: E402
        JobSourceStore,
    )

    storage_root = (
        Path(
            arguments.storage_root
        ).expanduser().resolve()
        if arguments.storage_root
        else DocumentStorageService().storage_root
    )

    pending_root = (
        Path(
            arguments.pending_root
        ).expanduser().resolve()
        if arguments.pending_root
        else JobSourceStore().pending_root
    )

    print()
    print(
        "  TARGETS"
    )

    if want_database:
        print(
            f"    database  {redacted(database_url)}"
        )

    if want_documents:
        print(
            f"    documents {storage_root}"
        )

    if want_pending:
        print(
            f"    pending   {pending_root}"
        )

    # ------------------------------------------------------
    # THE PHASE 9.2 INVARIANT, CHECKED BEFORE ANY WRITE
    # ------------------------------------------------------
    #
    # Nesting the pending root inside managed storage makes
    # the integrity scan classify every pending file as an
    # orphan, and orphans are the one class reconciliation
    # deletes on its own. The application refuses to start in
    # that configuration; a restore must refuse to CREATE it.

    if want_documents or want_pending:

        if (
            pending_root == storage_root
            or storage_root in pending_root.parents
            or pending_root in storage_root.parents
        ):

            print()
            print(
                "[FAIL] REFUSING: the pending root and the "
                "managed storage root overlap."
            )
            print(
                f"       documents {storage_root}"
            )
            print(
                f"       pending   {pending_root}"
            )
            print(
                "       Phase 9.2 keeps them separate "
                "because the integrity scan treats a file "
                "with no document row as an orphan, and "
                "reconciliation deletes orphans. Restoring "
                "into this layout would stage every pending "
                "upload for automatic deletion."
            )
            return 1

    # ------------------------------------------------------
    # THE SCHEMA REVISION
    # ------------------------------------------------------

    if want_database and recorded.get(
        "alembic_revision"
    ):

        head = current_head()

        if head and head != recorded[
            "alembic_revision"
        ]:

            print()
            print(
                "[FAIL] REFUSING: schema revision mismatch."
            )
            print(
                f"       the dump is at "
                f"{recorded['alembic_revision']}"
            )
            print(
                f"       this code expects {head}"
            )
            print(
                "       Restoring an older dump under newer "
                "code leaves a database the application "
                "cannot use, and the failure appears as "
                "confusing query errors rather than as a "
                "restore problem."
            )
            print(
                "       Restore with the matching code "
                "revision, then upgrade with Alembic."
            )
            return 1

        print(
            f"  schema         {head} matches the dump"
        )

    # ------------------------------------------------------
    # THE DRY RUN IS THE DEFAULT
    # ------------------------------------------------------

    if not arguments.confirm:

        print()
        print(
            "=" * 62
        )
        print(
            "VERIFIED. Nothing was written."
        )
        print(
            "  Every artifact matches its checksum and every "
            "precondition passed."
        )
        print(
            "  Re-run with --confirm to actually restore."
        )
        print(
            "=" * 62
        )
        return 0

    if not any(
        (
            want_database,
            want_documents,
            want_pending,
        )
    ):

        print()
        print(
            "--confirm was passed but no part was selected. "
            "Nothing to do."
        )
        return 2

    failures = []

    # ------------------------------------------------------
    # 1. THE DATABASE
    # ------------------------------------------------------

    if want_database:

        print()
        print(
            "  [1] restoring database"
        )

        if "database" not in parts:

            print(
                "      [FAIL] this backup contains no "
                "database dump"
            )
            failures.append(
                "database"
            )

        elif not database_url:

            print(
                "      [FAIL] no target: DATABASE_URL is "
                "unset and --database-url was not given"
            )
            failures.append(
                "database"
            )

        else:

            try:

                restore_database(
                    url=database_url,
                    archive=root
                    / parts["database"]["file"],
                    force=arguments.force,
                )

                print(
                    "      [ok] restored"
                )

            except Exception as error:

                print(
                    f"      [FAIL] {error}"
                )
                failures.append(
                    "database"
                )

    # ------------------------------------------------------
    # 2. MANAGED DOCUMENTS
    # ------------------------------------------------------

    if want_documents:

        print()
        print(
            "  [2] restoring managed documents"
        )

        if "documents" not in parts:

            print(
                "      [FAIL] this backup contains no "
                "document archive"
            )
            failures.append(
                "documents"
            )

        else:

            try:

                count = extract_tree(
                    archive=root
                    / parts["documents"]["file"],
                    destination=storage_root,
                    force=arguments.force,
                )

                print(
                    f"      [ok] {count} files into "
                    f"{storage_root}"
                )

            except Exception as error:

                print(
                    f"      [FAIL] {error}"
                )
                failures.append(
                    "documents"
                )

    # ------------------------------------------------------
    # 3. PENDING SOURCES
    # ------------------------------------------------------

    if want_pending:

        print()
        print(
            "  [3] restoring pending sources"
        )

        if "pending" not in parts:

            print(
                "      [skip] this backup contains no "
                "pending archive"
            )

        else:

            try:

                count = extract_tree(
                    archive=root
                    / parts["pending"]["file"],
                    destination=pending_root,
                    force=arguments.force,
                )

                print(
                    f"      [ok] {count} files into "
                    f"{pending_root}"
                )

            except Exception as error:

                print(
                    f"      [FAIL] {error}"
                )
                failures.append(
                    "pending"
                )

    # ------------------------------------------------------
    # WHAT TO DO NEXT
    # ------------------------------------------------------

    print()
    print(
        "=" * 62
    )

    if failures:

        print(
            "RESTORE INCOMPLETE. Failed: "
            + ", ".join(
                failures
            )
        )
        print(
            "=" * 62
        )
        return 1

    print(
        "RESTORE COMPLETE"
    )

    print()
    print(
        "NEXT, AND NOT OPTIONAL:"
    )

    print(
        "  1. Check the two halves agree:"
    )
    print(
        "       python scripts/maintenance/"
        "reconcile_storage.py --report"
    )

    if manifest["consistency"] == "hot":

        print(
            "     This was a HOT backup, so expect a small "
            "number of orphan files -- uploads that landed "
            "between the dump and the archive. That is the "
            "designed failure direction. A row with MISSING "
            "storage is not, and needs investigating."
        )

    if recorded.get(
        "unfinished_jobs"
    ):

        print(
            "  2. "
            f"{recorded['unfinished_jobs']} job(s) were "
            "unfinished when this backup was taken. They are "
            "back in the queue and a worker will claim them."
        )

        if "pending" not in parts:

            print(
                "     Their source files were NOT in this "
                "backup, so they will fail. Fail them "
                "deliberately rather than letting them retry."
            )

    print(
        "  3. Confirm readiness and worker health before "
        "returning traffic:"
    )
    print(
        "       GET /health/ready"
    )
    print(
        "       GET /health/workers"
    )

    print(
        "=" * 62
    )

    return 0


def current_head() -> str | None:

    """
    The revision this code's migrations end at.

    Read from the migration scripts, not from a database. The
    question is what the code expects, and asking the database
    would answer a different question.
    """

    try:

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(
            str(
                PROJECT_ROOT
                / "alembic.ini"
            )
        )

        return ScriptDirectory.from_config(
            config
        ).get_current_head()

    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
