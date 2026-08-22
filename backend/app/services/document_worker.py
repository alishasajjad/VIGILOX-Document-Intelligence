import logging
import os
import socket
import threading
import uuid

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from database.database import (
    SessionLocal,
)

from database.job_repositories import (
    DocumentJobRepository,
)

from backend.app.core.logging import (
    get_operational_logger,
)

from backend.app.core.timing import (
    StageTimer,
)

from backend.app.services.worker_health_service import (
    WorkerHeartbeatWriter,
)

from backend.app.domain.job_states import (
    JOB_ERROR_ABANDONED,
    JOB_ERROR_ATTEMPTS_EXHAUSTED,
    JOB_ERROR_SOURCE_MISSING,
    STAGE_EXTRACTING,
    STAGE_OCR,
    STAGE_PERSISTING,
    STAGE_READING,
    safe_message,
)

from backend.app.services.job_failure_classifier import (
    JobDataError,
    classify,
    retry_delay_seconds,
)

from backend.app.services.job_service import (
    JobService,
)

from backend.app.services.job_source_store import (
    JobSourceSecurityError,
)


# ==========================================================
# DOCUMENT WORKER
# PHASE 9.3
# ==========================================================
#
# The process that actually does the work. Claims a job, runs
# the existing pipeline, persists the result, and decides what
# to do when something goes wrong.
#
#
# WHY EXPENSIVE SERVICES ARE BUILT ONCE
# ----------------------------------------------------------
#
# DocumentPipelineService constructs PaddleOCR, and the
# measured baseline is unambiguous: OCR is 100% of local
# pipeline time at an 18.4 second median. Model construction
# is roughly three seconds on cached models.
#
# So the pipeline is built once per worker process and reused
# for every job. Building it per job would add that three
# seconds to every document and multiply resident memory by
# the concurrency.
#
#
# WHY CONCURRENCY DEFAULTS TO 1
# ----------------------------------------------------------
#
# Not because one is fast, but because the measurement says
# more would not help. PaddleOCR is CPU-bound and already uses
# multiple threads internally, so N parallel OCR passes on one
# machine contend for the same cores and each one gets slower.
# Total throughput barely moves and peak memory multiplies.
#
# Deriving a default from cpu_count() would be exactly the
# wrong inference: the bottleneck is not "we have spare
# cores", it is one library saturating the cores it has.
#
# VIGILOX_WORKER_CONCURRENCY raises it deliberately, which is
# the right way to make that decision -- with a measurement,
# on the machine in question.
#
#
# THE SHAPE OF ONE JOB
# ----------------------------------------------------------
#
#   claim           one short transaction, FOR UPDATE
#                   SKIP LOCKED, commits the claim
#
#   process         no transaction held. This is the
#                   eighteen-second part, and holding a
#                   database transaction open across it
#                   would pin a connection and a row lock
#                   for the duration
#
#   finish          one short transaction to record the
#                   outcome
#
# The lease is what makes the middle safe. A worker that dies
# during processing leaves a row whose lease stops being
# extended, and reclaim() returns it to the queue.
# ==========================================================


DEFAULT_POLL_SECONDS = 2.0

DEFAULT_IDLE_POLL_SECONDS = 5.0

