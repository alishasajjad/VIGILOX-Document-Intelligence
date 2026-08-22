import os
import uuid

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path

from database.database import (
    SessionLocal,
)

from database.job_repositories import (
    DocumentBatchRepository,
    DocumentJobRepository,
)

from backend.app.domain.job_states import (
    COMPLETED,
    FAILED,
    JOB_STATUSES,
    PROCESSING,
    QUEUED,
    RETRY_WAIT,
    TERMINAL_STATUSES,
    derive_batch_status,
)

from backend.app.services.job_source_store import (
    JobSourceStore,
)


# ==========================================================
# JOB SERVICE
# PHASE 9.3
# ==========================================================
#
# The application layer between HTTP and the queue. It owns
# transactions, owns the pending-upload lifecycle at creation
# time, and owns what a job looks like to a browser.
#
# The worker uses the same class for the parts that overlap --
# serialization, cleanup, batch derivation -- so the API and
# the worker cannot end up with two different ideas of what a
# job is.
#
#
# WHAT THE BROWSER IS ALLOWED TO SEE
# ----------------------------------------------------------
#
# serialize() is the only path from a job row to a response,
# and it is a whitelist rather than a dump. What it leaves out
# is the point:
#
#     source_name        a filesystem name
#     worker_id          internal topology
#     lease_expires_at   internal scheduling
#
# None of those help a person waiting for a document, and all
# of them tell an attacker something about the inside of the
# system. attempt_count and next_attempt_at do help -- they
# are the difference between "stuck" and "waiting" -- so they
# are included.
#
# The existing rule that error responses carry a code and a
# safe message and never an exception string applies here
# unchanged. The worker writes only vocabulary codes to the
# row, so there is nothing here to sanitise.
# ==========================================================


# ==========================================================
# BOUNDS
# ==========================================================
#
# The batch limit is set from the measured baseline, not from
# a round number.
#
# OCR is 100% of local pipeline time at an 18.4 second median
# and a 32.8 second maximum. A single worker at concurrency 1
# therefore clears roughly three documents a minute at best.
# Twenty files is about eleven minutes of queue -- long enough
# to be useful for a real intake session, short enough that
# the person who submitted it gets an answer in one sitting
# and that one batch cannot monopolise the queue for an hour.
#
# Raising this is a capacity decision, not a UI decision, and
# it should be made after Phase 9.5 re-measures.
# ==========================================================

DEFAULT_MAX_BATCH_FILES = 20

DEFAULT_MAX_ATTEMPTS = 3


def _configured_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:

    raw = os.getenv(
        name,
        "",
    ).strip()


    if not raw:
        return default


    try:
        value = int(
            raw
        )

    except ValueError:
        return default


    # Clamped rather than trusted. An operator typing 100000
    # into a batch limit should get a working system with a
    # sane bound, not an out-of-memory error.
    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


from sqlalchemy.exc import IntegrityError

from database.repositories import (
    DocumentRepository,
)

from backend.app.domain.duplicates import (
    DUPLICATE_DOCUMENT,
    DUPLICATE_DOCUMENT_MESSAGE,
    DUPLICATE_IN_PROGRESS,
    DUPLICATE_IN_PROGRESS_MESSAGE,
    fingerprint_path,
)


# ==========================================================
# THE CONSTRAINT THAT DOES THE WORK
# ==========================================================
#
# Named here so the translation from a database error to a
# product outcome keys on OUR constraint and nothing else. A
# different integrity error must not be reported as a
# duplicate.
# ==========================================================

ACTIVE_SOURCE_CONSTRAINT = (
    "uq_document_jobs_active_source"
)


