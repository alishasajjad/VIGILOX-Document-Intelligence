import tempfile
import threading
import uuid

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path

import groq
import httpx

from sqlalchemy import delete

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
    JOB_ERROR_ABANDONED,
    JOB_ERROR_ATTEMPTS_EXHAUSTED,
    JOB_ERROR_PROVIDER_RATE_LIMITED,
    JOB_ERROR_SOURCE_MISSING,
    JOB_ERROR_UNSUPPORTED_DOCUMENT,
    PROCESSING,
    QUEUED,
    RETRY_WAIT,
)

from backend.app.services.document_worker import (
    DocumentWorker,
)

from backend.app.services.job_failure_classifier import (
    UnsupportedDocumentError,
)

from backend.app.services.job_service import (
    JobService,
)

from backend.app.services.job_source_store import (
    JobSourceStore,
)


# ==========================================================
# PHASE 9.3
# JOB SERVICE AND WORKER CONTRACT TEST
# ==========================================================
#
# The claims this suite has to actually prove, because each
# one is a silent-data-corruption bug if it is wrong and a
# single-worker test would pass either way:
#
#   1. Two workers racing for one job produce exactly one
#      winner. Tested with real threads on real connections,
#      because FOR UPDATE SKIP LOCKED is a database behaviour
#      and mocking it would only test the mock.
#
#   2. A worker that dies mid-job does not strand the
#      document. The lease expires, another worker takes it,
#      and it finishes once.
#
#   3. A stale worker that comes back and tries to finish a
#      job somebody else owns does not leave a second
#      document behind for one upload.
#
#   4. A rate limit parks the job with a future
#      next_attempt_at and keeps its bytes. A permanent
#      failure does not retry at all and releases them.
#
#   5. Nothing a browser can see carries a filesystem path,
#      a worker identity or an exception string.
#
# The pipeline and the persistence service are injected fakes.
# That is the point: it makes every failure path reachable in
# milliseconds and costs no provider quota, so these can run
# in the deterministic gate.
#
# Real rows are written and deleted again. Every job created
# here carries a run-scoped marker in its filename so cleanup
# can never touch anything else.
# ==========================================================

RUN_MARKER = (
    "phase9test-"
    + uuid.uuid4().hex[:10]
)


PASSES: list[str] = []


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
# FAKES
# ==========================================================

class FakePipeline:

    """
    Stands in for OCR plus Groq plus the validators.

    Its whole job is to be instant and to fail on demand, so
    that the interesting paths -- rate limit, permanent
    failure, crash -- are reachable without an eighteen second
    OCR pass.
    """

    def __init__(
        self,
        *,
        raises: BaseException | None = None,
        on_process=None,
    ) -> None:

        self.raises = raises

        self.on_process = on_process

        self.calls = 0

        self.paths: list[str] = []


    def process(
        self,
        image_path,
        reference_date=None,
        timer=None,
    ):

        self.calls += 1

        self.paths.append(
            str(
                image_path
            )
        )


        if self.on_process is not None:
            self.on_process(
                self
            )


        if self.raises is not None:
            raise self.raises


        return {
            "extraction": {
                "document_type": "guard_license",
            },
            "ocr_lines": [],
            "evidence_flags": {},
            "field_confidence": {},
            "date_validation": {},
            "anomaly_validation": {},
            "review_decision": {},
        }


class FakePersistence:

    """
    Records what would have been saved and hands back a
    document id.
    """

    def __init__(
        self,
    ) -> None:

        self.saved: list[dict] = []


    def save_processed_document(
        self,
        *,
        original_filename,
        content_type,
        pipeline_result,
        source_path=None,
        source_sha256=None,
    ):

        """
        PHASE 10.3 added source_sha256, which the worker now
        passes because it already computed the fingerprint at
        job creation.

        Declared explicitly rather than swallowed by a
        **kwargs, so this double keeps DOCUMENTING the real
        interface. A double that quietly accepts anything
        stops failing when the real signature moves, which is
        the one thing it is here to notice.

        It is recorded, so a test can assert the worker
        forwarded it rather than dropping it.
        """

        document_id = (
            "doc-"
            + uuid.uuid4().hex[:12]
        )

        self.saved.append(
            {
                "document_id":
                    document_id,

                "original_filename":
                    original_filename,

                "source_path":
                    str(
                        source_path
                    ),

                "source_sha256":
                    source_sha256,
            }
        )

        return {
            "document_id":
                document_id,
        }


# ==========================================================
# A WORKER CONFINED TO THIS SUITE
# ==========================================================
#
# Overrides only the two entry points that pick a job, and
# passes the suite own job ids down to them. Everything else
# about the worker -- leasing, failure classification,
# persistence, completion -- is the real implementation, which
# is the whole point of testing through it.
# ==========================================================

class _ScopedWorker(
    DocumentWorker
):

    def __init__(
        self,
        *,
        owner,
        scoped: bool,
        **kwargs,
    ) -> None:

        super().__init__(
            **kwargs
        )

        self._owner = owner

        self._scoped = scoped


    def _scope(
        self,
    ):

        if not self._scoped:
            return None

        # A list, and an EMPTY one means nothing rather than
        # everything: claim_next builds an IN over it. If this
        # suite has created no jobs yet, there is nothing of
        # ours to claim, which is the truth.
        return list(
            self._owner.created
        )


    def claim(
        self,
        *,
        only_job_ids=None,
    ):

        return super().claim(
            only_job_ids=(
                only_job_ids
                if only_job_ids is not None
                else self._scope()
            ),
        )


    def process_one(
        self,
        *,
        only_job_ids=None,
    ) -> bool:

        return super().process_one(
            only_job_ids=(
                only_job_ids
                if only_job_ids is not None
                else self._scope()
            ),
        )