# ==========================================================
# LEASE
# ==========================================================
#
# RAISED FROM 180 IN PHASE 10.4, ON MEASUREMENT.
#
# The old value was set against a 32.8 second worst case and
# "room for a slow provider on top". Phase 10.4 measured what
# that room actually has to be, and 180 was not enough:
#
#     OCR                     28s median, 43s maximum
#                             (9 documents, real images)
#
#     extraction              1.18s median, 25.31s maximum
#
#     extraction worst case   220s
#                             bounded retries, one SDK retry,
#                             40s read timeout -- see
#                             ExtractionService.call_budget
#
#     pipeline worst case     268s
#
# The pipeline runs as ONE call between two stage markers, so
# the lease has to cover the whole of it in a single window.
# The worker cannot extend a lease from inside the pipeline.
#
# 360 gives that 268 seconds about a third again in headroom.
#
# WHAT THE OLD VALUE COST
# ----------------------------------------------------------
# Nothing incorrect: mark_completed is scoped to a job still
# PROCESSING under the same worker, so a worker that lost its
# lease cannot overwrite the new owner's outcome, and the
# document it created is discarded. But the work was wasted and
# it was silent -- a slow document would be processed twice and
# only the operational log would say so.
#
# WHAT THE NEW VALUE COSTS
# ----------------------------------------------------------
# A job whose worker actually crashed now waits up to 360
# seconds instead of 180 before another worker can reclaim it.
# That is the real trade, and it is the right way round: a
# crash is rare, and a legitimately slow document is not.
#
# test_call_budget_fits_lease asserts that the extraction
# configuration still fits inside this number, so changing
# either one without the other fails a test rather than
# quietly reintroducing the problem.
# ==========================================================

DEFAULT_LEASE_SECONDS = 360

DEFAULT_MAX_CONCURRENCY = 1


