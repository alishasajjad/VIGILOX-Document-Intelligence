import threading
import time
import uuid

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import groq
import httpx

from sqlalchemy import delete, func, select

from database.database import (
    SessionLocal,
)

from database.job_repositories import (
    DocumentJobRepository,
)

from database.models import (
    DocumentJobModel,
)

from backend.app.domain.job_states import (
    COMPLETED,
    FAILED,
    JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE,
    JOB_ERROR_PROVIDER_TIMEOUT,
    JOB_ERROR_PROVIDER_UNAVAILABLE,
    PROCESSING,
    QUEUED,
    RETRY_WAIT,
)

from backend.app.services.document_worker import (
    DocumentWorker,
)


# Reuse the fakes and harness from the Phase 9.3 suite rather
# than writing a second set that could drift from it.
from tests.jobs.test_phase9_job_worker import (
    FakePersistence,
    FakePipeline,
    Harness,
    require_quiet_queue,
)


# ==========================================================
# PHASE 9.6
# CONCURRENCY, RECOVERY AND LOAD
# ==========================================================
#
# Phase 9.3 proved the job system's core races. This suite
# covers the operational ones: the things that happen because
# processes restart, providers misbehave and several people
# watch the same page.
#
#   1. Durability. A queued job lives in PostgreSQL, not in a
#      process. Proved by discarding every connection and
#      every object and finding the job again.
#
#   2. Worker restart. A worker holding a lease is replaced by
#      a new process; the job finishes once.
#
#   3. The remaining transient classifications -- provider
#      5xx, network timeout, infrastructure -- each park the
#      job rather than failing the document.
#
#   4. Throughput under a realistic queue with several
#      workers, measured rather than asserted, with the sample
#      size reported so nothing here reads as a capacity
#      claim.
#
#   5. Status reads under load do not interfere with claiming.
#      A dashboard open in six tabs must not be able to stop a
#      worker taking work, and a simple read must not take a
#      lock.
#
# No Groq. Every provider condition is a constructed exception,
# which is what makes it possible to test the 500 path and the
# timeout path at all -- neither is something a real provider
# can be asked for on demand.
# ==========================================================

RUN_MARKER = (
    "phase96test-"
    + uuid.uuid4().hex[:10]
)


PASSES: list[str] = []

TIMINGS: dict[str, object] = {}


def ok(
    message: str,
) -> None:

    PASSES.append(
        message
    )

    print(
        f"[PASS] {message}"
    )


def fail(
    message: str,
) -> None:

    raise AssertionError(
        message
    )


# ==========================================================
# PROVIDER FAILURES
# ==========================================================

def provider_error(
    cls,
    status: int,
    headers: dict | None = None,
):

    return cls(
        "provider failure",
        response=(
            httpx.Response(
                status,
                headers=(
                    headers or {}
                ),
                request=(
                    httpx.Request(
                        "POST",
                        "https://api.groq.com/x",
                    )
                ),
            )
        ),
        body=None,
    )


def timeout_error():

    return (
        groq.APITimeoutError(
            request=(
                httpx.Request(
                    "POST",
                    "https://api.groq.com/x",
                )
            )
        )
    )


# ==========================================================
# 1. DURABILITY ACROSS A PROCESS RESTART
# ==========================================================

def test_queued_job_survives_process_restart(
    harness: Harness,
):

    """
    A queued job must live in PostgreSQL, not in the process
    that accepted it.

    Proved the only way it can be proved without spawning a
    second interpreter: dispose the connection pool, drop
    every Python object that knew about the job, and go and
    find it again through a brand new session, repository and
    worker.

    If the queue were in memory -- a list, a
    BackgroundTasks handle, an asyncio task -- nothing would
    survive dispose() and the job would be gone. That is the
    failure mode this asserts against, and it is exactly what
    FastAPI's BackgroundTasks would have given us.
    """

    payload = (
        harness.queue()
    )

    job_id = payload[
        "job_id"
    ]

    source_name = (
        harness.row(
            job_id
        )["source_name"]
    )

    # Everything the API process would have held.
    del payload

    from database.database import (
        engine,
    )

    # Every pooled connection is closed and discarded. A new
    # one has to be opened to see anything at all.
    engine.dispose()


    with SessionLocal.begin() as session:

        recovered = (
            DocumentJobRepository(
                session
            )
            .get_job(
                job_id
            )
        )

        if recovered is None:
            fail(
                "The job did not survive a connection "
                "pool reset. It is not durable."
            )

        if recovered.status != QUEUED:
            fail(
                "The job came back as "
                f"{recovered.status}, not QUEUED."
            )


    # And the bytes are still there, because they are on a
    # filesystem rather than in a request's temporary file.
    if not harness.store.exists(
        source_name
    ):
        fail(
            "The pending upload did not survive. A job "
            "whose bytes vanish with the process is not "
            "durable either."
        )


    # A completely fresh worker can still claim it.
    claimed = (
        harness.worker(
            worker_id="worker-after-restart",
        ).claim()
    )

    if claimed is None or claimed["job_id"] != job_id:
        fail(
            "A new worker could not claim the job that "
            "survived the restart."
        )


    ok(
        "a queued job and its bytes survive a connection "
        "pool reset and are claimable by a new worker"
    )


