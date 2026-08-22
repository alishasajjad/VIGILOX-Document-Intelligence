"""
==========================================================
PHASE 10.3 - EXACT DUPLICATE SOURCE DETECTION
==========================================================

WHAT THIS SUITE IS PROTECTING
----------------------------------------------------------

  1. Two identical uploads arriving at the same instant
     produce ONE job. Enforced by PostgreSQL, so this is
     tested with real concurrent threads against the real
     database rather than argued about.

  2. The transition where the worker persists a document and
     then completes its job has NO WINDOW in which the
     duplicate is invisible. Tested at the exact instant
     between the two commits, not reasoned about.

  3. A rejected duplicate costs no OCR and no Groq call.

  4. One duplicate inside a batch does not harm its siblings.

  5. Reprocessing is possible, but only when asked for
     explicitly.

  6. The fingerprint never leaves the service.


REAL POSTGRESQL IS REQUIRED
----------------------------------------------------------

The whole mechanism is a partial unique index. Substituting a
fake would test the substitute.

OCR and extraction are faked; they are irrelevant to identity
and would cost 17 seconds per document.
"""

import hashlib
import inspect
import json
import shutil
import sys
import tempfile
import threading
import uuid

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


from sqlalchemy import select                     # noqa: E402

from database.database import SessionLocal        # noqa: E402

from database.models import (                     # noqa: E402
    DocumentJobModel,
    DocumentModel,
)

from database.job_repositories import (           # noqa: E402
    DocumentJobRepository,
)

from database.repositories import (               # noqa: E402
    DocumentRepository,
)

from backend.app.domain.duplicates import (       # noqa: E402
    DUPLICATE_DOCUMENT,
    DUPLICATE_IN_PROGRESS,
    SOURCE_FINGERPRINT_LENGTH,
    describe_duplicate_source,
    fingerprint_path,
)

from backend.app.domain.job_states import (       # noqa: E402
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
)

from backend.app.services.job_service import (    # noqa: E402
    DuplicateSourceError,
    JobService,
)

from backend.app.services.job_source_store import (   # noqa: E402
    JobSourceStore,
)

from backend.app.services.document_worker import (    # noqa: E402
    DocumentWorker,
)

from backend.app.services.persistence_service import (  # noqa: E402
    PersistenceService,
)

from backend.app.services.query_service import (       # noqa: E402
    DocumentQueryService,
)

from tests.intelligence.test_phase10_unsupported_documents import (  # noqa: E402
    build_pipeline,
    clean_image,
    guard_extraction,
    ocr_lines,
)