def _configured_float(
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:

    raw = os.getenv(
        name,
        "",
    ).strip()


    if not raw:
        return default


    try:
        value = float(
            raw
        )

    except ValueError:
        return default


    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


def _configured_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:

    return int(
        _configured_float(
            name,
            float(
                default
            ),
            float(
                minimum
            ),
            float(
                maximum
            ),
        )
    )


def default_worker_id() -> str:

    """
    Identifies this worker in job rows and logs.

    Host plus pid plus a short random suffix. The suffix
    matters: two workers in one container share a hostname, and
    pid alone repeats across restarts, so without it a
    restarted worker could look like the one that just died
    and its stale lease could be extended by its successor.
    """

    return (
        f"{socket.gethostname()}"
        f"-{os.getpid()}"
        f"-{uuid.uuid4().hex[:6]}"
    )


# ==========================================================
# JOB OUTCOME METRICS
# PHASE 11.11
# ==========================================================
#
# Counted at the three terminal points, by OUTCOME only.
#
# No job id, no document id, no filename in the label. Each of
# those would be one Prometheus time series per upload, held
# by the scraper forever -- and a filename is user-controlled
# text as well. The identifiers live in the structured log,
# correlated by request_id, which is the right place for
# high-cardinality detail.
#
# Swallowed on failure: a counter must never fail a job.
# ==========================================================

def _count_outcome(
    outcome: str,
) -> None:

    try:
        from backend.app.services.metrics_service import (
            record_job_outcome,
        )

        record_job_outcome(
            outcome
        )

    except Exception:
        pass


class DocumentWorker:

    def __init__(
        self,
        *,
        pipeline=None,
        persistence=None,
        job_service: JobService | None = None,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:

        """
        pipeline and persistence are injected so the whole
        worker can be tested deterministically -- a fake
        pipeline that raises a rate-limit error proves the
        retry path without a provider, and a fake that returns
        a fixed result proves the completion path in
        milliseconds.

        They default to the real services, constructed once.
        """

        self.worker_id = (
            worker_id
            or default_worker_id()
        )

        self.jobs = (
            job_service
            if job_service is not None
            else JobService()
        )

        self.lease_seconds = (
            lease_seconds
            if lease_seconds is not None
            else _configured_int(
                "VIGILOX_JOB_LEASE_SECONDS",
                DEFAULT_LEASE_SECONDS,
                30,
                3600,
            )
        )

        self.logger = (
            logger
            if logger is not None
            else get_operational_logger(
                "worker"
            )
        )

        self._pipeline = pipeline

        self._persistence = persistence

        # Counters, for the log line on shutdown and for
        # tests to assert against.
        self.processed = 0

        self.completed = 0

        self.failed = 0

        self.retried = 0

        self.reclaimed = 0


    # ======================================================
    # LAZY REAL SERVICES
    # ======================================================

    @property
    def pipeline(
        self,
    ):

        if self._pipeline is None:

            from backend.app.services.pipeline_service import (
                DocumentPipelineService,
            )

            self.logger.info(
                "Constructing document pipeline "
                "(OCR model load)."
            )

            self._pipeline = (
                DocumentPipelineService()
            )


        return self._pipeline


    @property
    def persistence(
        self,
    ):

        if self._persistence is None:

            from backend.app.services.persistence_service import (
                PersistenceService,
            )

            self._persistence = (
                PersistenceService()
            )


        return self._persistence


    # ======================================================
    # CLAIM
    # ======================================================

    def claim(
        self,
        *,
        only_job_ids=None,
    ) -> dict | None:

        """
        Take one job, or None.

        The transaction is deliberately tiny: it exists only
        to hold the row lock while the claim is written. The
        returned dict is a plain snapshot rather than an ORM
        instance, because the session closes on the way out
        and a detached instance would raise on attribute
        access -- quietly, inside the processing path, which
        would be an unpleasant way to find out.
        """

        with SessionLocal.begin() as session:

            job = (
                DocumentJobRepository(
                    session
                )
                .claim_next(
                    worker_id=(
                        self.worker_id
                    ),

                    lease_seconds=(
                        self.lease_seconds
                    ),

                    only_job_ids=(
                        only_job_ids
                    ),
                )
            )


            if job is None:
                return None


            return {
                "job_id":
                    job.id,

                "batch_id":
                    job.batch_id,

                "source_name":
                    job.source_name,

                # PHASE 10.3. Carried through the claim so
                # persistence can store it without hashing
                # the bytes a second time.
                "source_sha256":
                    job.source_sha256,

                "original_filename":
                    job.original_filename,

                "content_type":
                    job.content_type,

                "attempt_count":
                    job.attempt_count,

                "max_attempts":
                    job.max_attempts,
            }


    def _advance(
        self,
        job_id: str,
        stage: str,
    ) -> bool:

        """
        Record the stage now beginning and push the lease out.

        Returns False when this worker no longer owns the job,
        which happens when its lease expired and someone else
        reclaimed it. The caller must stop immediately: two
        workers persisting the same document is the failure
        this whole design exists to prevent.
        """

        with SessionLocal.begin() as session:

            return (
                DocumentJobRepository(
                    session
                )
                .extend_lease(
                    job_id=job_id,

                    worker_id=(
                        self.worker_id
                    ),

                    lease_seconds=(
                        self.lease_seconds
                    ),

                    stage=stage,
                )
            )


    # ======================================================
    # PROCESS ONE JOB
    # ======================================================

    def process_one(
        self,
        *,
        only_job_ids=None,
    ) -> bool:

        """
        Claim and process a single job.

        Returns True when a job was handled, False when the
        queue was empty. The caller uses that to decide how
        long to sleep.

        only_job_ids restricts the claim to one job, or a
        set of them. The continuous worker loop never passes
        it -- it wants whatever is next. See
        DocumentJobRepository.claim_next for who does.
        """

        claimed = (
            self.claim(
                only_job_ids=only_job_ids,
            )
        )


        if claimed is None:
            return False


        job_id = claimed[
            "job_id"
        ]

        self.processed += 1

        timer = (
            StageTimer()
        )


        try:
            self._run(
                claimed,
                timer,
            )

        except _LostLease:

            # Not an error. Another worker owns this job now,
            # and it will finish it.
            self.logger.warning(
                "Lease lost; abandoning job.",
                extra={
                    "event":
                        "job.lease_lost",

                    "job_id":
                        job_id,
                },
            )

        except Exception as error:      # noqa: BLE001

            self._handle_failure(
                claimed,
                error,
                timer,
            )


        return True


    def _run(
        self,
        claimed: dict,
        timer: StageTimer,
    ) -> None:

        job_id = claimed[
            "job_id"
        ]

        source_name = claimed[
            "source_name"
        ]


        # ------------------------------------------------------
        # READING
        # ------------------------------------------------------

        try:
            source_path = (
                self.jobs
                .source_store
                .pending_path(
                    source_name
                )
            )

        except JobSourceSecurityError as error:

            # The row carries a name this store would never
            # have written. Not retryable -- the data is bad,
            # not the moment.
            raise JobDataError(
                "The job's source reference is not "
                "usable."
            ) from error


        if not source_path.is_file():

            raise FileNotFoundError(
                "The pending upload is gone."
            )


        # ------------------------------------------------------
        # OCR, EXTRACTION, VALIDATION
        # ------------------------------------------------------
        #
        # The pipeline is one call, so the stage markers around
        # it are necessarily coarse. OCR is written before it
        # starts because OCR is where all the time goes -- if a
        # job is sitting in PROCESSING, OCR is what it is
        # almost certainly doing.
        # ------------------------------------------------------

        if not self._advance(
            job_id,
            STAGE_OCR,
        ):
            raise _LostLease()


        result = (
            self.pipeline.process(
                str(
                    source_path
                ),
                timer=timer,
            )
        )


        # ------------------------------------------------------
        # PERSISTING
        # ------------------------------------------------------

        if not self._advance(
            job_id,
            STAGE_PERSISTING,
        ):
            raise _LostLease()


        with timer.stage(
            "persistence"
        ):
            stored = (
                self.persistence
                .save_processed_document(
                    original_filename=(
                        claimed[
                            "original_filename"
                        ]
                    ),

                    content_type=(
                        claimed[
                            "content_type"
                        ]
                    ),

                    pipeline_result=(
                        result
                    ),

                    source_path=(
                        str(
                            source_path
                        )
                    ),

                    # PHASE 10.3. Computed once, at job
                    # creation, and carried forward. Hashing
                    # the same bytes again here would be a
                    # second full read of the file for an
                    # answer already known -- and, worse, a
                    # second chance to disagree with the
                    # value the uniqueness check used.
                    source_sha256=(
                        claimed.get(
                            "source_sha256"
                        )
                    ),
                )
            )


        document_id = stored[
            "document_id"
        ]


        # ------------------------------------------------------
        # COMPLETE
        # ------------------------------------------------------
        #
        # mark_completed is scoped to status = PROCESSING, so a
        # worker whose lease was stolen cannot overwrite the
        # outcome the new owner recorded. A False return means
        # exactly that, and the document just persisted is the
        # duplicate -- so it is removed rather than left as a
        # second copy of the same upload.
        # ------------------------------------------------------

        with SessionLocal.begin() as session:

            recorded = (
                DocumentJobRepository(
                    session
                )
                .mark_completed(
                    job_id=job_id,
                    document_id=(
                        document_id
                    ),
                )
            )


        if not recorded:

            self.logger.error(
                "Completion rejected: the job was no "
                "longer PROCESSING. Removing the "
                "duplicate document this attempt "
                "created.",
                extra={
                    "event":
                        "job.duplicate_discarded",

                    "job_id":
                        job_id,

                    "document_id":
                        document_id,
                },
            )

            self._discard_document(
                document_id
            )

            raise _LostLease()


        self.completed += 1

        _count_outcome("completed")

        # The upload has been copied into managed storage by
        # the persistence service, so the pending copy is now
        # redundant.
        self._release_source(
            job_id
        )

        self.logger.info(
            "Job completed.",
            extra={
                "event":
                    "job.completed",

                "job_id":
                    job_id,

                "document_id":
                    document_id,

                **timer.as_log_fields(),
            },
        )


    # ======================================================
    # FAILURE
    # ======================================================

    def _handle_failure(
        self,
        claimed: dict,
        error: Exception,
        timer: StageTimer,
    ) -> None:

        job_id = claimed[
            "job_id"
        ]

        verdict = (
            classify(
                error
            )
        )

        attempt = claimed[
            "attempt_count"
        ]

        allowed = claimed[
            "max_attempts"
        ]

        # A transient failure is only worth another go while
        # attempts remain. Past that it is terminal, and it is
        # reported as attempts exhausted rather than as the
        # last symptom -- "rate limited" on a permanently
        # failed job reads like it is still waiting.
        can_retry = (
            verdict.transient
            and attempt < allowed
        )


        if can_retry:

            delay = (
                retry_delay_seconds(
                    attempt_count=(
                        attempt
                    ),

                    retry_after_seconds=(
                        verdict
                        .retry_after_seconds
                    ),
                )
            )

            retry_at = (
                datetime.now(
                    timezone.utc
                )
                + timedelta(
                    seconds=delay,
                )
            )

            with SessionLocal.begin() as session:

                DocumentJobRepository(
                    session
                ).mark_retry(
                    job_id=job_id,

                    error_code=(
                        verdict.code
                    ),

                    error_message=(
                        verdict.message
                    ),

                    retry_at=(
                        retry_at
                    ),
                )


            self.retried += 1

            _count_outcome("retried")

            # The source is deliberately kept: the next
            # attempt needs those bytes.
            self.logger.warning(
                "Job parked for retry.",
                extra={
                    "event":
                        "job.retry_scheduled",

                    "job_id":
                        job_id,

                    "error_code":
                        verdict.code,

                    "error_type":
                        verdict.error_type,

                    "attempt":
                        attempt,

                    "retry_in_seconds":
                        round(
                            delay,
                            1,
                        ),
                },
            )

            return


        code = (
            JOB_ERROR_ATTEMPTS_EXHAUSTED
            if verdict.transient
            else verdict.code
        )

        message = (
            safe_message(
                code
            )
        )

        with SessionLocal.begin() as session:

            DocumentJobRepository(
                session
            ).mark_failed(
                job_id=job_id,
                error_code=code,
                error_message=message,
            )


        self.failed += 1

        _count_outcome("failed")

        self._release_source(
            job_id
        )

        # verdict.detail carries the exception text. It goes to
        # the log, where an operator is looking, and never to
        # the job row, which reaches a browser.
        self.logger.error(
            "Job failed.",
            extra={
                "event":
                    "job.failed",

                "job_id":
                    job_id,

                "error_code":
                    code,

                "error_type":
                    verdict.error_type,

                "attempt":
                    attempt,

                **timer.as_log_fields(),
            },
        )


    def _release_source(
        self,
        job_id: str,
    ) -> None:

        """
        Delete the pending upload for a job that has finished.

        Re-reads the row rather than trusting the snapshot, so
        the terminal-status check in release_source() is made
        against what the database actually says.
        """

        try:

            with SessionLocal.begin() as session:

                job = (
                    DocumentJobRepository(
                        session
                    )
                    .get_job(
                        job_id
                    )
                )

                if job is not None:
                    self.jobs.release_source(
                        job
                    )


        except Exception as error:      # noqa: BLE001

            # Never let cleanup failure change the job's
            # outcome. An undeleted pending file is reported by
            # orphaned_sources() and removed deliberately; a
            # job flipped to FAILED because a delete failed
            # would lose a document that actually processed.
            self.logger.warning(
                "Could not release the pending upload.",
                extra={
                    "event":
                        "job.source_release_failed",

                    "job_id":
                        job_id,

                    "error_type":
                        type(
                            error
                        ).__name__,
                },
            )


    def _discard_document(
        self,
        document_id: str,
    ) -> None:

        """
        Remove a document this worker persisted after losing
        the job.

        Without this, a stale replay leaves a second document
        for one upload: two rows, two stored files, two audit
        trails, and nothing pointing at the extra one.
        """

        try:

            from backend.app.services.document_deletion_service import (
                DocumentDeletionService,
            )

            DocumentDeletionService().delete_document(
                document_id
            )


        except Exception as error:      # noqa: BLE001

            self.logger.error(
                "Could not remove the duplicate "
                "document. It requires manual "
                "reconciliation.",
                extra={
                    "event":
                        "job.duplicate_orphaned",

                    "document_id":
                        document_id,

                    "error_type":
                        type(
                            error
                        ).__name__,
                },
            )


    # ======================================================
    # RECOVERY
    # ======================================================

    def reclaim_expired(
        self,
    ) -> int:

        """
        Return jobs whose worker has gone to the queue.

        This is what stops a killed worker from stranding a
        document in PROCESSING forever. A job with attempts
        remaining goes back to QUEUED; one that has exhausted
        them is failed as ABANDONED, because a document that
        repeatedly kills its worker must eventually stop being
        handed to the next one.
        """

        recovered = 0


        with SessionLocal.begin() as session:

            repository = (
                DocumentJobRepository(
                    session
                )
            )

            for job in repository.find_expired_leases():

                if job.attempt_count < job.max_attempts:

                    repository.requeue(
                        job_id=job.id,

                        error_code=(
                            JOB_ERROR_ABANDONED
                        ),

                        error_message=(
                            safe_message(
                                JOB_ERROR_ABANDONED
                            )
                        ),
                    )

                    outcome = "requeued"


                else:

                    repository.mark_failed(
                        job_id=job.id,

                        error_code=(
                            JOB_ERROR_ABANDONED
                        ),

                        error_message=(
                            safe_message(
                                JOB_ERROR_ABANDONED
                            )
                        ),
                    )

                    outcome = "failed"


                recovered += 1

                self.logger.warning(
                    "Recovered a job with an expired "
                    "lease.",
                    extra={
                        "event":
                            f"job.{outcome}_after_lease_"
                            "expiry",

                        "job_id":
                            job.id,

                        "attempt":
                            job.attempt_count,
                    },
                )


        self.reclaimed += recovered

        return recovered


class _LostLease(
    RuntimeError
):
    """
    Raised internally when this worker no longer owns the job
    it was processing. Handled, never reported as a failure:
    the job is fine, it just belongs to someone else now.
    """


# ==========================================================
# THE LOOP
# ==========================================================

class WorkerRunner:

    """
    Runs one or more workers until asked to stop.

    Concurrency is threads rather than processes because the
    expensive thing -- the OCR model -- is shared, and because
    both OCR and the provider call release the GIL while they
    work. It defaults to one regardless; see the note at the
    top of this module.
    """

    def __init__(
        self,
        *,
        concurrency: int | None = None,
        poll_seconds: float | None = None,
        idle_poll_seconds: float | None = None,
        reclaim_every_seconds: float = 30.0,
        worker_factory=None,
        logger: logging.Logger | None = None,
    ) -> None:

        self.concurrency = (
            concurrency
            if concurrency is not None
            else _configured_int(
                "VIGILOX_WORKER_CONCURRENCY",
                DEFAULT_MAX_CONCURRENCY,
                1,
                8,
            )
        )

        self.poll_seconds = (
            poll_seconds
            if poll_seconds is not None
            else _configured_float(
                "VIGILOX_WORKER_POLL_SECONDS",
                DEFAULT_POLL_SECONDS,
                0.1,
                60.0,
            )
        )

        self.idle_poll_seconds = (
            idle_poll_seconds
            if idle_poll_seconds is not None
            else _configured_float(
                "VIGILOX_WORKER_IDLE_POLL_SECONDS",
                DEFAULT_IDLE_POLL_SECONDS,
                0.1,
                300.0,
            )
        )

        self.reclaim_every_seconds = (
            reclaim_every_seconds
        )

        self.logger = (
            logger
            if logger is not None
            else get_operational_logger(
                "worker"
            )
        )

        self._factory = (
            worker_factory
            or (
                lambda: DocumentWorker()
            )
        )

        # PHASE 11.8. Built by warm() before the run loop,
        # and reused by every thread afterwards. See warm().
        self._warm_worker = None

        # ------------------------------------------------------
        # PHASE 11.14. THE HEARTBEAT.
        # ------------------------------------------------------
        # Written from inside the loop below, which is the
        # whole point: a heartbeat has to be something the
        # worker can only produce by actually turning its
        # loop. A container that is running but wedged writes
        # nothing.
        #
        # ONE writer for the process, not one per thread. The
        # row is keyed on worker_id and the question being
        # answered is "is this worker alive", not "is thread 2
        # alive". N threads updating one row would just
        # contend for it.
        # ------------------------------------------------------
        # Built in run(), once the primary worker exists,
        # because it has to carry THAT worker's id -- the same
        # one that appears in job rows. Constructing it here
        # would mean inventing a second identity.
        self.heartbeat = None

        # Set to ask every thread to finish its current job
        # and stop. Graceful shutdown is the point: a killed
        # worker mid-document costs an OCR pass and a lease
        # timeout, and both are avoidable.
        self.stop_event = (
            threading.Event()
        )

        self._threads: list[threading.Thread] = []

        self.workers: list[DocumentWorker] = []


    def request_stop(
        self,
    ) -> None:

        self.stop_event.set()


    def _loop(
        self,
        worker: DocumentWorker,
        is_primary: bool,
    ) -> None:

        next_reclaim = 0.0


        while not self.stop_event.is_set():

            try:

                # One worker does recovery, so N workers do not
                # all sweep the same rows. SKIP LOCKED would
                # make that safe anyway, but it would also be
                # N times the queries for no benefit.
                if is_primary:

                    now = (
                        datetime.now(
                            timezone.utc
                        ).timestamp()
                    )

                    if now >= next_reclaim:

                        worker.reclaim_expired()

                        next_reclaim = (
                            now
                            + self.reclaim_every_seconds
                        )


                # PHASE 11.14. Before the claim, so an idle
                # worker still checks in -- an idle worker is
                # healthy and must not read as dead.
                #
                # Only the primary thread writes. The row is
                # per PROCESS, so N threads writing it would
                # contend for one row to say the same thing.
                if is_primary and self.heartbeat:

                    self.heartbeat.beat()


                did_work = (
                    worker.process_one()
                )


                # After the claim, so the counters and the
                # current job are recorded. A worker that has
                # been on the same job id for eleven minutes
                # is visible from this.
                if is_primary and self.heartbeat:

                    self.heartbeat.completed = sum(
                        candidate.completed
                        for candidate in self.workers
                    )

                    self.heartbeat.failed = sum(
                        candidate.failed
                        for candidate in self.workers
                    )

                    self.heartbeat.beat(
                        current_job_id=(
                            getattr(
                                worker,
                                "current_job_id",
                                None,
                            )
                        ),
                    )


            except Exception as error:      # noqa: BLE001

                # The loop must outlive any single failure. A
                # worker that exits on an unexpected exception
                # stops processing everything, silently, and
                # the queue just grows.
                did_work = False

                self.logger.error(
                    "Worker loop error; continuing.",
                    extra={
                        "event":
                            "worker.loop_error",

                        "error_type":
                            type(
                                error
                            ).__name__,
                    },
                )


            # wait() rather than sleep() so a stop request is
            # acted on immediately instead of after the
            # interval.
            self.stop_event.wait(
                self.poll_seconds
                if did_work
                else self.idle_poll_seconds
            )


    # ======================================================
    # WARM THE PIPELINE
    # PHASE 11.8
    # ======================================================

    def warm(
        self,
    ):

        """
        Build the OCR pipeline before any job is claimed.

        Raises whatever the pipeline construction raises. The
        caller decides what to do with that -- backend/worker.py
        treats it as fatal, because a worker that cannot load
        its model should fail to start rather than claim a job
        and fail it.

        Returns the constructed worker, which run() then reuses
        for the first thread so the load is not paid twice.
        """

        worker = self._factory()

        # Touching the property constructs it.
        worker.pipeline

        self._warm_worker = worker

        return worker


    def run(
        self,
    ) -> None:

        self.logger.info(
            "Worker starting.",
            extra={
                "event":
                    "worker.starting",

                "concurrency":
                    self.concurrency,
            },
        )

        for index in range(
            self.concurrency
        ):

            # PHASE 11.8. The first thread reuses the worker
            # warm() already built, so the OCR model load is
            # paid once rather than again here.
            #
            # Only the first: each thread needs its own worker
            # because a worker holds the lease and the job it
            # is processing, and PaddleOCR is not something to
            # share across threads.
            #
            # At the default concurrency of 1 -- which is the
            # measured right value, since OCR is CPU-bound and
            # already multi-threaded -- this means the model is
            # loaded exactly once per container.
            if (
                index == 0
                and self._warm_worker is not None
            ):
                worker = self._warm_worker

            else:
                worker = (
                    self._factory()
                )

            self.workers.append(
                worker
            )

            # PHASE 11.14. The heartbeat carries the PRIMARY
            # worker's id, which is the same id that appears
            # in the job rows it claims. That is what makes
            # "worker X has been on job Y for eleven minutes"
            # answerable from two tables.
            if index == 0:

                self.heartbeat = (
                    WorkerHeartbeatWriter(
                        worker_id=(
                            worker.worker_id
                        ),
                        concurrency=(
                            self.concurrency
                        ),
                    )
                )

                # A restart leaves the previous row behind,
                # because the id carries a random suffix.
                # Cleared here rather than on a timer: once
                # per process start is enough to bound the
                # table.
                self.heartbeat.prune_stale()

            thread = (
                threading.Thread(
                    target=self._loop,
                    args=(
                        worker,
                        index == 0,
                    ),
                    name=(
                        f"vigilox-worker-{index}"
                    ),
                    daemon=False,
                )
            )

            self._threads.append(
                thread
            )

            thread.start()


        # ------------------------------------------------------
        # JOIN WITH A TIMEOUT, IN A LOOP
        # PHASE 11.13
        # ------------------------------------------------------
        #
        # Not `thread.join()`. The timeout is what makes
        # shutdown work.
        #
        # Python delivers a signal to the MAIN thread, and the
        # handler only runs when that thread executes
        # bytecode. The handler here is what sets stop_event,
        # and stop_event is what makes these threads finish --
        # so the main thread has to be reachable for any of it
        # to happen.
        #
        # An untimed join blocks on a lock acquire. On Linux
        # that acquire is interruptible, the handler runs, the
        # event is set, the threads exit and the join returns.
        # On Windows it is NOT interruptible: the handler
        # cannot run until the join returns, and the join
        # cannot return until the handler runs. The worker sits
        # there until it is killed.
        #
        # Measured before this change: SIGBREAK produced no
        # shutdown log at all and the process was terminated
        # with STATUS_CONTROL_C_EXIT, abandoning whatever
        # document it held.
        #
        # A bounded join returns to bytecode twice a second, so
        # a pending handler runs on any platform. The Linux
        # containers were already fine; this makes a developer
        # stopping a local worker get the same behaviour
        # production gets, rather than an abrupt kill.
        #
        # The cost is one wakeup per thread per half second
        # while draining, which is nothing next to a pipeline
        # measured in tens of seconds.
        while any(
            thread.is_alive()
            for thread in self._threads
        ):

            for thread in self._threads:

                thread.join(
                    timeout=0.5,
                )


        totals = {
            "processed":
                sum(
                    w.processed
                    for w in self.workers
                ),

            "completed":
                sum(
                    w.completed
                    for w in self.workers
                ),

            "failed":
                sum(
                    w.failed
                    for w in self.workers
                ),

            "retried":
                sum(
                    w.retried
                    for w in self.workers
                ),

            "reclaimed":
                sum(
                    w.reclaimed
                    for w in self.workers
                ),
        }

        self.logger.info(
            "Worker stopped.",
            extra={
                "event":
                    "worker.stopped",

                **totals,
            },
        )