# ==========================================================
# HARNESS
# ==========================================================

class Harness:

    def __init__(
        self,
    ) -> None:

        self.temp_root = (
            Path(
                tempfile.mkdtemp(
                    prefix="vigilox-phase9-",
                )
            )
        )

        self.store = (
            JobSourceStore(
                pending_root=(
                    self.temp_root
                    / "pending"
                ),
            )
        )

        self.jobs = (
            JobService(
                source_store=(
                    self.store
                ),
            )
        )

        self.created: list[str] = []


    # ------------------------------------------------------

    def upload(
        self,
        name: str = "guard.jpg",
        content: bytes | None = None,
    ) -> Path:

        """
        A pending-source file for one job.

        PHASE 10.3. The default content is now UNIQUE per
        call, where it used to be the fixed literal b"BYTES".

        Every job in these suites represents a DIFFERENT
        document -- the fixed literal was a shortcut, not an
        intent. Once duplicate detection arrived, that
        shortcut made every job after the first an exact
        duplicate of it, and JobService correctly refused to
        queue them.

        Passing explicit content still works, which is what a
        test wanting a deliberate duplicate would do.
        """

        if content is None:
            content = (
                b"BYTES-"
                + uuid.uuid4().hex.encode()
            )

        path = (
            self.temp_root
            / f"upload-{uuid.uuid4().hex}.tmp"
        )

        path.write_bytes(
            content
        )

        return path


    def queue(
        self,
        name: str = "guard.jpg",
        batch_id: str | None = None,
    ) -> dict:

        payload = (
            self.jobs.create_job(
                original_filename=(
                    f"{RUN_MARKER}-{name}"
                ),

                content_type=(
                    "image/jpeg"
                ),

                size_bytes=5,

                upload_path=(
                    self.upload()
                ),

                batch_id=(
                    batch_id
                ),
            )
        )

        self.created.append(
            payload["job_id"]
        )

        return payload


    def worker(
        self,
        *,
        pipeline=None,
        persistence=None,
        lease_seconds: int = 180,
        worker_id: str | None = None,
        scoped: bool = True,
    ) -> DocumentWorker:

        """
        A worker for this suite.

        SCOPED TO THIS SUITE BY DEFAULT.
        ------------------------------------------------------

        claim_next takes the OLDEST claimable job, which is
        correct in production and wrong here: the shared
        development database may hold a real upload somebody
        made through the browser, and it would be older than
        anything this suite creates. A worker in a test would
        claim it and process it with a fake pipeline.

        The suite used to guard against that by refusing to run
        at all when the queue was not empty. That was honest
        but unlivable -- the whole gate stopped whenever a
        developer had used the application, and the reported
        fix was to drain somebody else's pending work.

        Restricting the claim removes the conflict instead of
        detecting it. A foreign job cannot be claimed, so its
        presence stops mattering.

        scoped=False is for the tests that deliberately reason
        about the queue as a whole.
        """

        return _ScopedWorker(
            owner=self,
            scoped=scoped,
            pipeline=(
                pipeline
                if pipeline is not None
                else FakePipeline()
            ),

            persistence=(
                persistence
                if persistence is not None
                else FakePersistence()
            ),

            job_service=(
                self.jobs
            ),

            worker_id=(
                worker_id
                or f"test-{uuid.uuid4().hex[:8]}"
            ),

            lease_seconds=(
                lease_seconds
            ),
        )


    def row(
        self,
        job_id: str,
    ) -> dict:

        with SessionLocal.begin() as session:

            job = (
                DocumentJobRepository(
                    session
                )
                .get_job(
                    job_id
                )
            )


            if job is None:
                fail(
                    f"Job {job_id} vanished."
                )


            return {
                "status":
                    job.status,

                "stage":
                    job.current_stage,

                "document_id":
                    job.document_id,

                "attempt_count":
                    job.attempt_count,

                "max_attempts":
                    job.max_attempts,

                "next_attempt_at":
                    job.next_attempt_at,

                "error_code":
                    job.safe_error_code,

                "error_message":
                    job.safe_error_message,

                "worker_id":
                    job.worker_id,

                "lease_expires_at":
                    job.lease_expires_at,

                "source_name":
                    job.source_name,
            }


    def claimable_count(
        self,
    ) -> int:

        """
        Jobs anywhere in the queue that a worker could take
        right now.

        QUEUED always, plus RETRY_WAIT whose backoff has
        elapsed -- the same condition the repository's claim
        query uses.
        """

        from sqlalchemy import func, or_, select

        with SessionLocal.begin() as session:

            return int(
                session.execute(
                    select(
                        func.count()
                    )
                    .select_from(
                        DocumentJobModel
                    )
                    .where(
                        or_(
                            DocumentJobModel.status
                            == QUEUED,

                            (
                                DocumentJobModel.status
                                == RETRY_WAIT
                            )
                            & (
                                DocumentJobModel
                                .next_attempt_at
                                <= datetime.now(
                                    timezone.utc
                                )
                            ),
                        )
                    )
                ).scalar_one()
            )


    def expire_lease(
        self,
        job_id: str,
    ) -> None:

        """
        Simulate a worker that died: leave the row PROCESSING
        but move its lease into the past.

        This is exactly the state a SIGKILL leaves behind, and
        it is the only honest way to test recovery without
        actually killing a process mid-transaction.
        """

        with SessionLocal.begin() as session:

            job = (
                session.get(
                    DocumentJobModel,
                    job_id,
                )
            )

            job.lease_expires_at = (
                datetime.now(
                    timezone.utc
                )
                - timedelta(
                    seconds=60,
                )
            )


    def cleanup(
        self,
    ) -> int:

        import shutil

        with SessionLocal.begin() as session:

            result = (
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
                )
            )

            removed = result.rowcount


        shutil.rmtree(
            self.temp_root,
            ignore_errors=True,
        )

        return removed