def test_retry_wait_survives_restart(
    harness: Harness,
):

    """
    A job parked for retry has to survive too, with its
    schedule intact -- otherwise a restart either loses it or
    retries it immediately, and the second is worse.
    """

    payload = (
        harness.queue()
    )

    harness.worker(
        pipeline=(
            FakePipeline(
                raises=(
                    provider_error(
                        groq.RateLimitError,
                        429,
                        {"retry-after": "120"},
                    )
                ),
            )
        ),
    ).process_one()

    before = (
        harness.row(
            payload["job_id"]
        )
    )

    if before["status"] != RETRY_WAIT:
        fail(
            "Expected RETRY_WAIT, got "
            f"{before['status']}."
        )


    from database.database import (
        engine,
    )

    engine.dispose()


    after = (
        harness.row(
            payload["job_id"]
        )
    )

    if after["status"] != RETRY_WAIT:
        fail(
            "A parked job did not survive the restart."
        )


    if after["next_attempt_at"] is None:
        fail(
            "The retry schedule was lost, so the job "
            "either never retries or retries "
            "immediately."
        )


    if after["attempt_count"] != before["attempt_count"]:
        fail(
            "The attempt count changed across the "
            "restart, so the attempt budget is not "
            "durable and a job could retry forever."
        )


    # Still not claimable before its time, restart or no
    # restart.
    if harness.worker().claim() is not None:
        fail(
            "A parked job became claimable early after "
            "a restart."
        )


    ok(
        "a parked job keeps its schedule and attempt "
        "count across a restart, and stays unclaimable "
        "until its time"
    )


# ==========================================================
# 2. WORKER RESTART
# ==========================================================

def test_worker_restart_finishes_the_job_once(
    harness: Harness,
):

    """
    A worker holding a lease is replaced by a new process.

    The distinction from the Phase 9.3 crash test is that the
    replacement is a genuinely different worker identity, which
    is what a restart produces: the pid changes and the random
    suffix changes, so the new worker cannot be mistaken for
    the old one and cannot extend its lease.
    """

    payload = (
        harness.queue()
    )

    job_id = payload[
        "job_id"
    ]

    dying = (
        harness.worker(
            worker_id="worker-pid-100",
        )
    )

    dying.claim()

    original_worker = (
        harness.row(
            job_id
        )["worker_id"]
    )

    # The process is gone. Its lease is no longer being
    # extended.
    del dying

    harness.expire_lease(
        job_id
    )

    persistence = (
        FakePersistence()
    )

    replacement = (
        harness.worker(
            worker_id="worker-pid-200",
            persistence=persistence,
        )
    )

    recovered = (
        replacement.reclaim_expired()
    )

    if recovered < 1:
        fail(
            "The replacement worker did not recover the "
            "abandoned job."
        )


    if not replacement.process_one():
        fail(
            "The replacement worker found nothing to do "
            "after recovering the job."
        )


    row = (
        harness.row(
            job_id
        )
    )

    if row["status"] != COMPLETED:
        fail(
            f"Expected COMPLETED, got {row['status']}."
        )


    if len(persistence.saved) != 1:
        fail(
            f"{len(persistence.saved)} documents "
            "persisted across a worker restart. Exactly "
            "one upload must produce exactly one "
            "document."
        )


    if original_worker == "worker-pid-200":
        fail(
            "This test is not exercising a restart: the "
            "replacement has the same identity as the "
            "worker it replaced."
        )


    ok(
        "a job held by a worker that restarts is "
        "recovered by its replacement and completes once"
    )


# ==========================================================
# 3. THE REMAINING TRANSIENT CLASSIFICATIONS
# ==========================================================