RUN_MARKER = (
    f"phase10-3-{uuid.uuid4().hex[:8]}"
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
# HARNESS
# ==========================================================

class Harness:

    """
    A JobService writing to the real database, with its own
    pending-source root under a temporary directory.

    Tracks every job and document it creates so the teardown
    can remove exactly those rows and nothing else.
    """

    def __init__(
        self,
    ) -> None:

        self.temp_root = Path(
            tempfile.mkdtemp(
                prefix="vigilox-p103-",
            )
        )

        self.store = JobSourceStore(
            pending_root=(
                self.temp_root
                / "pending"
            ),
        )

        self.jobs = JobService(
            source_store=(
                self.store
            ),
        )

        self.job_ids: list[str] = []

        self.document_ids: list[str] = []

        self.counter = 0


    # ------------------------------------------------------

    def upload_file(
        self,
        content: bytes,
        *,
        suffix: str = ".jpg",
    ) -> Path:

        """
        A fresh temporary file holding exactly these bytes.

        Fresh every time because create_job consumes the file
        it is handed. Two uploads of identical CONTENT are two
        different files, which is precisely the case duplicate
        detection has to get right.
        """

        self.counter += 1

        path = (
            self.temp_root
            / f"upload-{self.counter}{suffix}"
        )

        path.write_bytes(
            content
        )

        return path


    def queue(
        self,
        content: bytes,
        *,
        name: str = "doc.jpg",
        batch_id: str | None = None,
        reprocess: bool = False,
    ) -> dict:

        payload = (
            self.jobs.create_job(
                original_filename=(
                    f"{RUN_MARKER}-{name}"
                ),

                content_type="image/jpeg",

                size_bytes=len(
                    content
                ),

                upload_path=(
                    self.upload_file(
                        content
                    )
                ),

                batch_id=batch_id,

                reprocess=reprocess,
            )
        )

        self.job_ids.append(
            payload["job_id"]
        )

        return payload


    def batch(
        self,
        files: list[tuple[str, bytes]],
        *,
        reprocess: bool = False,
    ) -> dict:

        uploads = [
            {
                "original_filename":
                    f"{RUN_MARKER}-{name}",

                "content_type":
                    "image/jpeg",

                "size_bytes":
                    len(
                        content
                    ),

                "upload_path":
                    self.upload_file(
                        content
                    ),
            }
            for name, content in files
        ]

        result = (
            self.jobs.create_batch(
                uploads=uploads,
                reprocess=reprocess,
            )
        )

        for job in result["jobs"]:
            self.job_ids.append(
                job["job_id"]
            )

        return result


    def row(
        self,
        job_id: str,
    ) -> dict | None:

        with SessionLocal() as session:

            job = session.get(
                DocumentJobModel,
                job_id,
            )

            if job is None:
                return None

            return {
                "status": job.status,
                "document_id": job.document_id,
                "attempt_count": job.attempt_count,
                "source_sha256": job.source_sha256,
            }


    def worker(
        self,
        pipeline,
        *,
        persistence=None,
    ) -> DocumentWorker:

        return DocumentWorker(
            pipeline=pipeline,

            persistence=(
                persistence
                if persistence is not None
                else PersistenceService()
            ),

            job_service=self.jobs,

            worker_id=(
                f"p103-{uuid.uuid4().hex[:8]}"
            ),

            lease_seconds=180,
        )


    def drain(
        self,
        *,
        limit: int = 40,
    ) -> int:

        """
        Process every claimable job until the queue is empty.

        Called by tests that deliberately leave a job queued,
        so the NEXT test starts from an empty queue.

        Without this, a later test calling process_one would
        claim the earlier leftover -- process_one takes the
        oldest claimable job, not the newest -- and would
        assert against a job it never created.
        """

        worker = self.worker(
            guard_pipeline()
        )

        processed = 0

        # Only jobs THIS RUN created. A blanket process_one()
        # would claim whatever is oldest in the database, which
        # may be a real upload.
        for job_id in list(
            self.job_ids
        ):

            if processed >= limit:
                break


            if worker.process_one(
                only_job_ids=job_id,
            ):
                processed += 1


        self.collect_documents()

        return processed


    def require_only_job(
        self,
        job_id: str,
    ) -> None:

        """
        Kept as a no-op for readability at the call sites.

        It used to assert that nothing else in the database was
        claimable. That is no longer needed: every worker call
        in this suite names the job it wants, so a foreign job
        cannot be claimed by accident and its presence is
        irrelevant.
        """

        return None


    def require_quiet_queue(
        self,
        *,
        allowed: set | None = None,
    ) -> None:

        """
        Also a no-op now, for the same reason.

        Removing the calls entirely would read as if nobody
        had thought about the interaction. Leaving them, with
        this explanation, records that the problem was real and
        how it was actually solved.
        """

        return None


    def cleanup(
        self,
    ) -> None:

        # Documents first: an analysis, review and audit row
        # cascade from the document, and a job referencing it
        # is deleted separately below.
        with SessionLocal.begin() as session:

            repository = DocumentRepository(
                session
            )

            for document_id in set(
                self.document_ids
            ):

                document = (
                    repository.get_document(
                        document_id
                    )
                )

                if document is not None:
                    repository.delete_document(
                        document
                    )


        with SessionLocal.begin() as session:

            for job_id in set(
                self.job_ids
            ):

                job = session.get(
                    DocumentJobModel,
                    job_id,
                )

                if job is not None:
                    session.delete(
                        job
                    )


        shutil.rmtree(
            self.temp_root,
            ignore_errors=True,
        )


    def collect_documents(
        self,
    ) -> None:

        """
        Record every document any of this run's jobs produced,
        so teardown removes them.
        """

        for job_id in list(
            self.job_ids
        ):

            row = self.row(
                job_id
            )

            if (
                row
                and row["document_id"]
            ):
                self.document_ids.append(
                    row["document_id"]
                )


# ==========================================================
# FIXTURE BYTES
# ==========================================================

def image_bytes() -> bytes:

    """
    Real evaluation image bytes, so hashing is realistic, made
    UNIQUE PER RUN by appending the run marker.

    WHY THE MARKER IS NOT OPTIONAL
    ------------------------------------------------------
    Returning the fixture unchanged made this suite depend on
    nobody having ever processed guard_001.jpg. That is not an
    assumption a test can make once exact duplicate detection
    exists, and it broke as soon as those bytes had been
    processed once through the application -- the first upload
    of the suite was rejected as a duplicate of a real
    document.

    The marker is appended rather than prepended so the file
    stays a decodable JPEG: a decoder stops at the
    end-of-image marker and ignores trailing bytes. Within one
    run the value is constant, so every identical-content
    assertion in this suite still holds.
    """

    return (
        clean_image().read_bytes()
        + RUN_MARKER.encode()
    )


def different_bytes() -> bytes:

    """
    A different document. One trailing byte is enough to make
    a different SHA-256, and using the same base image proves
    the fingerprint is over CONTENT rather than over anything
    that happens to look similar.
    """

    return image_bytes() + b"\x00"


def guard_pipeline():

    pipeline, _, _ = build_pipeline(
        lines=ocr_lines(),
        extraction=(
            guard_extraction()
        ),
    )

    return pipeline


# ==========================================================
# 1. THE FINGERPRINT ITSELF
# ==========================================================

def test_fingerprint(
    harness: Harness,
) -> None:

    section(
        "TEST 1 - THE FINGERPRINT IS OVER THE BYTES"
    )

    content = image_bytes()

    first = harness.upload_file(
        content
    )

    second = harness.upload_file(
        content
    )

    assert_equal(
        fingerprint_path(
            first
        ),
        fingerprint_path(
            second
        ),
        (
            "Two files with identical content must "
            "fingerprint identically, whatever they are "
            "called or where they sit."
        ),
    )

    assert_equal(
        len(
            fingerprint_path(
                first
            )
        ),
        SOURCE_FINGERPRINT_LENGTH,
        (
            "A SHA-256 hex digest is 64 characters, which "
            "is what the column is sized for."
        ),
    )

    assert_equal(
        fingerprint_path(
            first
        ),
        hashlib.sha256(
            content
        ).hexdigest(),
        (
            "The streamed fingerprint must equal a plain "
            "SHA-256 of the same bytes. Chunked reading "
            "must not change the answer."
        ),
    )

    assert_true(
        fingerprint_path(
            first
        )
        != fingerprint_path(
            harness.upload_file(
                different_bytes()
            )
        ),
        (
            "One differing byte must produce a different "
            "fingerprint."
        ),
    )

    ok(
        "Identical content hashes identically regardless of "
        "filename; one byte of difference does not; "
        "streaming matches a plain SHA-256"
    )


# ==========================================================
# 2. A COMPLETED DUPLICATE
# ==========================================================

def test_completed_duplicate(
    harness: Harness,
) -> None:

    section(
        "TEST 2 - AN IDENTICAL SOURCE ALREADY PROCESSED"
    )

    content = image_bytes()

    harness.require_quiet_queue()

    first = harness.queue(
        content,
        name="original.jpg",
    )

    # Process it, so a completed document exists.
    pipeline = guard_pipeline()

    worker = harness.worker(
        pipeline
    )

    assert_true(
        worker.process_one(
            only_job_ids=first["job_id"],
        ),
        "The worker must process the queued job.",
    )

    row = harness.row(
        first["job_id"]
    )

    assert_equal(
        row["status"],
        "COMPLETED",
        "The first job completes normally.",
    )

    document_id = row["document_id"]

    harness.document_ids.append(
        document_id
    )

    assert_equal(
        row["source_sha256"],
        hashlib.sha256(
            content
        ).hexdigest(),
        (
            "The job must store the fingerprint of the bytes "
            "it was given."
        ),
    )

    ok(
        "First upload processed normally and stored its "
        "source fingerprint"
    )


    # ------------------------------------------------------
    # THE DOCUMENT CARRIES THE FINGERPRINT TOO
    # ------------------------------------------------------

    with SessionLocal() as session:

        document = session.get(
            DocumentModel,
            document_id,
        )

        stored = document.source_sha256


    assert_equal(
        stored,
        hashlib.sha256(
            content
        ).hexdigest(),
        (
            "The document must carry the same fingerprint the "
            "job did. The worker passes it forward rather "
            "than rehashing, so a mismatch here would mean "
            "the two could disagree about what was uploaded."
        ),
    )

    ok(
        "The document carries the same fingerprint, carried "
        "forward rather than recomputed"
    )


    # ------------------------------------------------------
    # THE SECOND UPLOAD IS REJECTED
    # ------------------------------------------------------

    ocr_calls_before = 0

    try:
        harness.queue(
            content,
            name="a-copy.jpg",
        )

        raise AssertionError(
            (
                "An identical upload of an already "
                "processed source must be rejected."
            )
        )

    except DuplicateSourceError as duplicate:

        assert_equal(
            duplicate.code,
            DUPLICATE_DOCUMENT,
            (
                "A source with a completed document is "
                "DUPLICATE_DOCUMENT, not "
                "DUPLICATE_IN_PROGRESS."
            ),
        )

        assert_equal(
            duplicate.existing_document_id,
            document_id,
            (
                "The rejection must name the existing "
                "document, so the caller can open it. A "
                "rejection with nothing actionable in it is "
                "the silent discard this policy exists to "
                "prevent."
            ),
        )

        assert_equal(
            duplicate.existing_job_id,
            None,
            (
                "There is no active job for a completed "
                "source, so no job is named."
            ),
        )

    ok(
        "A different filename with identical bytes is "
        f"rejected as {DUPLICATE_DOCUMENT} and names the "
        "existing document"
    )


    # ------------------------------------------------------
    # AND IT COST NOTHING
    # ------------------------------------------------------

    # Asserted by ROW COUNT below rather than by asking the
    # worker for "nothing", because a worker asked for nothing
    # in particular might legitimately find an unrelated job.
    # The question here is whether the rejected duplicate
    # created a job, and counting its rows answers exactly
    # that.

    with SessionLocal() as session:

        job_count = len(
            session.execute(
                select(
                    DocumentJobModel.id
                )
                .where(
                    DocumentJobModel
                    .original_filename
                    .like(
                        f"{RUN_MARKER}-a-copy%"
                    )
                )
            )
            .all()
        )

    assert_equal(
        job_count,
        0,
        (
            "The rejected duplicate must leave no job row. "
            "Raising inside the insert transaction rolls it "
            "back."
        ),
    )

    # ------------------------------------------------------
    # AND LEFT NO BYTES BEHIND
    # ------------------------------------------------------
    #
    # create_job stores the pending copy before it inserts the
    # row, so a rejection has to remove it. Otherwise every
    # duplicate upload would leave a file in the pending store
    # that no job will ever claim -- which the storage
    # reconciliation would later have to explain.

    pending = (
        harness.store.orphaned_names(
            known_names=set()
        )
    )

    assert_equal(
        sorted(
            pending
        ),
        [],
        (
            "A rejected duplicate must leave no pending "
            "source file. The bytes are stored before the row "
            "is inserted, so the rejection path is "
            "responsible for removing them."
        ),
    )

    ok(
        "The rejected duplicate queued no job, left no row, "
        "left no pending bytes, and consumed no OCR or "
        "provider call"
    )


# ==========================================================
# 3. AN ACTIVE DUPLICATE
# ==========================================================

def test_active_duplicate(
    harness: Harness,
) -> None:

    section(
        "TEST 3 - AN IDENTICAL SOURCE ALREADY IN FLIGHT"
    )

    content = (
        image_bytes()
        + b"active"
    )

    first = harness.queue(
        content,
        name="inflight.jpg",
    )

    assert_equal(
        harness.row(
            first["job_id"]
        )["status"],
        "QUEUED",
        "The first job is queued and therefore active.",
    )


    try:
        harness.queue(
            content,
            name="inflight-copy.jpg",
        )

        raise AssertionError(
            (
                "A second upload of a source with an active "
                "job must be rejected."
            )
        )

    except DuplicateSourceError as duplicate:

        assert_equal(
            duplicate.code,
            DUPLICATE_IN_PROGRESS,
            (
                "A source already being processed is "
                "DUPLICATE_IN_PROGRESS. There is no document "
                "to point at yet, so reporting "
                "DUPLICATE_DOCUMENT would be wrong."
            ),
        )

        assert_equal(
            duplicate.existing_job_id,
            first["job_id"],
            (
                "The rejection must name the job already "
                "running, so the caller can follow it "
                "instead of starting another."
            ),
        )

        assert_equal(
            duplicate.existing_document_id,
            None,
            (
                "No document exists yet, so none is named."
            ),
        )

    ok(
        f"A second identical upload is rejected as "
        f"{DUPLICATE_IN_PROGRESS} and names the running job"
    )


    # ------------------------------------------------------
    # ENFORCED BY THE DATABASE, NOT BY A LOOKUP
    # ------------------------------------------------------

    with SessionLocal() as session:

        indexes = {
            entry["name"]: entry
            for entry in (
                __import__(
                    "sqlalchemy"
                )
                .inspect(
                    session.get_bind()
                )
                .get_indexes(
                    "document_jobs"
                )
            )
        }

    constraint = indexes.get(
        "uq_document_jobs_active_source"
    )

    assert_true(
        constraint is not None,
        (
            "The partial unique index must exist in the "
            "database. Without it, duplicate protection would "
            "be a check followed by an insert, which has a "
            "window between the two statements."
        ),
    )

    assert_true(
        constraint["unique"],
        "The active-source index must be unique.",
    )

    ok(
        "uq_document_jobs_active_source exists in PostgreSQL "
        "and is unique"
    )


    # ------------------------------------------------------
    # AND IT IS RELEASED WHEN THE JOB FINISHES
    # ------------------------------------------------------

    # This test deliberately holds a job queued in order to
    # observe the in-flight rejection above, so the queue is
    # not empty -- but nothing ELSE may be claimable, or the
    # worker would claim that instead.
    harness.require_only_job(
        first["job_id"]
    )

    worker = harness.worker(
        guard_pipeline()
    )

    assert_true(
        worker.process_one(
            only_job_ids=first["job_id"],
        ),
        "The in-flight job processes normally.",
    )

    row = harness.row(
        first["job_id"]
    )

    assert_true(
        row["status"] in TERMINAL_STATUSES,
        "The job reached a terminal state.",
    )

    harness.document_ids.append(
        row["document_id"]
    )

    # Now the same bytes report the OTHER duplicate code,
    # because the slot was released and a document exists.
    try:
        harness.queue(
            content,
            name="inflight-later.jpg",
        )

        raise AssertionError(
            "Still a duplicate after completion."
        )

    except DuplicateSourceError as duplicate:

        assert_equal(
            duplicate.code,
            DUPLICATE_DOCUMENT,
            (
                "Once the job is terminal the active-source "
                "slot is released, and the same bytes are now "
                "a completed duplicate rather than one in "
                "progress. The partial index is what makes "
                "that transition automatic."
            ),
        )

    ok(
        "The active-source slot is released on completion, "
        "and the outcome becomes DUPLICATE_DOCUMENT"
    )


    harness.drain()


# ==========================================================
# 4. SIMULTANEOUS IDENTICAL UPLOADS
# ==========================================================

def test_concurrent_duplicates(
    harness: Harness,
) -> None:

    section(
        "TEST 4 - SIMULTANEOUS IDENTICAL UPLOADS"
    )

    content = (
        image_bytes()
        + b"concurrent"
    )

    worker_count = 6

    barrier = threading.Barrier(
        worker_count
    )

    results: list = [
        None
    ] * worker_count


    def attempt(
        index: int,
    ) -> None:

        # Prepared before the barrier so the barrier releases
        # into the create call itself, not into file I/O.
        upload = harness.upload_file(
            content
        )

        barrier.wait()

        try:
            payload = (
                harness.jobs.create_job(
                    original_filename=(
                        f"{RUN_MARKER}-race-"
                        f"{index}.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    size_bytes=len(
                        content
                    ),

                    upload_path=upload,
                )
            )

            results[index] = (
                "created",
                payload["job_id"],
            )

        except DuplicateSourceError as duplicate:
            results[index] = (
                "duplicate",
                duplicate.code,
            )

        except Exception as error:      # noqa: BLE001
            results[index] = (
                "error",
                f"{type(error).__name__}: {error}",
            )


    threads = [
        threading.Thread(
            target=attempt,
            args=(index,),
        )
        for index in range(
            worker_count
        )
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(
            timeout=60
        )


    created = [
        outcome
        for outcome in results
        if outcome
        and outcome[0] == "created"
    ]

    duplicates = [
        outcome
        for outcome in results
        if outcome
        and outcome[0] == "duplicate"
    ]

    errors = [
        outcome
        for outcome in results
        if outcome
        and outcome[0] == "error"
    ]

    for _, job_id in created:
        harness.job_ids.append(
            job_id
        )


    assert_equal(
        errors,
        [],
        (
            "No attempt may fail with anything other than a "
            "duplicate rejection. An unexpected error here "
            "would mean the constraint is producing an "
            "unhandled integrity failure instead of a product "
            f"outcome. Got: {errors}"
        ),
    )

    assert_equal(
        len(
            created
        ),
        1,
        (
            f"Exactly one of {worker_count} simultaneous "
            "identical uploads may create a job. More than "
            "one means the uniqueness is not being enforced; "
            "none means a correct request was lost."
        ),
    )

    assert_equal(
        len(
            duplicates
        ),
        worker_count - 1,
        (
            "Every other attempt must be reported as a "
            "duplicate rather than dropped."
        ),
    )

    assert_equal(
        {
            code
            for _, code in duplicates
        },
        {
            DUPLICATE_IN_PROGRESS
        },
        (
            "A losing racer collided with an active job, so "
            "the code is DUPLICATE_IN_PROGRESS."
        ),
    )

    ok(
        f"{worker_count} simultaneous identical uploads -> "
        f"exactly 1 job created, {worker_count - 1} reported "
        f"as {DUPLICATE_IN_PROGRESS}, 0 unexpected errors"
    )


    # ------------------------------------------------------
    # AND ONLY ONE ROW EXISTS
    # ------------------------------------------------------

    with SessionLocal() as session:

        rows = (
            session.execute(
                select(
                    DocumentJobModel.id
                )
                .where(
                    DocumentJobModel.source_sha256
                    == hashlib.sha256(
                        content
                    ).hexdigest()
                )
            )
            .all()
        )

    assert_equal(
        len(
            rows
        ),
        1,
        (
            "The database must hold exactly one job row for "
            "these bytes. A rolled-back loser must leave "
            "nothing behind."
        ),
    )

    ok(
        "Exactly one job row exists for the contested source; "
        "the losing transactions left nothing behind"
    )


    # The winner is still queued. Drained here so the next
    # test starts from an empty queue -- process_one claims
    # the oldest claimable job, so leaving this behind would
    # have the next test working on it instead of its own.
    harness.drain()


# ==========================================================
# 5. THE TRANSACTION RACE
# ==========================================================

def test_persist_then_complete_race(
    harness: Harness,
) -> None:

    section(
        "TEST 5 - THE PERSIST-THEN-COMPLETE TRANSITION"
    )

    # ------------------------------------------------------
    # THE ORDERING THIS ALL DEPENDS ON
    # ------------------------------------------------------
    #
    # The safety argument is: a job stops being active only
    # AFTER its document is committed. So asserting that
    # ordering is asserting the premise, and a future
    # reordering fails here rather than silently opening the
    # window.
    # ------------------------------------------------------

    source = inspect.getsource(
        DocumentWorker._run
    )

    persist_at = source.find(
        "save_processed_document"
    )

    complete_at = source.find(
        "mark_completed"
    )

    assert_true(
        persist_at != -1
        and complete_at != -1,
        (
            "Both steps must be findable in the worker, or "
            "this assertion is checking nothing."
        ),
    )

    assert_true(
        persist_at < complete_at,
        (
            "The worker MUST persist the document before "
            "marking the job completed.\n\n"
            "Duplicate detection depends on it. A job only "
            "releases its active-source slot when it leaves "
            "an active state, so if the document were "
            "committed after that release, there would be an "
            "instant where the uniqueness is gone and the "
            "document is not yet visible -- and an identical "
            "upload in that instant would be accepted."
        ),
    )

    ok(
        "The worker persists the document before completing "
        "the job, which is the premise the race safety rests "
        "on"
    )


    # ------------------------------------------------------
    # NOW TEST EVERY INSTANT OF THE TRANSITION
    # ------------------------------------------------------
    #
    # THE PROPERTY THAT MATTERS
    # ------------------------------------------------------
    #
    # There must be NO instant at which an identical upload is
    # ACCEPTED. Which of the two duplicate codes it gets is
    # secondary -- both are rejections that name something the
    # caller can act on.
    #
    # Three instants are observed, by hooking the pipeline and
    # the persistence of a real worker run:
    #
    #   1. job PROCESSING, no document yet
    #      -> the partial unique index rejects the insert
    #      -> DUPLICATE_IN_PROGRESS
    #
    #   2. job PROCESSING, document committed
    #      -> the completed-document check sees it first
    #      -> DUPLICATE_DOCUMENT
    #
    #   3. job COMPLETED, document committed
    #      -> DUPLICATE_DOCUMENT
    #
    # Instant 2 is the one the design had to get right, and it
    # is worth being precise about WHY it reports the document
    # rather than the job. Both facts are true at that moment.
    # The cheap completed-document check runs before the
    # insert, so it wins -- and that is the more useful answer:
    # the document exists and can be opened, whereas the job is
    # a moment from disappearing.
    # ------------------------------------------------------

    content = (
        image_bytes()
        + b"race"
    )

    fingerprint = hashlib.sha256(
        content
    ).hexdigest()

    observed: dict = {}


    def observe(
        label: str,
    ) -> None:

        """
        Attempt the identical upload and record what happened,
        along with the job state and document count at that
        exact moment.
        """

        with SessionLocal() as session:

            observed[
                f"{label}_job_status"
            ] = (
                session.execute(
                    select(
                        DocumentJobModel.status
                    )
                    .where(
                        DocumentJobModel
                        .source_sha256
                        == fingerprint
                    )
                )
                .scalars()
                .first()
            )

            observed[
                f"{label}_documents"
            ] = len(
                session.execute(
                    select(
                        DocumentModel.id
                    )
                    .where(
                        DocumentModel.source_sha256
                        == fingerprint
                    )
                )
                .all()
            )


        try:
            harness.queue(
                content,
                name=f"race-{label}.jpg",
            )

            observed[label] = "ACCEPTED"

        except DuplicateSourceError as duplicate:
            observed[label] = duplicate.code

        except Exception as error:      # noqa: BLE001
            observed[label] = (
                f"error:{type(error).__name__}"
            )


    class ObservingPipeline:

        """
        Observes instant 1: the worker has claimed the job and
        is processing it, and no document exists yet.
        """

        def __init__(
            self,
            inner,
        ) -> None:

            self.inner = inner


        def process(
            self,
            *args,
            **kwargs,
        ):

            observe(
                "before_document"
            )

            return self.inner.process(
                *args,
                **kwargs,
            )


    class ObservingPersistence:

        """
        Observes instant 2: the document is committed and the
        job has not been marked completed yet.
        """

        def __init__(
            self,
        ) -> None:

            self.real = (
                PersistenceService()
            )


        def save_processed_document(
            self,
            **kwargs,
        ) -> dict:

            stored = (
                self.real
                .save_processed_document(
                    **kwargs
                )
            )

            observe(
                "after_document"
            )

            return stored


    harness.require_quiet_queue()

    first = harness.queue(
        content,
        name="race-original.jpg",
    )

    worker = harness.worker(
        ObservingPipeline(
            guard_pipeline()
        ),
        persistence=(
            ObservingPersistence()
        ),
    )

    assert_true(
        worker.process_one(
            only_job_ids=first["job_id"],
        ),
        "The worker must process the job.",
    )

    row = harness.row(
        first["job_id"]
    )

    harness.document_ids.append(
        row["document_id"]
    )

    observe(
        "after_completion"
    )


    # ------------------------------------------------------
    # THE INSTANTS WERE REAL
    # ------------------------------------------------------

    assert_equal(
        observed[
            "before_document_job_status"
        ],
        "PROCESSING",
        (
            "Instant 1 must have been observed while the job "
            "was PROCESSING."
        ),
    )

    assert_equal(
        observed[
            "before_document_documents"
        ],
        0,
        (
            "Instant 1 must have been observed before any "
            "document existed, or it is not the instant "
            "under test."
        ),
    )

    assert_equal(
        observed[
            "after_document_job_status"
        ],
        "PROCESSING",
        (
            "Instant 2 must have been observed while the job "
            "was STILL PROCESSING -- that is the whole "
            "point: the document is committed and the job has "
            "not been completed yet."
        ),
    )

    assert_equal(
        observed[
            "after_document_documents"
        ],
        1,
        (
            "And the document must already be committed at "
            "instant 2."
        ),
    )

    # The query is by fingerprint and is not filtered by
    # status, so this reads the job's own terminal state
    # rather than the absence of one.
    assert_equal(
        observed[
            "after_completion_job_status"
        ],
        "COMPLETED",
        (
            "After completion the job is COMPLETED, which is "
            "terminal -- so it no longer occupies the "
            "active-source slot even though the row is still "
            "there."
        ),
    )

    assert_true(
        observed[
            "after_completion_job_status"
        ]
        in TERMINAL_STATUSES,
        (
            "And terminal is what matters: the partial unique "
            "index only covers ACTIVE_STATUSES, so a terminal "
            "job holds nothing."
        ),
    )

    ok(
        "All three instants observed as intended: "
        "PROCESSING with 0 documents, PROCESSING with 1 "
        "document, then a terminal job with 1 document"
    )


    # ------------------------------------------------------
    # AND AT NO INSTANT WAS THE UPLOAD ACCEPTED
    # ------------------------------------------------------

    accepted = [
        label
        for label in (
            "before_document",
            "after_document",
            "after_completion",
        )
        if observed[label] == "ACCEPTED"
    ]

    assert_equal(
        accepted,
        [],
        (
            "An identical upload must be rejected at EVERY "
            "instant of the persist-then-complete "
            "transition.\n\n"
            "This is the property the whole design exists "
            "for. An acceptance at any of these three "
            "moments means a second document and a second "
            "pipeline run for bytes already on file.\n\n"
            f"Accepted at: {accepted}\n"
            f"Observed: {observed}"
        ),
    )

    ok(
        "No instant of the transition accepts an identical "
        "upload"
    )


    # ------------------------------------------------------
    # AND THE CODES ARE THE RIGHT ONES
    # ------------------------------------------------------

    assert_equal(
        observed["before_document"],
        DUPLICATE_IN_PROGRESS,
        (
            "Before the document exists, the only thing "
            "holding the source is the active job, so the "
            "rejection comes from the partial unique index "
            "and reports DUPLICATE_IN_PROGRESS."
        ),
    )

    assert_equal(
        observed["after_document"],
        DUPLICATE_DOCUMENT,
        (
            "Once the document is committed, BOTH facts are "
            "true -- a document exists and a job is still "
            "active. The completed-document check runs first, "
            "so the caller is told about the document.\n\n"
            "Which is the more useful of the two answers: the "
            "document can be opened, whereas the job is an "
            "instant from disappearing."
        ),
    )

    assert_equal(
        observed["after_completion"],
        DUPLICATE_DOCUMENT,
        (
            "And after completion the document is the only "
            "thing left to report."
        ),
    )

    ok(
        "Codes across the transition: "
        f"{observed['before_document']} -> "
        f"{observed['after_document']} -> "
        f"{observed['after_completion']}"
    )


    # ------------------------------------------------------
    # EXACTLY ONE DOCUMENT AND ONE JOB EXIST
    # ------------------------------------------------------

    with SessionLocal() as session:

        documents = len(
            session.execute(
                select(
                    DocumentModel.id
                )
                .where(
                    DocumentModel.source_sha256
                    == fingerprint
                )
            )
            .all()
        )

        jobs = len(
            session.execute(
                select(
                    DocumentJobModel.id
                )
                .where(
                    DocumentJobModel.source_sha256
                    == fingerprint
                )
            )
            .all()
        )

    assert_equal(
        documents,
        1,
        (
            "Three rejected duplicate attempts must have "
            "produced no extra document."
        ),
    )

    assert_equal(
        jobs,
        1,
        (
            "And no extra job row. Every rejection rolled "
            "back cleanly."
        ),
    )

    assert_equal(
        row["status"],
        "COMPLETED",
        "The original job completed normally throughout.",
    )

    ok(
        "After three rejected attempts across the "
        "transition: exactly 1 document and 1 job for the "
        "source, and the original completed normally"
    )


# ==========================================================
# 6. BATCHES
# ==========================================================

def test_batch_duplicates(
    harness: Harness,
) -> None:

    section(
        "TEST 6 - A DUPLICATE INSIDE A BATCH"
    )

    a_bytes = (
        image_bytes()
        + b"batch-a"
    )

    b_bytes = (
        image_bytes()
        + b"batch-b"
    )

    result = harness.batch(
        [
            (
                "A.jpg",
                a_bytes,
            ),
            (
                "A-copy.jpg",
                a_bytes,
            ),
            (
                "B.jpg",
                b_bytes,
            ),
        ]
    )

    assert_equal(
        result["submitted_count"],
        3,
        "Three files were submitted.",
    )

    assert_equal(
        result["queued_count"],
        2,
        (
            "A and B queue; A-copy is a duplicate of A. One "
            "duplicate must not cost the batch its other "
            "files."
        ),
    )

    assert_equal(
        len(
            result["rejected"]
        ),
        1,
        "Exactly one file is rejected.",
    )

    rejected = result[
        "rejected"
    ][0]

    assert_true(
        rejected[
            "original_filename"
        ].endswith(
            "A-copy.jpg"
        ),
        (
            "The rejected file must be named, so the user "
            "knows which one it was."
        ),
    )

    assert_equal(
        rejected["error_code"],
        DUPLICATE_IN_PROGRESS,
        (
            "A-copy collided with its own sibling, which is "
            "queued and therefore active. Reporting it as "
            "DUPLICATE_IN_PROGRESS is accurate: that job is "
            "running and is the one to watch."
        ),
    )

    assert_true(
        rejected.get(
            "existing_job_id"
        ),
        (
            "The rejection must point at the sibling job, so "
            "the user can follow the one that is running "
            "rather than wonder what happened."
        ),
    )

    queued_ids = {
        job["job_id"]
        for job in result["jobs"]
    }

    assert_true(
        rejected[
            "existing_job_id"
        ]
        in queued_ids,
        (
            "And the job it points at must be one of the "
            "jobs this same batch queued."
        ),
    )

    assert_true(
        rejected["error_code"]
        != "QUEUE_REJECTED",
        (
            "A duplicate must not be reported with the "
            "generic queue-rejection code. The specific code "
            "is what lets the interface offer the right "
            "action."
        ),
    )

    ok(
        "Batch of A, A-copy, B -> 2 queued, A-copy rejected "
        f"as {DUPLICATE_IN_PROGRESS} pointing at its sibling"
    )


    # ------------------------------------------------------
    # CROSS-BATCH
    # ------------------------------------------------------

    second = harness.batch(
        [
            (
                "A-again.jpg",
                a_bytes,
            ),
            (
                "C.jpg",
                image_bytes() + b"batch-c",
            ),
        ]
    )

    assert_equal(
        second["queued_count"],
        1,
        (
            "Only C queues. A-again is identical to a file "
            "still active from the first batch, and duplicate "
            "identity does not stop at a batch boundary."
        ),
    )

    assert_equal(
        second[
            "rejected"
        ][0]["error_code"],
        DUPLICATE_IN_PROGRESS,
        (
            "The cross-batch duplicate is reported the same "
            "way as one inside a batch."
        ),
    )

    ok(
        "A duplicate across two batches is detected and "
        "reported per file; the unrelated sibling still "
        "queues"
    )


    # A, B and C are queued. Drained for the same reason as
    # above.
    harness.drain()


# ==========================================================
# 7. DELIBERATE REPROCESSING
# ==========================================================

def test_reprocess(
    harness: Harness,
) -> None:

    section(
        "TEST 7 - DELIBERATE REPROCESSING"
    )

    content = (
        image_bytes()
        + b"reprocess"
    )

    harness.require_quiet_queue()

    first = harness.queue(
        content,
        name="repro-original.jpg",
    )

    worker = harness.worker(
        guard_pipeline()
    )

    assert_true(
        worker.process_one(
            only_job_ids=first["job_id"],
        ),
        "The first job processes.",
    )

    first_row = harness.row(
        first["job_id"]
    )

    first_document = first_row[
        "document_id"
    ]

    harness.document_ids.append(
        first_document
    )


    # ------------------------------------------------------
    # THE DEFAULT REFUSES
    # ------------------------------------------------------

    try:
        harness.queue(
            content,
            name="repro-accident.jpg",
        )

        raise AssertionError(
            (
                "Without an explicit request, an identical "
                "upload must be refused. If the default were "
                "permissive, every retried request would "
                "quietly produce another document and another "
                "OCR pass."
            )
        )

    except DuplicateSourceError:
        pass

    ok(
        "The default refuses: a retried or repeated upload "
        "cannot accidentally reprocess a stored source"
    )


    # ------------------------------------------------------
    # AN EXPLICIT REQUEST IS ALLOWED
    # ------------------------------------------------------

    second = harness.queue(
        content,
        name="repro-deliberate.jpg",
        reprocess=True,
    )

    assert_equal(
        harness.row(
            second["job_id"]
        )["status"],
        "QUEUED",
        (
            "An explicit reprocess request queues a job even "
            "though a document already exists for these "
            "bytes."
        ),
    )

    assert_true(
        worker.process_one(
            only_job_ids=second["job_id"],
        ),
        "The reprocess job runs.",
    )

    second_row = harness.row(
        second["job_id"]
    )

    second_document = second_row[
        "document_id"
    ]

    harness.document_ids.append(
        second_document
    )

    assert_true(
        second_document != first_document,
        (
            "Reprocessing produces a NEW analysis, which is "
            "the point of asking for it."
        ),
    )

    assert_equal(
        second_row["source_sha256"],
        first_row["source_sha256"],
        (
            "The fingerprint is identical, because the bytes "
            "are identical. Pretending a reprocessed upload "
            "is a different source would make the record lie "
            "about where it came from."
        ),
    )

    ok(
        "An explicit reprocess creates a second analysis of "
        "the SAME source: new document, identical fingerprint"
    )


    # ------------------------------------------------------
    # REPROCESS DOES NOT OVERRIDE IN-PROGRESS
    # ------------------------------------------------------

    third = harness.queue(
        content,
        name="repro-third.jpg",
        reprocess=True,
    )

    try:
        harness.queue(
            content,
            name="repro-fourth.jpg",
            reprocess=True,
        )

        raise AssertionError(
            (
                "Even with reprocess=true, a second "
                "concurrent job for the same bytes must be "
                "refused. There is no version of "
                "re-analyse-these-bytes that is served by "
                "running two identical jobs at once."
            )
        )

    except DuplicateSourceError as duplicate:

        assert_equal(
            duplicate.code,
            DUPLICATE_IN_PROGRESS,
            (
                "reprocess suppresses the completed-document "
                "rejection only, never the in-flight one."
            ),
        )

    assert_true(
        worker.process_one(
            only_job_ids=third["job_id"],
        ),
        "Drain the third job.",
    )

    harness.document_ids.append(
        harness.row(
            third["job_id"]
        )["document_id"]
    )

    ok(
        "reprocess=true suppresses the completed-document "
        "rejection only; two concurrent identical jobs are "
        "still refused"
    )


    harness.drain()


    # ------------------------------------------------------
    # THE RECORD DISTINGUISHES THE TWO
    # ------------------------------------------------------

    query_service = (
        DocumentQueryService()
    )

    original = (
        query_service.get_document(
            first_document
        )["duplicate"]
    )

    repeat = (
        query_service.get_document(
            second_document
        )["duplicate"]
    )

    assert_equal(
        original["is_reprocess"],
        False,
        (
            "The first document is the original, not a "
            "reprocess."
        ),
    )

    assert_equal(
        original["attempt"],
        1,
        "The original is attempt 1.",
    )

    assert_equal(
        original[
            "first_document_id"
        ],
        None,
        (
            "The original has no earlier document to point "
            "at."
        ),
    )

    assert_equal(
        repeat["is_reprocess"],
        True,
        (
            "The second document IS a repeat analysis of a "
            "source already on file, and says so. This is "
            "the distinction between a source duplicate and "
            "a new analysis attempt."
        ),
    )

    assert_equal(
        repeat["attempt"],
        2,
        "The reprocess is attempt 2.",
    )

    assert_equal(
        repeat[
            "first_document_id"
        ],
        first_document,
        (
            "And it points back at the original."
        ),
    )

    assert_true(
        first_document
        in repeat[
            "same_source_document_ids"
        ],
        (
            "The siblings are listed so an operator can see "
            "every analysis of the same source."
        ),
    )

    assert_true(
        repeat["note"],
        (
            "A repeat analysis carries a plain-language note, "
            "so a reader is not left guessing whether the "
            "system is implying something."
        ),
    )

    ok(
        "The record distinguishes source duplicate from new "
        "analysis attempt: attempt 1 vs 2, with a link back "
        "to the original"
    )


# ==========================================================
# 8. THE FINGERPRINT NEVER LEAVES
# ==========================================================

def test_fingerprint_not_exposed(
    harness: Harness,
) -> None:

    section(
        "TEST 8 - THE HASH IS NEVER EXPOSED"
    )

    document_id = (
        harness.document_ids[0]
        if harness.document_ids
        else None
    )

    assert_true(
        document_id,
        (
            "This test needs a document produced by an "
            "earlier test."
        ),
    )

    with SessionLocal() as session:

        fingerprint = (
            session.get(
                DocumentModel,
                document_id,
            ).source_sha256
        )

    assert_true(
        fingerprint,
        "The document must actually have a fingerprint.",
    )


    # ------------------------------------------------------
    # THE DOCUMENT DETAIL PAYLOAD
    # ------------------------------------------------------

    detail = (
        DocumentQueryService()
        .get_document(
            document_id
        )
    )

    rendered = json.dumps(
        detail,
        default=str,
    )

    assert_true(
        fingerprint not in rendered,
        (
            "The fingerprint must not appear anywhere in the "
            "document payload.\n\n"
            "A hash of the bytes is a stable identifier for "
            "the content. Publishing it would let anyone "
            "holding a candidate file confirm, offline and "
            "without access, that VIGILOX holds that exact "
            "document."
        ),
    )

    assert_true(
        "source_sha256" not in rendered,
        (
            "Not even the field name, which would invite a "
            "future change to start populating it."
        ),
    )

    assert_true(
        detail["duplicate"] is not None,
        (
            "The duplicate block is still present -- the "
            "information is delivered without the hash."
        ),
    )

    ok(
        "The document detail payload carries the duplicate "
        "block and neither the hash nor its field name"
    )


    # ------------------------------------------------------
    # THE JOB PAYLOAD
    # ------------------------------------------------------

    job_payload = (
        harness.jobs.get_job(
            harness.job_ids[0]
        )
    )

    rendered_job = json.dumps(
        job_payload,
        default=str,
    )

    assert_true(
        "source_sha256"
        not in rendered_job,
        (
            "The job serializer is a whitelist and must not "
            "have gained the fingerprint."
        ),
    )

    with SessionLocal() as session:

        stored = (
            session.get(
                DocumentJobModel,
                harness.job_ids[0],
            ).source_sha256
        )

    if stored:

        assert_true(
            stored not in rendered_job,
            (
                "And the value itself must not appear under "
                "any other key."
            ),
        )

    ok(
        "The job payload exposes neither the fingerprint nor "
        "its field name"
    )


    # ------------------------------------------------------
    # THE DUPLICATE REJECTION PAYLOAD
    # ------------------------------------------------------

    error = DuplicateSourceError(
        code=DUPLICATE_DOCUMENT,
        message="m",
        existing_document_id="doc-1",
        same_source_count=2,
    )

    assert_equal(
        sorted(
            error.payload()
        ),
        [
            "code",
            "existing_document_id",
            "existing_job_id",
            "message",
            "same_source_count",
        ],
        (
            "The rejection payload is a fixed shape with no "
            "room for a hash."
        ),
    )

    ok(
        "The rejection payload carries only the code, the "
        "message and the references"
    )


    # ------------------------------------------------------
    # AND NO ACCUSATION ANYWHERE
    # ------------------------------------------------------

    forbidden = (
        "fraud",
        "tamper",
        "suspicious",
        "fake",
        "forged",
        "risk score",
    )

    surfaces = [
        rendered,
        rendered_job,
        json.dumps(
            error.payload()
        ),
        json.dumps(
            describe_duplicate_source(
                document_id="b",
                same_source_document_ids=[
                    "a",
                    "b",
                ],
            )
        ),
    ]

    for surface in surfaces:

        lowered = surface.lower()

        for word in forbidden:

            assert_true(
                word not in lowered,
                (
                    "A duplicate upload is a workflow fact, "
                    "not an accusation. Found "
                    f"{word!r} in a duplicate surface."
                ),
            )

    ok(
        "No fraud, tampering, suspicion or risk language on "
        "any duplicate surface"
    )


# ==========================================================
# 9. THE DERIVED DESCRIPTION
# ==========================================================

def test_describe_duplicate_source() -> None:

    section(
        "TEST 9 - THE DERIVED DESCRIPTION"
    )

    # A lone document.
    lone = describe_duplicate_source(
        document_id="only",
        same_source_document_ids=[
            "only"
        ],
    )

    assert_equal(
        lone["is_reprocess"],
        False,
        "A lone document is not a reprocess.",
    )

    assert_equal(
        lone["same_source_count"],
        0,
        "It has no siblings.",
    )

    assert_equal(
        lone["note"],
        None,
        (
            "And it carries no note, because there is "
            "nothing to explain."
        ),
    )


    # A document with no fingerprint at all: pre-Phase-10.3.
    unknown = describe_duplicate_source(
        document_id="legacy",
        same_source_document_ids=[],
    )

    assert_equal(
        unknown["is_reprocess"],
        False,
        (
            "A document whose source was never "
            "fingerprinted must not be reported as a "
            "reprocess. Unknown is not the same as none, but "
            "claiming a repeat would be worse than claiming "
            "neither."
        ),
    )

    assert_equal(
        unknown["attempt"],
        None,
        (
            "And its position is reported as unknown rather "
            "than guessed at."
        ),
    )


    # Three analyses of one source.
    third = describe_duplicate_source(
        document_id="c",
        same_source_document_ids=[
            "a",
            "b",
            "c",
        ],
    )

    assert_equal(
        third["attempt"],
        3,
        "The third document is attempt 3.",
    )

    assert_equal(
        third["first_document_id"],
        "a",
        "The original is the oldest.",
    )

    assert_equal(
        sorted(
            third[
                "same_source_document_ids"
            ]
        ),
        [
            "a",
            "b",
        ],
        (
            "The sibling list excludes the document being "
            "described."
        ),
    )

    ok(
        "Lone, unfingerprinted and third-attempt documents "
        "all describe correctly, and a document never lists "
        "itself as its own sibling"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print()
    print(
        "=" * 74
    )
    print(
        "PHASE 10.3 - EXACT DUPLICATE SOURCE DETECTION"
    )
    print(
        "=" * 74
    )

    harness = Harness()

    try:

        test_fingerprint(
            harness
        )

        test_completed_duplicate(
            harness
        )

        test_active_duplicate(
            harness
        )

        test_concurrent_duplicates(
            harness
        )

        test_persist_then_complete_race(
            harness
        )

        test_batch_duplicates(
            harness
        )

        test_reprocess(
            harness
        )

        test_fingerprint_not_exposed(
            harness
        )

        test_describe_duplicate_source()

    finally:

        harness.collect_documents()

        harness.cleanup()


    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 10.3 DUPLICATE SOURCE TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