class DuplicateSourceError(
    Exception
):

    """
    An identical source has already been seen.

    Carries the reference the caller needs in order to act,
    because a rejection with nothing to act on is the silent
    discard this policy exists to prevent.

    NEVER carries the fingerprint. The hash is an offline
    confirmation oracle for the document contents and has no
    business leaving the service.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        existing_document_id: str | None = None,
        existing_job_id: str | None = None,
        same_source_count: int = 0,
    ) -> None:

        super().__init__(
            message
        )

        self.code = code

        self.message = message

        self.existing_document_id = (
            existing_document_id
        )

        self.existing_job_id = (
            existing_job_id
        )

        self.same_source_count = (
            same_source_count
        )


    def payload(
        self,
    ) -> dict:

        return {
            "code":
                self.code,

            "message":
                self.message,

            "existing_document_id":
                self.existing_document_id,

            "existing_job_id":
                self.existing_job_id,

            "same_source_count":
                self.same_source_count,
        }


class JobNotFoundError(
    LookupError
):
    """
    Raised when a job or batch id does not exist. The caller
    maps it to a 404; this class carries no id, so it is safe
    to log.
    """


class BatchTooLargeError(
    ValueError
):
    """
    Raised when a batch exceeds the configured file count.
    """


class JobService:

    def __init__(
        self,
        source_store: JobSourceStore | None = None,
    ) -> None:

        self.source_store = (
            source_store
            if source_store is not None
            else JobSourceStore()
        )


    # ======================================================
    # CONFIGURATION
    # ======================================================

    @property
    def max_batch_files(
        self,
    ) -> int:

        return _configured_int(
            "VIGILOX_MAX_BATCH_FILES",
            DEFAULT_MAX_BATCH_FILES,
            1,
            200,
        )


    @property
    def max_attempts(
        self,
    ) -> int:

        return _configured_int(
            "VIGILOX_JOB_MAX_ATTEMPTS",
            DEFAULT_MAX_ATTEMPTS,
            1,
            10,
        )


    # ======================================================
    # CREATE
    # ======================================================

    # ======================================================
    # DUPLICATE SOURCE DETECTION
    # PHASE 10.3
    # ======================================================

    @staticmethod
    def _is_active_source_conflict(
        error: IntegrityError,
    ) -> bool:

        """
        Whether this integrity error is our partial unique
        index rejecting a second active job for one source.

        Keyed on the constraint name, never on the shape of
        the message, so an unrelated integrity error is not
        reported to a user as a duplicate.
        """

        original = error.orig

        diagnostic = getattr(
            original,
            "diag",
            None,
        )

        constraint = (
            getattr(
                diagnostic,
                "constraint_name",
                None,
            )
            if diagnostic is not None
            else None
        )

        if constraint == ACTIVE_SOURCE_CONSTRAINT:
            return True


        # Some driver and error combinations do not populate
        # diag.constraint_name. Fall back to the exact name
        # only -- never to a general "unique" match.
        return (
            ACTIVE_SOURCE_CONSTRAINT
            in str(
                original
            )
        )


    @staticmethod
    def _completed_duplicate(
        session,
        fingerprint: str,
    ) -> DuplicateSourceError | None:

        """
        Build the DUPLICATE_DOCUMENT outcome if these bytes
        already produced a document.

        Returns the error rather than raising it, so the two
        call sites -- the cheap check before the bytes are
        stored, and the authoritative re-check inside the
        insert transaction -- share one definition of what a
        completed duplicate is and what it reports.

        The reference is the MOST RECENT document for the
        source. If the source was deliberately reprocessed,
        the latest analysis is the current state of it, and
        pointing at a superseded original would send a
        reviewer to the wrong record.
        """

        documents = (
            DocumentRepository(
                session
            )
            .documents_for_source(
                fingerprint
            )
        )

        if not documents:
            return None


        return DuplicateSourceError(
            code=DUPLICATE_DOCUMENT,
            message=(
                DUPLICATE_DOCUMENT_MESSAGE
            ),
            existing_document_id=(
                documents[-1].id
            ),
            same_source_count=len(
                documents
            ),
        )


    def create_job(
        self,
        *,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        upload_path: str | Path,
        batch_id: str | None = None,
        reprocess: bool = False,
    ) -> dict:

        """
        Accept an upload and queue it.

        upload_path is the bounded temporary file the request
        handler streamed the body into. It is consumed.

        ORDER MATTERS, and the order is: bytes first, row
        second.

        A row written before the bytes are safely stored can be
        claimed by a worker in the window between the two, and
        that worker would fail with SOURCE_MISSING on a job
        that was in fact perfectly fine. Storing first means
        the worst case is an unreferenced pending file, which
        is inert, reportable, and cleaned up deliberately --
        rather than a job that fails for a reason that has
        already stopped being true.


        PHASE 10.3 - DUPLICATE SOURCE
        ------------------------------------------------------

        Raises DuplicateSourceError when these exact bytes
        have been seen before and reprocess is not set.

        reprocess=False is the default on purpose. Re-analysing
        a source already on file is a deliberate act, and a
        browser retrying a failed request is not that act. If
        the default were permissive, a flaky connection would
        silently produce a second document and a second 17
        seconds of OCR every time it retried.

        reprocess=True suppresses the completed-document
        rejection ONLY. It does not suppress the in-progress
        rejection, because there is no version of "analyse
        these bytes again" that is served by running two
        identical jobs at the same time -- the answer is to
        wait for the one already running.
        """

        # ==================================================
        # FINGERPRINT FIRST
        # ==================================================
        #
        # Before the pending copy, before the row, before a
        # worker exists to claim it. A duplicate answered here
        # costs one hash of a file already on local disk; the
        # same duplicate answered after the worker picks it up
        # costs a PaddleOCR pass and a Groq completion.
        #
        # A hash failure is not allowed to reject the upload.
        # The fingerprint is a feature of duplicate detection,
        # not a precondition for processing a document, so an
        # unreadable-for-hashing file falls through to null and
        # simply takes no part in duplicate detection. It will
        # fail later on its own merits if the bytes are truly
        # unusable.
        # ==================================================

        try:
            fingerprint = (
                fingerprint_path(
                    upload_path
                )
            )

        except OSError:
            fingerprint = None


        # ==================================================
        # THE CHEAP CHECK
        # ==================================================
        #
        # Not authoritative -- see the re-check inside the
        # transaction below, which is. This one exists purely
        # so the common case never writes a pending file it is
        # about to delete.
        # ==================================================

        if (
            fingerprint
            and not reprocess
        ):

            with SessionLocal() as session:

                duplicate = (
                    self._completed_duplicate(
                        session,
                        fingerprint,
                    )
                )

            if duplicate is not None:
                raise duplicate


        suffix = (
            Path(
                original_filename
            ).suffix.lower()
        )

        # The stored name is generated, never derived from the
        # uploaded filename. An uploaded name is untrusted and
        # this way it never reaches a path at all.
        source_name = (
            uuid.uuid4().hex
            + (
                suffix
                if suffix
                and len(suffix) <= 11
                and suffix[1:].isalnum()
                else ""
            )
        )

        self.source_store.save_pending(
            source_name=(
                source_name
            ),

            source_path=(
                upload_path
            ),
        )


        try:

            with SessionLocal.begin() as session:

                job = (
                    DocumentJobRepository(
                        session
                    )
                    .create_job(
                        original_filename=(
                            original_filename
                        ),

                        content_type=(
                            content_type
                        ),

                        size_bytes=(
                            size_bytes
                        ),

                        source_name=(
                            source_name
                        ),

                        max_attempts=(
                            self.max_attempts
                        ),

                        batch_id=(
                            batch_id
                        ),

                        source_sha256=(
                            fingerprint
                        ),
                    )
                )

                # ==========================================
                # THE AUTHORITATIVE RE-CHECK
                # PHASE 10.3
                # ==========================================
                #
                # This closes the one real race, and it is
                # worth writing down exactly why it closes it.
                #
                # THE RACE
                # ------------------------------------------
                # An upload arrives while a worker is halfway
                # through processing the identical bytes. The
                # cheap check above finds no document, because
                # the worker has not persisted one yet. If
                # nothing else happened, this upload would
                # queue a second job for a source that is
                # about to have a document.
                #
                # WHY CHECKING AGAIN HERE IS ENOUGH
                # ------------------------------------------
                # The INSERT above has already either taken
                # the active-source slot in the partial unique
                # index, or failed. So reaching this line
                # means no other job for these bytes was
                # active a moment ago.
                #
                # And the worker commits in this order:
                #
                #   1. transaction A: the document row
                #   2. transaction B: job -> COMPLETED
                #
                # A job only stops being active in step 2,
                # which happens strictly after step 1. So if
                # the earlier job is no longer active -- which
                # the successful insert just established --
                # its document is already committed, and this
                # query, running under READ COMMITTED with a
                # fresh statement snapshot, will see it.
                #
                # There is therefore no ordering in which the
                # uniqueness has been released and the
                # document is not yet visible.
                #
                # THE DEPENDENCY THIS CREATES
                # ------------------------------------------
                # The argument rests entirely on the worker
                # persisting the document BEFORE marking the
                # job completed. Reversing those two would
                # open the window again. The Phase 10.3 test
                # suite asserts the order rather than trusting
                # this comment to be read.
                #
                # Raising inside the transaction rolls the
                # inserted job back, so the rejection leaves
                # nothing behind.
                # ==========================================

                if (
                    fingerprint
                    and not reprocess
                ):

                    duplicate = (
                        self._completed_duplicate(
                            session,
                            fingerprint,
                        )
                    )

                    if duplicate is not None:
                        raise duplicate


                # Read while the session is open. Accessing a
                # detached instance's attributes after the
                # block would raise, and returning the
                # serialized form is what the caller wants
                # anyway.
                payload = (
                    self.serialize(
                        job
                    )
                )

            return payload


        except IntegrityError as error:

            # The row did not happen, so the bytes are
            # unreferenced.
            self.source_store.delete_pending(
                source_name
            )


            if not self._is_active_source_conflict(
                error
            ):
                raise


            # ==========================================
            # AN IDENTICAL SOURCE IS ALREADY RUNNING
            # ==========================================
            #
            # The partial unique index rejected this insert,
            # which means another job for these exact bytes
            # was active. PostgreSQL chose the winner; there
            # was no window in which both could win.
            #
            # The lookup is only to name the job that won, so
            # the caller can follow it instead of starting
            # again. It is allowed to come back empty -- the
            # winner may have finished in between -- and the
            # collision is still reported.
            # ==========================================

            with SessionLocal() as session:

                active = (
                    DocumentJobRepository(
                        session
                    )
                    .active_job_for_source(
                        fingerprint
                    )
                )

                active_job_id = (
                    active.id
                    if active is not None
                    else None
                )


            raise DuplicateSourceError(
                code=(
                    DUPLICATE_IN_PROGRESS
                ),
                message=(
                    DUPLICATE_IN_PROGRESS_MESSAGE
                ),
                existing_job_id=(
                    active_job_id
                ),
            ) from error


        except Exception:

            # The row did not happen, so the bytes are
            # unreferenced. Remove them rather than leaving
            # residue that no job will ever claim.
            #
            # This also covers the duplicate raised inside the
            # transaction above: the rejection must not leave a
            # pending file behind either.
            self.source_store.delete_pending(
                source_name
            )

            raise


    def create_batch(
        self,
        *,
        uploads: list[dict],
        reprocess: bool = False,
    ) -> dict:

        """
        Queue several documents as one batch.

        uploads is a list of dicts with original_filename,
        content_type, size_bytes and upload_path -- already
        validated by the request layer, which owns type and
        size rules.

        The batch row is created first so that every job can
        reference it. If a later job fails to queue, the ones
        already queued stay queued: a batch is a grouping, not
        a transaction, and throwing away accepted work because
        the eighth file had a problem would be worse than
        reporting the eighth file as rejected.
        """

        if not uploads:

            raise ValueError(
                "A batch needs at least one file."
            )


        limit = self.max_batch_files


        if len(uploads) > limit:

            raise BatchTooLargeError(
                (
                    "A batch may contain at most "
                    f"{limit} files."
                )
            )


        with SessionLocal.begin() as session:

            batch = (
                DocumentBatchRepository(
                    session
                )
                .create_batch(
                    submitted_count=(
                        len(uploads)
                    ),
                )
            )

            batch_id = batch.id


        jobs: list[dict] = []

        rejected: list[dict] = []


        for upload in uploads:

            try:
                jobs.append(
                    self.create_job(
                        original_filename=(
                            upload[
                                "original_filename"
                            ]
                        ),

                        content_type=(
                            upload[
                                "content_type"
                            ]
                        ),

                        size_bytes=(
                            upload[
                                "size_bytes"
                            ]
                        ),

                        upload_path=(
                            upload[
                                "upload_path"
                            ]
                        ),

                        batch_id=(
                            batch_id
                        ),

                        reprocess=(
                            reprocess
                        ),
                    )
                )

            # ==========================================
            # A DUPLICATE FILE IS REPORTED, NOT FATAL
            # PHASE 10.3
            # ==========================================
            #
            # Caught before the generic handler so the file
            # gets its real code and its reference instead of
            # the opaque QUEUE_REJECTED.
            #
            # The batch continues. A batch is a grouping, not
            # a transaction, and the whole point of uploading
            # twenty files is that the twentieth being a
            # duplicate does not throw away the nineteen that
            # were fine.
            #
            # This also covers TWO IDENTICAL FILES INSIDE ONE
            # BATCH -- a.jpg and a-copy.jpg. The first takes
            # the active-source slot, the second collides with
            # it and is reported as DUPLICATE_IN_PROGRESS
            # pointing at its own sibling. Which is accurate:
            # that job is running, and it is the one to watch.
            # ==========================================

            except DuplicateSourceError as duplicate:

                rejected.append(
                    {
                        "original_filename":
                            upload.get(
                                "original_filename"
                            ),

                        "error_code":
                            duplicate.code,

                        "error_message":
                            duplicate.message,

                        "existing_document_id":
                            (
                                duplicate
                                .existing_document_id
                            ),

                        "existing_job_id":
                            (
                                duplicate
                                .existing_job_id
                            ),
                    }
                )

            except Exception as error:      # noqa: BLE001

                # Reported per file, with no exception text.
                rejected.append(
                    {
                        "original_filename":
                            upload.get(
                                "original_filename"
                            ),

                        "error_code":
                            "QUEUE_REJECTED",

                        "error_message":
                            (
                                "This file could not be "
                                "queued for processing."
                            ),
                    }
                )


        return {
            "batch_id":
                batch_id,

            "submitted_count":
                len(uploads),

            "queued_count":
                len(jobs),

            "jobs":
                jobs,

            "rejected":
                rejected,
        }


    # ======================================================
    # READ
    # ======================================================

    def get_job(
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

                raise JobNotFoundError(
                    "No such job."
                )


            return (
                self.serialize(
                    job
                )
            )


    def get_batch(
        self,
        batch_id: str,
    ) -> dict:

        with SessionLocal.begin() as session:

            repository = (
                DocumentJobRepository(
                    session
                )
            )

            batch = (
                DocumentBatchRepository(
                    session
                )
                .get_batch(
                    batch_id
                )
            )


            if batch is None:

                raise JobNotFoundError(
                    "No such batch."
                )


            jobs = (
                repository
                .jobs_for_batch(
                    batch_id
                )
            )

            counts = (
                repository
                .count_by_status(
                    batch_id=(
                        batch_id
                    ),
                )
            )

            serialized = [
                self.serialize(
                    job
                )
                for job in jobs
            ]

            created_at = (
                batch.created_at
            )

            submitted = (
                batch.submitted_count
            )


        # Every status present, including the zeroes. A caller
        # rendering a summary should not have to guess whether
        # a missing key means none or means the field was
        # dropped.
        summary = {
            status: counts.get(
                status,
                0,
            )
            for status in JOB_STATUSES
        }

        return {
            "batch_id":
                batch_id,

            "status":
                derive_batch_status(
                    counts
                ),

            "submitted_count":
                submitted,

            "created_at":
                _isoformat(
                    created_at
                ),

            "counts":
                summary,

            "document_ids": [
                item["document_id"]
                for item in serialized
                if item["document_id"]
            ],

            "jobs":
                serialized,
        }


    def queue_depth(
        self,
    ) -> dict[str, int]:

        """
        How many jobs are in each status, across everything.

        Used by the readiness and metrics surfaces in Phase
        11.7. Grouped in the database, so it stays cheap
        enough to call on a schedule.
        """

        with SessionLocal.begin() as session:

            counts = (
                DocumentJobRepository(
                    session
                )
                .count_by_status()
            )


        return {
            status: counts.get(
                status,
                0,
            )
            for status in JOB_STATUSES
        }


    # ======================================================
    # SERIALIZATION
    # ======================================================

    def serialize(
        self,
        job,
    ) -> dict:

        """
        The only route from a job row to anything a browser
        sees.

        A whitelist. source_name, worker_id and
        lease_expires_at are deliberately absent: a filesystem
        name and the internal scheduling state are nobody's
        business outside the worker, and none of them help
        somebody waiting for a document.
        """

        status = job.status

        return {
            "job_id":
                job.id,

            "batch_id":
                job.batch_id,

            "status":
                status,

            # Advisory only. Present while PROCESSING and
            # cleared otherwise, so a stale stage cannot be
            # mistaken for live progress on a finished job.
            "current_stage":
                (
                    job.current_stage
                    if status == PROCESSING
                    else None
                ),

            "original_filename":
                job.original_filename,

            "content_type":
                job.content_type,

            "size_bytes":
                job.size_bytes,

            "document_id":
                job.document_id,

            "attempt_count":
                job.attempt_count,

            "max_attempts":
                job.max_attempts,

            # Only meaningful while waiting to retry. On a
            # terminal job it is noise that reads like a
            # promise of another attempt.
            "next_attempt_at":
                (
                    _isoformat(
                        job.next_attempt_at
                    )
                    if status == RETRY_WAIT
                    else None
                ),

            "error_code":
                job.safe_error_code,

            "error_message":
                job.safe_error_message,

            "created_at":
                _isoformat(
                    job.created_at
                ),

            "started_at":
                _isoformat(
                    job.started_at
                ),

            "completed_at":
                _isoformat(
                    job.completed_at
                ),

            "failed_at":
                _isoformat(
                    job.failed_at
                ),

            # Saves every caller from re-deriving the one
            # question that decides whether to keep polling.
            "is_terminal":
                status in TERMINAL_STATUSES,

            "status_url":
                f"/api/v1/document-jobs/{job.id}",

            # Present only when there is something to open.
            "document_url":
                (
                    f"/review/{job.document_id}"
                    if status == COMPLETED
                    and job.document_id
                    else None
                ),
        }


    # ======================================================
    # SOURCE LIFECYCLE
    # ======================================================

    def release_source(
        self,
        job,
    ) -> bool:

        """
        Delete a job's pending upload.

        Called when a job reaches COMPLETED or FAILED, and
        never while it is QUEUED, PROCESSING or RETRY_WAIT --
        a job waiting to retry still needs its bytes, and
        deleting them would turn a recoverable rate limit into
        a permanent SOURCE_MISSING on the next attempt.

        These are identity documents, so a terminal job holding
        its upload forever is a privacy question as much as a
        disk one.
        """

        if job.status not in TERMINAL_STATUSES:
            return False


        return (
            self.source_store
            .delete_pending(
                job.source_name
            )
        )


    def orphaned_sources(
        self,
    ) -> list[str]:

        """
        Pending files that no job row refers to.

        Reported only. Nothing here deletes them: the same
        rule the managed store follows, and for the same
        reason -- automatic deletion of something merely
        unrecognised is how in-flight work gets destroyed.
        """

        from database.models import (
            DocumentJobModel,
        )

        from sqlalchemy import select


        with SessionLocal.begin() as session:

            known = {
                name
                for (name,) in session.execute(
                    select(
                        DocumentJobModel.source_name
                    )
                ).all()
            }


        return (
            self.source_store
            .orphaned_names(
                known
            )
        )


def _isoformat(
    value: datetime | None,
) -> str | None:

    if value is None:
        return None


    # Rows written by PostgreSQL come back timezone-aware.
    # A naive value would still be UTC by construction, so it
    # is labelled rather than guessed at.
    if value.tzinfo is None:

        value = value.replace(
            tzinfo=timezone.utc,
        )


    return (
        value
        .astimezone(
            timezone.utc
        )
        .isoformat(
            timespec="seconds"
        )
    )