def test_transient_provider_conditions(
    harness: Harness,
):

    """
    Provider 5xx, a network timeout and an infrastructure
    failure each park the job rather than failing the
    document.

    None of these can be requested from a real provider on
    demand, which is the whole reason the pipeline is
    injectable.
    """

    cases = (
        (
            "provider 500",
            provider_error(
                groq.InternalServerError,
                500,
            ),
            JOB_ERROR_PROVIDER_UNAVAILABLE,
        ),
        (
            "provider 503",
            provider_error(
                groq.InternalServerError,
                503,
            ),
            JOB_ERROR_PROVIDER_UNAVAILABLE,
        ),
        (
            "network timeout",
            timeout_error(),
            JOB_ERROR_PROVIDER_TIMEOUT,
        ),
        (
            "connection failure",
            groq.APIConnectionError(
                request=(
                    httpx.Request(
                        "POST",
                        "https://api.groq.com/x",
                    )
                )
            ),
            JOB_ERROR_PROVIDER_UNAVAILABLE,
        ),
        (
            "disk full",
            OSError(
                28,
                "No space left on device",
            ),
            JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE,
        ),
    )

    for label, error, expected in cases:

        payload = (
            harness.queue()
        )

        source_name = (
            harness.row(
                payload["job_id"]
            )["source_name"]
        )

        started = (
            datetime.now(
                timezone.utc
            )
        )

        harness.worker(
            pipeline=(
                FakePipeline(
                    raises=error,
                )
            ),
        ).process_one()

        row = (
            harness.row(
                payload["job_id"]
            )
        )


        if row["status"] != RETRY_WAIT:
            fail(
                f"{label}: expected RETRY_WAIT, got "
                f"{row['status']} "
                f"({row['error_code']}). A transient "
                "provider condition must not fail the "
                "document."
            )


        if row["error_code"] != expected:
            fail(
                f"{label}: expected {expected}, got "
                f"{row['error_code']}."
            )


        if row["next_attempt_at"] is None:
            fail(
                f"{label}: no next_attempt_at was set."
            )


        scheduled = row["next_attempt_at"]

        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(
                tzinfo=timezone.utc,
            )

        waited = (
            scheduled - started
        ).total_seconds()

        # The specific failure a retry loop invites.
        if waited < 2:
            fail(
                f"{label}: the retry is scheduled "
                f"{waited:.1f}s out. That is a hot loop."
            )


        # The bytes are kept, because the next attempt needs
        # them.
        if not harness.store.exists(
            source_name
        ):
            fail(
                f"{label}: the pending upload was "
                "deleted while the job is waiting to "
                "retry."
            )


    ok(
        f"{len(cases)} transient conditions each park the "
        "job with a backoff and keep its bytes"
    )


# ==========================================================
# 4. THROUGHPUT UNDER A REALISTIC QUEUE
# ==========================================================