def rate_limit_error(
    retry_after: str | None = None,
) -> groq.RateLimitError:

    headers = (
        {
            "retry-after": retry_after,
        }
        if retry_after
        else {}
    )

    return (
        groq.RateLimitError(
            "rate limited",
            response=(
                httpx.Response(
                    429,
                    headers=headers,
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
    )


# ==========================================================
# 1. CREATION
# ==========================================================

def test_creation_stores_bytes_before_row(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != QUEUED:
        fail(
            "A new job should be QUEUED, not "
            f"{row['status']}."
        )


    if row["attempt_count"] != 0:
        fail(
            "A new job has made no attempts."
        )


    # The bytes must be on disk already. A row that exists
    # before its bytes can be claimed in the window between
    # the two and fail with SOURCE_MISSING on a job that was
    # fine.
    if not harness.store.exists(
        row["source_name"]
    ):
        fail(
            "The pending upload is not on disk, so a "
            "worker could claim this job and find "
            "nothing."
        )


    # The stored name must not be derived from the uploaded
    # filename, which is untrusted.
    if RUN_MARKER in row["source_name"]:
        fail(
            "The stored source name contains the "
            "uploaded filename. It must be generated, so "
            "an uploaded name never reaches a path."
        )


    ok(
        "a queued job has its bytes on disk and a "
        "generated source name"
    )


def test_failed_row_removes_orphaned_bytes(
    harness: Harness,
):

    """
    If the row cannot be written, the bytes must not be left
    behind unreferenced.
    """

    upload = (
        harness.upload()
    )

    class Boom(
        RuntimeError
    ):
        pass

    original = (
        DocumentJobRepository.create_job
    )

    def exploding(
        *args,
        **kwargs,
    ):
        raise Boom(
            "row rejected"
        )

    DocumentJobRepository.create_job = (
        exploding
    )


    before = set(
        harness.store
        .orphaned_names(
            set()
        )
    )


    try:
        harness.jobs.create_job(
            original_filename=(
                f"{RUN_MARKER}-doomed.jpg"
            ),
            content_type="image/jpeg",
            size_bytes=5,
            upload_path=upload,
        )

        fail(
            "Job creation should have raised."
        )

    except Boom:
        pass

    finally:
        DocumentJobRepository.create_job = (
            original
        )


    after = set(
        harness.store
        .orphaned_names(
            set()
        )
    )


    if after - before:
        fail(
            "A failed job creation left "
            f"{len(after - before)} unreferenced "
            "pending file(s) behind."
        )


    ok(
        "a job creation that fails leaves no "
        "unreferenced bytes"
    )


# ==========================================================
# 2. CLAIM SAFETY
# ==========================================================

def test_single_claim_wins(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    first = (
        harness.worker()
    )

    second = (
        harness.worker()
    )

    claimed_first = (
        first.claim()
    )

    claimed_second = (
        second.claim()
    )


    if claimed_first is None:
        fail(
            "The first worker claimed nothing."
        )


    if (
        claimed_second is not None
        and claimed_second["job_id"]
        == claimed_first["job_id"]
    ):
        fail(
            "Two workers claimed the same job."
        )


    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != PROCESSING:
        fail(
            "A claimed job should be PROCESSING."
        )


    if row["attempt_count"] != 1:
        fail(
            "A claim is an attempt; attempt_count "
            f"should be 1, not {row['attempt_count']}."
        )


    if row["lease_expires_at"] is None:
        fail(
            "A claimed job must carry a lease, or a "
            "dead worker strands it forever."
        )


    ok(
        "a claim is exclusive, counts as an attempt "
        "and takes a lease"
    )


def test_concurrent_claims_are_exclusive(
    harness: Harness,
):

    """
    The real test. Eight threads, real connections, one job
    each, and every job claimed exactly once.

    A version of this that shared a session, or that mocked
    the database, would pass without proving anything -- the
    guarantee being relied on is PostgreSQL's, so PostgreSQL
    has to be the thing under test.
    """

    # PHASE 10.4 SIMPLIFIED THIS.
    #
    # It used to count how many jobs were claimable in the
    # WHOLE queue and add its own six, because a worker in a
    # test claimed the oldest claimable row anywhere in the
    # shared database. That arithmetic was the only way to
    # state the expectation without assuming an empty queue --
    # and it was still wrong once the queue held rows this
    # suite could not claim.
    #
    # Workers built by the harness are now confined to the
    # jobs this suite created, so the expectation is exact and
    # local: six jobs, eight racers, six claims. Nothing else
    # in the database can be claimed, so nothing else has to be
    # counted.
    #
    # The property under test is unchanged and is still
    # PostgreSQL's: no job is claimed twice.
    job_ids = {
        harness.queue()["job_id"]
        for _ in range(6)
    }

    claimable_total = len(
        job_ids
    )

    workers = 8

    claims: list[dict] = []

    errors: list[str] = []

    barrier = (
        threading.Barrier(
            workers
        )
    )

    lock = (
        threading.Lock()
    )


    def race(
        index: int,
    ) -> None:

        worker = (
            harness.worker(
                worker_id=(
                    f"racer-{index}"
                ),
            )
        )

        try:
            # Every thread arrives at the claim at the same
            # moment. Without this they would naturally
            # stagger and the race would not happen.
            barrier.wait(
                timeout=20
            )

            claimed = (
                worker.claim()
            )


            if claimed is not None:

                with lock:
                    claims.append(
                        claimed
                    )


        except Exception as error:      # noqa: BLE001

            with lock:
                errors.append(
                    f"{type(error).__name__}: {error}"
                )


    threads = [
        threading.Thread(
            target=race,
            args=(
                index,
            ),
        )
        for index in range(
            workers
        )
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(
            timeout=40
        )


    if errors:
        fail(
            "Claiming raised under concurrency:\n"
            + "\n".join(
                errors
            )
        )


    claimed_ids = [
        claim["job_id"]
        for claim in claims
    ]


    # THE property. A duplicate here means two workers would
    # each run the pipeline on one upload and persist two
    # documents.
    if len(claimed_ids) != len(
        set(
            claimed_ids
        )
    ):

        duplicates = [
            job_id
            for job_id in set(
                claimed_ids
            )
            if claimed_ids.count(
                job_id
            )
            > 1
        ]

        fail(
            "The same job was claimed more than once: "
            f"{duplicates}. FOR UPDATE SKIP LOCKED is "
            "not doing its job, and two workers would "
            "produce two documents from one upload."
        )


    # Eight workers against however many jobs were claimable:
    # every worker that could get one should have got one, and
    # the surplus workers should have got nothing rather than
    # stealing a claimed row.
    expected = min(
        workers,
        claimable_total,
    )


    if len(claims) != expected:
        fail(
            f"{claimable_total} jobs were claimable and "
            f"{workers} workers raced, so {expected} "
            f"claims were expected; {len(claims)} were "
            "made."
        )


    # And this test has to have actually raced for something,
    # or it proves nothing.
    mine = [
        job_id
        for job_id in claimed_ids
        if job_id in job_ids
    ]


    if len(mine) < 2:
        fail(
            "The race did not involve at least two of "
            "this test's own jobs, so it is not "
            "exercising concurrent claiming."
        )


    ok(
        f"{workers} concurrent workers made "
        f"{len(claims)} claims over {claimable_total} "
        "claimable jobs with no double claim"
    )


def test_lease_extension_is_owner_scoped(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    owner = (
        harness.worker(
            worker_id="the-owner",
        )
    )

    owner.claim()


    thief = (
        harness.worker(
            worker_id="the-thief",
        )
    )

    stolen = (
        thief._advance(
            payload["job_id"],
            "OCR",
        )
    )


    if stolen:
        fail(
            "A worker that does not own a job was able "
            "to extend its lease. Two workers with a "
            "live claim on one row is the exact failure "
            "the lease exists to prevent."
        )


    if not owner._advance(
        payload["job_id"],
        "OCR",
    ):
        fail(
            "The owning worker could not extend its own "
            "lease."
        )


    ok(
        "only the owning worker can extend a lease"
    )


# ==========================================================
# 3. HAPPY PATH
# ==========================================================

def test_completion(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    pipeline = (
        FakePipeline()
    )

    persistence = (
        FakePersistence()
    )

    worker = (
        harness.worker(
            pipeline=pipeline,
            persistence=persistence,
        )
    )

    source_name = (
        harness.row(
            payload["job_id"]
        )["source_name"]
    )


    if not worker.process_one():
        fail(
            "The worker found nothing to do."
        )


    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != COMPLETED:
        fail(
            f"Expected COMPLETED, got {row['status']} "
            f"({row['error_code']})."
        )


    if not row["document_id"]:
        fail(
            "A completed job must carry its "
            "document_id."
        )


    if row["stage"] is not None:
        fail(
            "A finished job should not still report a "
            "stage."
        )


    if row["worker_id"] is not None:
        fail(
            "A finished job should not still name a "
            "worker."
        )


    if row["lease_expires_at"] is not None:
        fail(
            "A finished job should not still hold a "
            "lease."
        )


    if pipeline.calls != 1:
        fail(
            f"The pipeline ran {pipeline.calls} times "
            "for one job."
        )


    if len(persistence.saved) != 1:
        fail(
            f"{len(persistence.saved)} documents were "
            "persisted for one job."
        )


    # The pipeline must have been handed the pending file, not
    # something else.
    if source_name not in pipeline.paths[0]:
        fail(
            "The pipeline was not given the job's "
            "pending upload."
        )


    # Managed storage now holds the bytes, so the pending copy
    # is redundant.
    if harness.store.exists(
        source_name
    ):
        fail(
            "The pending upload survived completion. "
            "These are identity documents; a finished "
            "job must not keep a second copy."
        )


    ok(
        "a job completes once, records its document, "
        "clears its lease and releases its bytes"
    )


# ==========================================================
# 4. RETRY
# ==========================================================

def test_rate_limit_parks_and_keeps_bytes(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    worker = (
        harness.worker(
            pipeline=(
                FakePipeline(
                    raises=(
                        rate_limit_error(
                            "45"
                        )
                    ),
                )
            ),
        )
    )

    before = (
        datetime.now(
            timezone.utc
        )
    )

    worker.process_one()

    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != RETRY_WAIT:
        fail(
            "A rate limit should park the job in "
            f"RETRY_WAIT, not {row['status']}."
        )


    if row["error_code"] != JOB_ERROR_PROVIDER_RATE_LIMITED:
        fail(
            "A rate limit should be recorded as "
            f"{JOB_ERROR_PROVIDER_RATE_LIMITED}, not "
            f"{row['error_code']}."
        )


    if row["next_attempt_at"] is None:
        fail(
            "A parked job needs next_attempt_at, or "
            "nothing knows when to try again."
        )


    scheduled = row["next_attempt_at"]

    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(
            tzinfo=timezone.utc,
        )


    waited = (
        scheduled - before
    ).total_seconds()


    # The provider said 45 seconds. Honouring it is the
    # difference between backing off politely and guessing.
    if not 30 <= waited <= 70:
        fail(
            "The retry was scheduled "
            f"{waited:.0f}s out. The provider's "
            "Retry-After of 45s should have been "
            "honoured."
        )


    # A busy-loop is the specific failure a rate limit invites.
    if waited < 2:
        fail(
            "The retry is immediate. That is a hot "
            "loop against a provider that just asked us "
            "to slow down."
        )


    # The next attempt needs these bytes.
    if not harness.store.exists(
        row["source_name"]
    ):
        fail(
            "The pending upload was deleted while the "
            "job is waiting to retry, so the retry "
            "will fail with SOURCE_MISSING."
        )


    ok(
        f"a rate limit parks the job {waited:.0f}s out, "
        "honours Retry-After and keeps its bytes"
    )


def test_retry_wait_is_not_claimable_early(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    harness.worker(
        pipeline=(
            FakePipeline(
                raises=(
                    rate_limit_error(
                        "600"
                    )
                ),
            )
        ),
    ).process_one()


    # A second worker must not pick it up before its time.
    if harness.worker().claim() is not None:
        fail(
            "A job in RETRY_WAIT was claimed before "
            "next_attempt_at. The backoff is not being "
            "enforced, which turns a rate limit into a "
            "spin."
        )


    # Move its time into the past; now it should be claimable.
    with SessionLocal.begin() as session:

        session.get(
            DocumentJobModel,
            payload["job_id"],
        ).next_attempt_at = (
            datetime.now(
                timezone.utc
            )
            - timedelta(
                seconds=1,
            )
        )


    claimed = (
        harness.worker().claim()
    )


    if claimed is None:
        fail(
            "A job whose next_attempt_at has passed "
            "was not claimable."
        )


    if claimed["attempt_count"] != 2:
        fail(
            "A retry is the second attempt; got "
            f"{claimed['attempt_count']}."
        )


    ok(
        "RETRY_WAIT is claimable only after "
        "next_attempt_at, and counts as a new attempt"
    )


def test_attempts_exhausted_is_terminal(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    pipeline = (
        FakePipeline(
            raises=(
                rate_limit_error()
            ),
        )
    )

    worker = (
        harness.worker(
            pipeline=pipeline,
        )
    )

    source_name = (
        harness.row(
            payload["job_id"]
        )["source_name"]
    )

    attempts = (
        harness.row(
            payload["job_id"]
        )["max_attempts"]
    )


    for _ in range(
        attempts + 2
    ):

        worker.process_one()

        # Skip the backoff so the test is not sitting there
        # for a minute.
        with SessionLocal.begin() as session:

            job = (
                session.get(
                    DocumentJobModel,
                    payload["job_id"],
                )
            )

            if job.next_attempt_at is not None:

                job.next_attempt_at = (
                    datetime.now(
                        timezone.utc
                    )
                    - timedelta(
                        seconds=1,
                    )
                )


    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != FAILED:
        fail(
            "A transient failure that runs out of "
            "attempts must become FAILED, not "
            f"{row['status']}. A job retrying forever "
            "occupies a worker permanently."
        )


    if row["attempt_count"] != attempts:
        fail(
            f"Expected exactly {attempts} attempts, "
            f"got {row['attempt_count']}."
        )


    if row["error_code"] != JOB_ERROR_ATTEMPTS_EXHAUSTED:
        fail(
            "A permanently failed job should say "
            "attempts were exhausted, not repeat the "
            f"last symptom ({row['error_code']}). "
            "'Rate limited' on a dead job reads like it "
            "is still waiting."
        )


    if harness.store.exists(
        source_name
    ):
        fail(
            "A terminally failed job kept its pending "
            "upload."
        )


    ok(
        f"a transient failure retries exactly "
        f"{attempts} times, then fails as exhausted "
        "and releases its bytes"
    )


# ==========================================================
# 5. PERMANENT FAILURE
# ==========================================================

def test_permanent_failure_does_not_retry(
    harness: Harness,
):

    cases = (
        (
            "unsupported document",
            UnsupportedDocumentError(
                "not a supported type"
            ),
            JOB_ERROR_UNSUPPORTED_DOCUMENT,
        ),
    )

    for label, error, expected in cases:

        payload = (
            harness.queue()
        )

        pipeline = (
            FakePipeline(
                raises=error,
            )
        )

        worker = (
            harness.worker(
                pipeline=pipeline,
            )
        )

        source_name = (
            harness.row(
                payload["job_id"]
            )["source_name"]
        )

        worker.process_one()

        row = (
            harness.row(
                payload["job_id"]
            )
        )


        if row["status"] != FAILED:
            fail(
                f"{label}: expected FAILED on the "
                f"first attempt, got {row['status']}."
            )


        if row["attempt_count"] != 1:
            fail(
                f"{label}: a permanent failure must "
                "not consume more than one attempt; "
                f"got {row['attempt_count']}."
            )


        if row["error_code"] != expected:
            fail(
                f"{label}: expected {expected}, got "
                f"{row['error_code']}."
            )


        if harness.store.exists(
            source_name
        ):
            fail(
                f"{label}: the pending upload survived "
                "a terminal failure."
            )


    ok(
        "a permanent failure fails on the first "
        "attempt and never retries"
    )


def test_missing_source_is_permanent(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    row = (
        harness.row(
            payload["job_id"]
        )
    )

    # Delete the bytes behind the job's back, which is what a
    # cleanup script or a lost volume looks like.
    harness.store.delete_pending(
        row["source_name"]
    )

    pipeline = (
        FakePipeline()
    )

    harness.worker(
        pipeline=pipeline,
    ).process_one()

    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != FAILED:
        fail(
            "A job whose bytes are gone cannot "
            "succeed; expected FAILED, got "
            f"{row['status']}."
        )


    if row["error_code"] != JOB_ERROR_SOURCE_MISSING:
        fail(
            "Expected SOURCE_MISSING, got "
            f"{row['error_code']}."
        )


    if pipeline.calls:
        fail(
            "The pipeline was run despite the source "
            "being missing. That is an eighteen second "
            "OCR pass on nothing."
        )


    ok(
        "a job with no bytes fails permanently without "
        "running the pipeline"
    )


# ==========================================================
# 6. CRASH RECOVERY
# ==========================================================

def test_expired_lease_is_recovered(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    # A worker claims the job and is killed. The row stays
    # PROCESSING with a lease nobody is extending.
    harness.worker(
        worker_id="doomed-worker",
    ).claim()

    harness.expire_lease(
        payload["job_id"]
    )


    survivor = (
        harness.worker(
            worker_id="survivor",
        )
    )

    # Before recovery it must not be claimable: a live claim
    # is a live claim, expired or not, until something
    # deliberately reclaims it.
    recovered = (
        survivor.reclaim_expired()
    )


    if recovered < 1:
        fail(
            "An expired lease was not recovered. The "
            "document would sit in PROCESSING forever "
            "and silently never appear."
        )


    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != QUEUED:
        fail(
            "A recovered job should be back in the "
            f"queue, not {row['status']}."
        )


    if row["worker_id"] is not None:
        fail(
            "A recovered job still names the dead "
            "worker."
        )


    if row["error_code"] != JOB_ERROR_ABANDONED:
        fail(
            "A recovered job should record that it was "
            "abandoned, so an operator can see it "
            "happened."
        )


    # attempt_count must NOT be reset, or a document that
    # kills its worker every time is retried forever.
    if row["attempt_count"] != 1:
        fail(
            "The abandoned attempt was not counted "
            f"(attempt_count = {row['attempt_count']}). "
            "A document that repeatedly kills its "
            "worker must eventually stop being retried."
        )


    # And now it finishes, exactly once.
    persistence = (
        FakePersistence()
    )

    survivor_two = (
        harness.worker(
            persistence=persistence,
        )
    )

    survivor_two.process_one()

    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != COMPLETED:
        fail(
            "The recovered job did not complete; got "
            f"{row['status']}."
        )


    if len(persistence.saved) != 1:
        fail(
            f"{len(persistence.saved)} documents "
            "persisted for one recovered job."
        )


    ok(
        "a dead worker's job is recovered, counted, "
        "and finishes exactly once"
    )


def test_exhausted_abandoned_job_fails(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    with SessionLocal.begin() as session:

        job = (
            session.get(
                DocumentJobModel,
                payload["job_id"],
            )
        )

        job.status = PROCESSING

        job.worker_id = "gone"

        job.attempt_count = job.max_attempts

        job.lease_expires_at = (
            datetime.now(
                timezone.utc
            )
            - timedelta(
                seconds=60,
            )
        )


    harness.worker().reclaim_expired()

    row = (
        harness.row(
            payload["job_id"]
        )
    )


    if row["status"] != FAILED:
        fail(
            "A job that has exhausted its attempts and "
            "then been abandoned must fail, not go back "
            f"in the queue; got {row['status']}."
        )


    if row["error_code"] != JOB_ERROR_ABANDONED:
        fail(
            f"Expected ABANDONED, got "
            f"{row['error_code']}."
        )


    ok(
        "an abandoned job with no attempts left fails "
        "instead of looping"
    )


def test_stale_replay_stops_at_the_lease_gate(
    harness: Harness,
):

    """
    A worker stalls, loses its lease, the job is reclaimed and
    finished by somebody else, and the original worker wakes
    up mid-pipeline.

    It must notice at the next stage boundary and stop before
    persisting anything. This is the cheap outcome: the stale
    attempt costs an OCR pass and nothing else.
    """

    payload = (
        harness.queue()
    )

    job_id = payload[
        "job_id"
    ]

    stale_persistence = (
        FakePersistence()
    )

    other_persistence = (
        FakePersistence()
    )

    def steal(
        pipeline,
    ) -> None:

        # Forced mid-pipeline, because this interleaving is
        # one a timing-dependent test would essentially never
        # hit on its own.
        harness.expire_lease(
            job_id
        )

        other = (
            harness.worker(
                worker_id="the-other-worker",
                persistence=(
                    other_persistence
                ),
            )
        )

        other.reclaim_expired()

        other.process_one()


    stale_worker = (
        harness.worker(
            worker_id="the-stale-worker",
            pipeline=(
                FakePipeline(
                    on_process=steal,
                )
            ),
            persistence=(
                stale_persistence
            ),
        )
    )

    # No pre-claim: process_one() claims for itself, and
    # claiming twice would leave the job PROCESSING and the
    # steal would never run.
    stale_worker.process_one()


    row = (
        harness.row(
            job_id
        )
    )


    if row["status"] != COMPLETED:
        fail(
            "The job should have been completed by the "
            f"worker that owned it; got {row['status']}."
        )


    if len(stale_persistence.saved) != 0:
        fail(
            "The stale worker persisted a document "
            "after losing its lease. It must notice at "
            "the next stage boundary and stop."
        )


    if len(other_persistence.saved) != 1:
        fail(
            "The worker that owned the job should have "
            "persisted exactly one document; got "
            f"{len(other_persistence.saved)}."
        )


    if row["document_id"] != (
        other_persistence.saved[0]["document_id"]
    ):
        fail(
            "The job does not point at the document "
            "persisted by its real owner."
        )


    ok(
        "a worker that loses its lease stops before "
        "persisting, and the real owner's document wins"
    )


def test_stale_replay_discards_a_duplicate_document(
    harness: Harness,
):

    """
    The narrower and nastier race: the stale worker gets past
    the stage gate and persists, and only then discovers the
    job is no longer its.

    mark_completed is scoped to status = PROCESSING precisely
    so that this cannot overwrite the outcome the real owner
    recorded. The document the stale attempt created is then a
    duplicate for one upload, and has to be removed rather
    than left orphaned with nothing pointing at it.
    """

    payload = (
        harness.queue()
    )

    job_id = payload[
        "job_id"
    ]

    other_persistence = (
        FakePersistence()
    )

    class StealingPersistence(
        FakePersistence
    ):

        """
        Loses the lease at the last possible moment: after the
        PERSISTING stage gate has already been passed, during
        the write itself.
        """

        def save_processed_document(
            self,
            **kwargs,
        ):

            if not self.saved:

                harness.expire_lease(
                    job_id
                )

                other = (
                    harness.worker(
                        worker_id=(
                            "the-real-owner"
                        ),
                        persistence=(
                            other_persistence
                        ),
                    )
                )

                other.reclaim_expired()

                other.process_one()


            return (
                super()
                .save_processed_document(
                    **kwargs
                )
            )


    stale_persistence = (
        StealingPersistence()
    )

    discarded: list[str] = []

    stale_worker = (
        harness.worker(
            worker_id="the-stale-worker",
            persistence=(
                stale_persistence
            ),
        )
    )

    # Record what the worker tries to remove. The real
    # deletion service would be operating on a document these
    # fakes never wrote, so the call is observed rather than
    # executed.
    stale_worker._discard_document = (
        discarded.append
    )

    stale_worker.process_one()


    row = (
        harness.row(
            job_id
        )
    )


    if row["status"] != COMPLETED:
        fail(
            f"Expected COMPLETED, got {row['status']}."
        )


    if len(other_persistence.saved) != 1:
        fail(
            "The real owner should have persisted "
            "exactly one document."
        )


    owner_document = (
        other_persistence.saved[0]["document_id"]
    )


    if row["document_id"] != owner_document:
        fail(
            "The stale worker overwrote the outcome "
            "recorded by the worker that actually owned "
            "the job. mark_completed is not scoped to "
            "PROCESSING."
        )


    stale_documents = [
        entry["document_id"]
        for entry in stale_persistence.saved
    ]


    if not stale_documents:
        fail(
            "This test is not exercising the race it "
            "claims to: the stale worker never "
            "persisted, so there was no duplicate to "
            "discard."
        )


    if discarded != stale_documents:
        fail(
            "The stale worker persisted "
            f"{stale_documents} but discarded "
            f"{discarded}. A duplicate document for one "
            "upload must be removed, not left orphaned "
            "with nothing pointing at it."
        )


    ok(
        "a stale worker that persists past the gate has "
        "its duplicate document discarded, and cannot "
        "overwrite the real outcome"
    )


# ==========================================================
# 7. WHAT THE BROWSER SEES
# ==========================================================

def test_serialization_hides_internals(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    worker = (
        harness.worker(
            worker_id="secret-worker-name",
        )
    )

    worker.claim()

    serialized = (
        harness.jobs.get_job(
            payload["job_id"]
        )
    )

    forbidden = (
        "source_name",
        "worker_id",
        "lease_expires_at",
        "source_path",
        "upload_path",
    )


    for key in forbidden:

        if key in serialized:
            fail(
                f"The job payload exposes {key}. A "
                "filesystem name and the internal "
                "scheduling state are nobody's "
                "business outside the worker."
            )


    blob = repr(
        serialized
    )


    if "secret-worker-name" in blob:
        fail(
            "The worker identity leaked into the job "
            "payload."
        )


    for marker in (
        "storage",
        "pending",
        "Temp",
        "/tmp",
        "C:\\",
    ):

        if marker in blob:
            fail(
                f"The job payload contains {marker!r}, "
                "which looks like a filesystem path."
            )


    for required in (
        "job_id",
        "status",
        "attempt_count",
        "max_attempts",
        "is_terminal",
        "status_url",
    ):

        if required not in serialized:
            fail(
                f"The job payload is missing "
                f"{required}."
            )


    if serialized["current_stage"] is None:
        fail(
            "A PROCESSING job should report its "
            "advisory stage."
        )


    ok(
        "the job payload carries no path, no worker "
        "identity and no internal scheduling state"
    )


def test_terminal_job_hides_stale_fields(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    harness.worker().process_one()

    serialized = (
        harness.jobs.get_job(
            payload["job_id"]
        )
    )


    if serialized["current_stage"] is not None:
        fail(
            "A finished job still reports a stage, "
            "which reads as live progress."
        )


    if serialized["next_attempt_at"] is not None:
        fail(
            "A finished job still reports "
            "next_attempt_at, which reads as a promise "
            "of another attempt."
        )


    if not serialized["is_terminal"]:
        fail(
            "A COMPLETED job should be terminal."
        )


    if not serialized["document_url"]:
        fail(
            "A completed job should offer a link to "
            "its document."
        )


    if serialized["document_url"] != (
        f"/review/{serialized['document_id']}"
    ):
        fail(
            "The document link does not point at the "
            "document."
        )


    ok(
        "a finished job reports no stage, no next "
        "attempt, and a link to its document"
    )


def test_error_message_is_vocabulary_not_exception(
    harness: Harness,
):

    payload = (
        harness.queue()
    )

    secret = (
        "postgresql://user:hunter2@db:5432/vigilox "
        "traceback File \"x.py\" line 9"
    )

    harness.worker(
        pipeline=(
            FakePipeline(
                raises=(
                    RuntimeError(
                        secret
                    )
                ),
            )
        ),
    ).process_one()

    serialized = (
        harness.jobs.get_job(
            payload["job_id"]
        )
    )

    blob = repr(
        serialized
    )


    for leak in (
        "hunter2",
        "postgresql://",
        "traceback",
        "File \"",
        "RuntimeError",
    ):

        if leak in blob:
            fail(
                f"The job payload leaked {leak!r} from "
                "an exception. Job rows reach the "
                "browser and follow the same rule as "
                "HTTP errors: a code and a safe "
                "sentence, never exception text."
            )


    if not serialized["error_message"]:
        fail(
            "A failed job should still explain itself "
            "in a readable sentence."
        )


    ok(
        "an exception's text never reaches the job "
        "payload, but a readable reason does"
    )


# ==========================================================
# MAIN
# ==========================================================

def require_quiet_queue(
    harness: Harness,
) -> None:

    """
    Refuse to run against a queue that already holds
    claimable jobs.

    claim_next() takes the oldest claimable row, which is
    exactly right in production and inconvenient here: a
    pre-existing job means the worker under test claims
    something this suite did not create, and the assertions
    read as failures for a reason that has nothing to do with
    the code.

    That happened. This suite passed alone and failed in the
    gate because five rows left over from an unrelated smoke
    test were older than its own.

    The fix is to say so, rather than to cope silently. A test
    that quietly adapts to a dirty queue is a test that has
    stopped checking the thing it was written for, and one
    that reaches into unrelated rows to tidy them is worse --
    those rows might be somebody's work in progress.
    """

    outstanding = (
        harness.claimable_count()
    )


    if outstanding:

        raise AssertionError(
            (
                f"{outstanding} job(s) are already "
                "claimable in the queue, so this suite "
                "cannot tell its own jobs from "
                "somebody else's.\n\n"
                "Drain the queue first:\n\n"
                "    python -m backend.worker --drain\n\n"
                "or, if they are residue, remove them "
                "deliberately:\n\n"
                "    python -m scripts.maintenance."
                "purge_finished_jobs --queued\n"
            )
        )


def main() -> int:

    print()
    print("=" * 76)
    print(
        "PHASE 9.3 - JOB SERVICE AND WORKER"
    )
    print("=" * 76)
    print()

    harness = (
        Harness()
    )

    # PHASE 10.4. The blanket guard is gone.
    #
    # Every worker this harness builds is confined to this
    # suite own jobs, so a foreign job in the queue cannot be
    # claimed and its presence no longer matters.
    #
    # require_quiet_queue is kept below, uncalled, because its
    # reasoning is worth reading and because a future test that
    # genuinely needs an empty queue should call it rather than
    # reinvent it.

    try:

        test_creation_stores_bytes_before_row(
            harness
        )

        test_failed_row_removes_orphaned_bytes(
            harness
        )

        test_single_claim_wins(
            harness
        )

        test_concurrent_claims_are_exclusive(
            harness
        )

        test_lease_extension_is_owner_scoped(
            harness
        )

        test_completion(
            harness
        )

        test_rate_limit_parks_and_keeps_bytes(
            harness
        )

        test_retry_wait_is_not_claimable_early(
            harness
        )

        test_attempts_exhausted_is_terminal(
            harness
        )

        test_permanent_failure_does_not_retry(
            harness
        )

        test_missing_source_is_permanent(
            harness
        )

        test_expired_lease_is_recovered(
            harness
        )

        test_exhausted_abandoned_job_fails(
            harness
        )

        test_stale_replay_stops_at_the_lease_gate(
            harness
        )

        test_stale_replay_discards_a_duplicate_document(
            harness
        )

        test_serialization_hides_internals(
            harness
        )

        test_terminal_job_hides_stale_fields(
            harness
        )

        test_error_message_is_vocabulary_not_exception(
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


    print()
    print("=" * 76)
    print(
        f"[PASS] PHASE 9.3 PASSED - "
        f"{len(PASSES)} properties asserted"
    )
    print("=" * 76)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
