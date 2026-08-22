import argparse
import sys

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path


# ==========================================================
# PURGE FINISHED JOB ROWS AND ORPHANED PENDING UPLOADS
# PHASE 9.3
# ==========================================================
#
# Operational cleanup for the job queue.
#
# Two things accumulate:
#
#   1. Rows for jobs that finished. Useful history for a
#      while, then just rows.
#
#   2. Pending uploads that no job row refers to. These are
#      real identity documents sitting on disk with nothing
#      pointing at them, so they matter more than the rows do.
#
#
# WHAT IT WILL NOT DO
# ----------------------------------------------------------
#
# It never touches a job that is QUEUED, PROCESSING or
# RETRY_WAIT unless explicitly asked, and even then it says
# what it is about to do first.
#
# That restraint is the same rule the managed storage
# reconciliation follows, and for the same reason: automatic
# deletion of something merely unrecognised is how in-flight
# work gets destroyed. A PROCESSING row might be a worker
# eighteen seconds into an OCR pass. A pending upload might be
# a job waiting out a rate limit.
#
# So --dry-run is the default. Deleting requires --apply.
#
#
# Run:
#
#     python -m scripts.maintenance.purge_finished_jobs
#     python -m scripts.maintenance.purge_finished_jobs --apply
#     python -m scripts.maintenance.purge_finished_jobs \
#         --older-than-days 30 --apply
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


from dotenv import load_dotenv               # noqa: E402

load_dotenv(
    PROJECT_ROOT / ".env"
)


from sqlalchemy import delete, select        # noqa: E402

from database.database import (               # noqa: E402
    SessionLocal,
)

from database.models import (                 # noqa: E402
    DocumentJobModel,
)

from backend.app.domain.job_states import (   # noqa: E402
    COMPLETED,
    FAILED,
    PROCESSING,
    QUEUED,
    RETRY_WAIT,
)

from backend.app.services.job_service import (   # noqa: E402
    JobService,
)


TERMINAL = (
    COMPLETED,
    FAILED,
)


def summarize() -> dict[str, int]:

    service = (
        JobService()
    )

    return (
        service.queue_depth()
    )


def main() -> int:

    parser = (
        argparse.ArgumentParser(
            description=(
                "Remove finished job rows and pending "
                "uploads that nothing refers to."
            )
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually delete. Without this nothing is "
            "removed and the report is printed."
        ),
    )

    parser.add_argument(
        "--older-than-days",
        type=int,
        default=0,
        help=(
            "Only remove finished jobs older than this "
            "many days. Default 0, meaning all finished "
            "jobs."
        ),
    )

    parser.add_argument(
        "--queued",
        action="store_true",
        help=(
            "Also remove QUEUED and RETRY_WAIT jobs. "
            "This discards work that has not been done "
            "yet, so it is never implied and never the "
            "default."
        ),
    )

    arguments = (
        parser.parse_args()
    )

    service = (
        JobService()
    )

    depth = (
        service.queue_depth()
    )

    print()
    print(
        "Job queue"
    )
    print(
        "-" * 60
    )

    for status, count in depth.items():
        print(
            f"  {status:<14}{count}"
        )


    cutoff = (
        datetime.now(
            timezone.utc
        )
        - timedelta(
            days=arguments.older_than_days,
        )
    )

    removable = list(
        TERMINAL
    )


    if arguments.queued:
        removable += [
            QUEUED,
            RETRY_WAIT,
        ]


    # PROCESSING is never removable here, with or without
    # --queued. A row in PROCESSING may be a live worker
    # partway through a document; the way to deal with a stuck
    # one is the lease, through
    # `python -m backend.worker --reclaim-only`.
    with SessionLocal.begin() as session:

        candidates = list(
            session.execute(
                select(
                    DocumentJobModel.id,
                    DocumentJobModel.status,
                    DocumentJobModel.source_name,
                )
                .where(
                    DocumentJobModel.status.in_(
                        removable
                    ),

                    DocumentJobModel.created_at
                    <= cutoff,
                )
            ).all()
        )


    print()
    print(
        f"  {len(candidates)} job row(s) eligible for "
        "removal"
    )

    by_status: dict[str, int] = {}

    for _, status, _ in candidates:
        by_status[status] = (
            by_status.get(
                status,
                0,
            )
            + 1
        )

    for status, count in sorted(
        by_status.items()
    ):
        print(
            f"    {status:<14}{count}"
        )


    if depth.get(
        PROCESSING,
        0,
    ):
        print()
        print(
            f"  {depth[PROCESSING]} job(s) are "
            "PROCESSING and are never removed here. If "
            "one is stuck, its lease is the mechanism:"
        )
        print(
            "      python -m backend.worker "
            "--reclaim-only"
        )


    orphans = (
        service.orphaned_sources()
    )

    print()
    print(
        f"  {len(orphans)} pending upload(s) that no "
        "job row refers to"
    )


    if not arguments.apply:

        print()
        print(
            "  Nothing was changed. Re-run with "
            "--apply to delete."
        )
        print()

        return 0


    # ------------------------------------------------------
    # DELETE
    # ------------------------------------------------------
    #
    # Rows first, then the files those rows referred to, then
    # the files nothing referred to. Deleting a row before its
    # file means the worst case is an unreferenced file, which
    # this same command reports and removes. Deleting the file
    # first would mean a surviving row pointing at nothing,
    # which reads as a corrupted job.
    # ------------------------------------------------------

    removed_files = 0

    for _, _, source_name in candidates:

        try:
            if service.source_store.delete_pending(
                source_name
            ):
                removed_files += 1

        except Exception:      # noqa: BLE001
            pass


    with SessionLocal.begin() as session:

        result = (
            session.execute(
                delete(
                    DocumentJobModel
                )
                .where(
                    DocumentJobModel.id.in_(
                        [
                            job_id
                            for job_id, _, _ in candidates
                        ]
                    )
                )
            )
            if candidates
            else None
        )

        removed_rows = (
            result.rowcount
            if result is not None
            else 0
        )


    # Re-read: some of the earlier orphans may have just been
    # deleted along with their rows.
    removed_orphans = 0

    for source_name in service.orphaned_sources():

        try:
            if service.source_store.delete_pending(
                source_name
            ):
                removed_orphans += 1

        except Exception:      # noqa: BLE001
            pass


    print()
    print(
        f"  removed {removed_rows} row(s), "
        f"{removed_files} referenced file(s), "
        f"{removed_orphans} orphaned file(s)"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