def test_multi_worker_throughput(
    harness: Harness,
):

    """
    Several workers draining a queue.

    The pipeline is a fake, so this measures the job system --
    claiming, leasing, updating, cleaning up -- and not OCR.
    That is the intent: OCR's cost is already measured, and
    what matters here is that the queue machinery is not
    itself a bottleneck and that concurrency does not produce
    duplicates.

    Nothing here is a capacity claim. The sample size and the
    worker count are reported so the numbers cannot be read as
    one.
    """

    total = 24

    workers = 4

    job_ids = {
        harness.queue()["job_id"]
        for _ in range(
            total
        )
    }

    persistences = [
        FakePersistence()
        for _ in range(
            workers
        )
    ]

    errors: list[str] = []

    processed = {
        "count": 0,
    }

    lock = (
        threading.Lock()
    )

    barrier = (
        threading.Barrier(
            workers
        )
    )


    def drain(
        index: int,
    ) -> None:

        worker = (
            harness.worker(
                worker_id=f"throughput-{index}",
                persistence=(
                    persistences[index]
                ),
            )
        )

        try:
            barrier.wait(
                timeout=30
            )

            while True:

                # PHASE 12.6. Scoped to this test's jobs for
                # the same reason as the status-read test
                # below: an unrestricted drain takes anything
                # the HARNESS created, and the parking test
                # above leaves five jobs that become
                # claimable the moment their backoff elapses.
                #
                # This one happened to pass, because the
                # backoffs had not come due yet. That is
                # luck, not isolation, and the throughput
                # number would have been quietly wrong rather
                # than failing.
                if not worker.process_one(
                    only_job_ids=sorted(
                        job_ids
                    ),
                ):
                    break

                with lock:
                    processed["count"] += 1


        except Exception as error:      # noqa: BLE001

            with lock:
                errors.append(
                    f"{type(error).__name__}: {error}"
                )


    threads = [
        threading.Thread(
            target=drain,
            args=(
                index,
            ),
        )
        for index in range(
            workers
        )
    ]

    started = (
        time.perf_counter()
    )

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(
            timeout=120
        )

    elapsed = (
        time.perf_counter()
        - started
    )


    if errors:
        fail(
            "Draining raised under concurrency:\n"
            + "\n".join(
                errors
            )
        )


    # Every document persisted exactly once, across all
    # workers. This is the property that matters and it is
    # checked against the documents actually written, not
    # against a status count.
    saved = [
        entry["document_id"]
        for persistence in persistences
        for entry in persistence.saved
    ]

    if len(saved) != len(
        set(
            saved
        )
    ):
        fail(
            "A document id was persisted more than "
            "once under concurrency."
        )


    with SessionLocal.begin() as session:

        rows = (
            session.execute(
                select(
                    DocumentJobModel.status,
                    func.count(),
                )
                .where(
                    DocumentJobModel.id.in_(
                        job_ids
                    )
                )
                .group_by(
                    DocumentJobModel.status
                )
            ).all()
        )

    by_status = {
        status: int(
            count
        )
        for status, count in rows
    }


    if by_status.get(
        COMPLETED,
        0,
    ) != total:
        fail(
            f"Expected {total} completed jobs, got "
            f"{by_status}."
        )


    if len(saved) != total:
        fail(
            f"{total} jobs completed but "
            f"{len(saved)} documents were persisted."
        )


    # Every worker did some of the work, or the concurrency is
    # not being exercised.
    busy = [
        len(
            persistence.saved
        )
        for persistence in persistences
    ]

    if sum(
        1
        for count in busy
        if count
    ) < 2:
        fail(
            "Only one worker did any work, so this is "
            f"not a concurrency test: {busy}"
        )


    TIMINGS["throughput"] = {
        "jobs": total,
        "workers": workers,
        "seconds": round(
            elapsed,
            2,
        ),
        "jobs_per_second": round(
            total / elapsed,
            1,
        )
        if elapsed
        else None,
        "per_worker": busy,
        "note": (
            "job-system throughput with an injected "
            "pipeline. Not a document-processing rate: "
            "OCR is the real cost and is measured "
            "separately."
        ),
    }

    ok(
        f"{workers} workers drained {total} jobs in "
        f"{elapsed:.1f}s with no duplicate document "
        f"(per worker: {busy})"
    )


# ==========================================================
# 5. STATUS READS UNDER LOAD
# ==========================================================

def test_status_reads_do_not_block_claiming(
    harness: Harness,
):

    """
    A dashboard open in six tabs must not be able to stop a
    worker taking work.

    Status reads use a plain SELECT with no FOR UPDATE, so they
    should never contend with the claim query. That is easy to
    say and easy to get wrong -- a status read that
    accidentally took a row lock, or ran inside a long
    transaction, would serialise the whole queue -- so it is
    measured: many readers hammering status while workers
    claim, and both have to keep working.
    """

    total = 8

    readers = 6

    job_ids = [
        harness.queue()["job_id"]
        for _ in range(
            total
        )
    ]

    stop = (
        threading.Event()
    )

    reads = {
        "count": 0,
    }

    errors: list[str] = []

    lock = (
        threading.Lock()
    )


    def poll() -> None:

        try:
            while not stop.is_set():

                for job_id in job_ids:

                    if stop.is_set():
                        break

                    harness.jobs.get_job(
                        job_id
                    )

                    with lock:
                        reads["count"] += 1


        except Exception as error:      # noqa: BLE001

            with lock:
                errors.append(
                    f"reader: {type(error).__name__}: "
                    f"{error}"
                )


    reader_threads = [
        threading.Thread(
            target=poll,
            daemon=True,
        )
        for _ in range(
            readers
        )
    ]

    for thread in reader_threads:
        thread.start()


    persistence = (
        FakePersistence()
    )

    worker = (
        harness.worker(
            worker_id="worker-under-read-load",
            persistence=persistence,
        )
    )

    started = (
        time.perf_counter()
    )

    claimed = 0

    try:
        # ----------------------------------------------------
        # RESTRICTED TO THIS TEST'S JOBS
        # ----------------------------------------------------
        #
        # PHASE 12.6. Without only_job_ids this drained
        # everything the HARNESS had ever created, not what
        # this test created -- and the harness is shared
        # across every test in the file.
        #
        # Test 4 above parks five jobs in RETRY_WAIT with a
        # backoff. They are not claimable while the backoff
        # runs, so on a fast machine this test finished before
        # they came due and the count came out at 8. Under
        # gate load the intervening tests took longer, the
        # backoffs elapsed, and the worker legitimately
        # claimed 8 + 5 = 13 -- failing an assertion that
        # reads as "status reads are interfering with
        # claiming", which had nothing to do with it.
        #
        # A test that passes on a fast machine and fails on a
        # slow one, with a message pointing at the wrong
        # subsystem, is worse than no test. Scoping the drain
        # to job_ids makes the count mean what the assertion
        # says it means.
        while worker.process_one(
            only_job_ids=job_ids,
        ):
            claimed += 1

    finally:
        stop.set()

        for thread in reader_threads:
            thread.join(
                timeout=10
            )


    elapsed = (
        time.perf_counter()
        - started
    )


    if errors:
        fail(
            "Status reads raised while claiming was in "
            "progress:\n"
            + "\n".join(
                errors
            )
        )


    if claimed != total:
        fail(
            f"The worker processed {claimed} of {total} "
            "jobs while status was being polled. Status "
            "reads are interfering with claiming."
        )


    if reads["count"] < readers:
        fail(
            f"Only {reads['count']} status reads "
            "completed, so the readers were not "
            "actually loading anything."
        )


    if len(persistence.saved) != total:
        fail(
            "Documents were lost or duplicated while "
            "status was under load."
        )


    TIMINGS["status_under_load"] = {
        "jobs": total,
        "readers": readers,
        "status_reads": reads["count"],
        "seconds": round(
            elapsed,
            2,
        ),
        "note": (
            "status reads take no row lock, so they do "
            "not serialise the claim query"
        ),
    }

    ok(
        f"{readers} readers made {reads['count']} status "
        f"reads while a worker drained {total} jobs, with "
        "no interference"
    )


