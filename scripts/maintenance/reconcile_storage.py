import argparse
import json
import sys

from pathlib import Path


# ==========================================================
# RECONCILE MANAGED STORAGE AGAINST THE DATABASE
# PHASE 11.1
# ==========================================================
#
# StorageIntegrityService compares what is on disk under the
# managed storage root against what the documents table says
# should be there, and sorts every entry into one of four
# categories:
#
#   healthy_documents   a row and its file, agreeing
#   missing_storage     a row whose file is gone
#   orphan_storage      a managed file whose row is gone
#   unmanaged_entries   something in the tree that this
#                       application did not put there
#
# StorageReconciliationService then acts on exactly ONE of
# those four: orphan_storage.
#
#
# WHY THIS SCRIPT EXISTS
# ----------------------------------------------------------
# The Phase 11.1 structure audit found
# StorageReconciliationService reachable only from its own
# test. It is an operational tool with no operational way to
# run it -- which means the safety it provides was, in
# practice, unavailable to whoever would need it.
#
# Nothing about the service changed. This is the entrypoint it
# was missing.
#
#
# WHAT IT WILL NOT TOUCH
# ----------------------------------------------------------
# missing_storage is a row whose file has disappeared. That is
# a data-loss incident and possibly a restore, not a cleanup.
# Deleting the row would destroy the only remaining record
# that the document ever existed.
#
# unmanaged_entries is anything in the storage tree this
# application did not write. Deleting a file merely because it
# is unrecognised is how a misconfigured storage root becomes
# an outage.
#
# healthy_documents is, obviously, left alone.
#
# So this deletes managed files that no database row refers
# to, and nothing else. The service reports the other three
# counts so the operator can see what was deliberately left.
#
#
# DRY RUN IS THE DEFAULT
# ----------------------------------------------------------
# It prints what it would delete and exits. Deleting requires
# --apply, spelled out, because the files involved are real
# identity documents.
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


from backend.app.services.storage_reconciliation_service import (  # noqa: E402
    StorageReconciliationService,
)


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Delete managed storage files that no database "
            "row refers to. Reports, and does not touch, "
            "rows whose file is missing and entries this "
            "application did not write."
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually delete the orphaned files. Without "
            "this the script only reports."
        ),
    )

    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help=(
            "Print the full report as JSON instead of a "
            "summary."
        ),
    )

    return parser


def main(
    argv=None,
) -> int:

    arguments = build_parser().parse_args(
        argv
    )

    report = (
        StorageReconciliationService()
        .reconcile_orphans(
            dry_run=not arguments.apply,
        )
    )

    if arguments.as_json:

        print(
            json.dumps(
                report,
                indent=2,
                default=str,
            )
        )

        return (
            1
            if report["failed_count"]
            else 0
        )

    print(
        "=" * 62
    )
    print(
        "STORAGE RECONCILIATION"
    )
    print(
        "=" * 62
    )
    print(
        f"mode              {report['mode']}"
    )
    print(
        f"orphan candidates {report['candidate_count']}"
    )
    print(
        f"deleted           {report['deleted_count']}"
    )
    print(
        f"would delete      "
        f"{report['would_delete_count']}"
    )
    print(
        f"skipped           {report['skipped_count']}"
    )
    print(
        f"failed            {report['failed_count']}"
    )

    protected = report[
        "protected"
    ]

    print()
    print(
        "left alone on purpose:"
    )
    print(
        f"  rows whose file is missing   "
        f"{protected['missing_storage']}"
    )
    print(
        f"  entries this app did not write "
        f"{protected['unmanaged_entries']}"
    )
    print(
        f"  healthy documents            "
        f"{protected['healthy_documents']}"
    )

    if protected["missing_storage"]:

        print()
        print(
            "NOTE: "
            f"{protected['missing_storage']} document row(s) "
            "have no file on disk."
        )
        print(
            "      That is a data-loss condition, not "
            "something to clean up. Investigate before "
            "deleting anything."
        )

    if (
        report["mode"] == "DRY_RUN"
        and report["would_delete_count"]
    ):

        print()
        print(
            "Nothing was deleted. Re-run with --apply to "
            "delete the orphaned files."
        )

    print(
        "=" * 62
    )

    return (
        1
        if report["failed_count"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