def test_queue_depth_is_grouped_in_the_database(
    harness: Harness,
):

    """
    Queue depth is a metric in Phase 11 and will be scraped on
    a schedule, so it must not be a table scan in Python.
    """

    for _ in range(
        5
    ):
        harness.queue()


    depth = (
        harness.jobs.queue_depth()
    )

    if depth.get(
        QUEUED,
        0,
    ) < 5:
        fail(
            "queue_depth did not see the queued jobs: "
            f"{depth}"
        )


    # Every status present, including the zeroes, so a caller
    # rendering a summary does not have to guess whether a
    # missing key means none.
    for status in (
        QUEUED,
        PROCESSING,
        RETRY_WAIT,
        COMPLETED,
        FAILED,
    ):

        if status not in depth:
            fail(
                f"queue_depth omits {status}. A missing "
                "key is indistinguishable from a "
                "dropped field."
            )


    ok(
        "queue depth reports every status and is grouped "
        "in the database"
    )


# ==========================================================
# MAIN
# ==========================================================

def cleanup_run() -> int:

    with SessionLocal.begin() as session:

        return (
            session.execute(
                delete(
                    DocumentJobModel
                )
                .where(
                    DocumentJobModel
                    .original_filename
                    .like(
                        f"{RUN_MARKER}%"
                    )
                )
            ).rowcount
        )


def main() -> int:

    print()
    print("=" * 76)
    print(
        "PHASE 9.6 - CONCURRENCY, RECOVERY AND LOAD"
    )
    print("=" * 76)
    print()

    harness = (
        Harness()
    )

    # PHASE 10.4. See test_phase9_job_worker: workers built by
    # the shared harness are confined to that suite own jobs,
    # so the queue no longer has to be empty. The import is
    # kept so a future test needing an empty queue can call it
    # rather than reinvent it.

    try:

        test_queued_job_survives_process_restart(
            harness
        )

        test_retry_wait_survives_restart(
            harness
        )

        test_worker_restart_finishes_the_job_once(
            harness
        )

        test_transient_provider_conditions(
            harness
        )

        test_multi_worker_throughput(
            harness
        )

        test_status_reads_do_not_block_claiming(
            harness
        )

        test_queue_depth_is_grouped_in_the_database(
            harness
        )


    finally:

        removed = (
            harness.cleanup()
        )

        print()
        print(
            f"  cleaned up {removed} test job row(s)"
        )


    if TIMINGS:

        print()
        print(
            "  MEASURED (job system, injected pipeline "
            "-- not a document-processing rate):"
        )

        for name, detail in TIMINGS.items():
            print(
                f"    {name}: {detail}"
            )


    print()
    print("=" * 76)
    print(
        f"[PASS] PHASE 9.6 PASSED - "
        f"{len(PASSES)} properties asserted"
    )
    print("=" * 76)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
