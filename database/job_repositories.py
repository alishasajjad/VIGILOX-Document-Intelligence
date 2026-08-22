from datetime import (
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy import (
    func,
    select,
    update,
)
from sqlalchemy.orm import Session

from database.models import (
    DocumentBatchModel,
    DocumentJobModel,
)


# ==========================================================
# DOCUMENT JOB REPOSITORY
# PHASE 9.2
# ==========================================================
#
# The durable queue's data access layer. Same shape as the
# existing repositories: a Session comes in, the caller owns
# the transaction, and nothing here imports upward into the
# application services.
#
#
# THE CLAIM PROTOCOL
# ----------------------------------------------------------
#
# Two workers must never process the same document. The
# obvious implementation --
#
#     read the oldest queued job
#     mark it PROCESSING
#
# -- is a race, and it is a race that produces two documents
# from one upload, two rows, two stored files and two audit
# trails. It would also pass a single-worker test perfectly.
#
# So the claim is a single statement:
#
#     SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1
#
# FOR UPDATE takes a row lock inside the transaction. SKIP
# LOCKED makes a second worker step over rows already locked
# by the first instead of blocking on them. The result is that
# concurrent workers claim different rows, and never the same
# one, without a queue service and without an advisory lock
# protocol of our own.
#
#
# THE LEASE
# ----------------------------------------------------------
#
# A worker that is killed mid-job leaves PROCESSING behind
# with nobody working on it. Without a lease that row is stuck
# forever, and the document silently never appears.
#
# So a claim sets lease_expires_at, and a job is only really
# being worked on while that time is in the future. Anything
# past it is recoverable by reclaim_expired(), which is
# ordinary queue maintenance rather than an incident.
#
# The worker extends its own lease as it advances through
# stages, so a slow document does not get taken away from a
# healthy worker.
# ==========================================================


from backend.app.domain.job_states import (
    ACTIVE_STATUSES,
    CLAIMABLE_STATUSES,
    RETRY_WAIT,
)


class DocumentJobRepository:

    def __init__(
        self,
        session: Session,
    ) -> None:

        self.session = session


    # ======================================================
    # CREATE
    # ======================================================

    def create_job(
        self,
        *,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        source_name: str,
        max_attempts: int,
        batch_id: str | None = None,
        source_sha256: str | None = None,
    ) -> DocumentJobModel:

        job = (
            DocumentJobModel(
                batch_id=(
                    batch_id
                ),

                status="QUEUED",

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

                # PHASE 10.3. The partial unique index over
                # active jobs is what actually stops two
                # concurrent identical uploads, so this value
                # reaching the row is the enforcement point,
                # not a decoration on it.
                source_sha256=(
                    source_sha256
                ),

                max_attempts=(
                    max_attempts
                ),

                attempt_count=0,
            )
        )

        self.session.add(
            job
        )

        # Flush rather than commit: the caller owns the
        # transaction, and it needs the generated id.
        self.session.flush()

        return job


    # ======================================================
    # ACTIVE JOB FOR A SOURCE
    # PHASE 10.3
    # ======================================================

    def active_job_for_source(
        self,
        source_sha256: str | None,
    ):

        """
        The active job holding these exact source bytes, if
        there is one.

        Used ONLY to report which job a rejected duplicate
        collided with. It is deliberately NOT used to decide
        whether to insert: that decision belongs to the
        partial unique index, because a lookup followed by an
        insert has a window between the two and the index has
        none.

        So this can return None even though an insert just
        failed -- if the winning transaction committed and
        then finished between the two statements. The caller
        reports the collision either way and simply has no
        job to point at.
        """

        if not source_sha256:
            return None


        return (
            self.session.execute(
                select(
                    DocumentJobModel
                )
                .where(
                    DocumentJobModel.source_sha256
                    == source_sha256
                )
                .where(
                    DocumentJobModel.status.in_(
                        ACTIVE_STATUSES
                    )
                )
                .order_by(
                    DocumentJobModel.created_at.asc()
                )
                .limit(1)
            )
            .scalars()
            .first()
        )


    # ======================================================
    # READ
    # ======================================================

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJobModel | None:

        return (
            self.session.get(
                DocumentJobModel,
                job_id,
            )
        )


    def jobs_for_batch(
        self,
        batch_id: str,
    ) -> list[DocumentJobModel]:

        statement = (
            select(
                DocumentJobModel
            )
            .where(
                DocumentJobModel.batch_id
                == batch_id
            )
            .order_by(
                DocumentJobModel.created_at,
                DocumentJobModel.id,
            )
        )

        return list(
            self.session
            .execute(
                statement
            )
            .scalars()
            .all()
        )


    def count_by_status(
        self,
        batch_id: str | None = None,
    ) -> dict[str, int]:

        """
        How many jobs are in each status, optionally for one
        batch.

        Grouped in the database rather than by loading rows
        and counting in Python, because the queue-depth metric
        in Phase 11.7 calls this on a schedule and a table
        scan per scrape would be a self-inflicted load
        problem.
        """

        statement = (
            select(
                DocumentJobModel.status,
                func.count(),
            )
            .group_by(
                DocumentJobModel.status
            )
        )


        if batch_id is not None:

            statement = (
                statement.where(
                    DocumentJobModel.batch_id
                    == batch_id
                )
            )


        return {
            status: int(
                total
            )
            for status, total in (
                self.session
                .execute(
                    statement
                )
                .all()
            )
        }


    # ======================================================
    # CLAIM
    # ======================================================

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
        only_job_ids=None,
    ) -> DocumentJobModel | None:

        """
        Take exclusive ownership of one claimable job, or
        return None when there is nothing to do.

        Must be called inside a transaction. The row lock that
        makes this safe lives for the length of that
        transaction, so committing is what publishes the
        claim.


        only_job_ids
        ------------------------------------------------------

        Restricts the claim to a specific job, or a specific
        set of them. Accepts one id or any iterable of ids.

        It changes nothing about the locking, the ordering or
        the claimable predicate -- an ineligible job is still
        not claimed, and a job another worker holds is still
        skipped. It only narrows which rows are considered.

        Two callers want it.

        An OPERATOR investigating one stuck job wants to run
        exactly that job rather than whatever happens to be at
        the head of the queue.

        And TESTS need it. Without it, a worker in a test
        claims the oldest claimable job in the whole database,
        which may be a real upload somebody made through the
        browser. That had two bad consequences: a test could
        process somebody else's document with an injected
        pipeline, and the guard added to prevent that made the
        whole suite refuse to run whenever a developer had
        legitimately used the application. A test that fails
        because the product was used is a test that gets
        deleted.

        An empty collection matches nothing, which is the
        honest reading of "restrict to none of them" and stops
        an empty test-owned set from silently becoming
        unrestricted.
        """

        moment = (
            now
            if now is not None
            else datetime.now(
                timezone.utc
            )
        )

        # QUEUED is claimable now. RETRY_WAIT is claimable
        # once its backoff has elapsed -- that comparison is
        # the entire backoff mechanism, and it lives in the
        # query so a worker cannot accidentally ignore it.
        #
        # PHASE 11.4. The status set comes from
        # CLAIMABLE_STATUSES rather than from two string
        # literals here.
        #
        # It used to be written out, which made the domain
        # constant look like a single definition of "claimable"
        # while the query that decides it ignored the constant
        # entirely. That is the same duplication that hid a
        # real critical-field error in Phase 10.5 and put an
        # evidence-flag parser in JavaScript before Phase 10.6.
        #
        # WHY IT IS NOT JUST status.in_(CLAIMABLE_STATUSES):
        # the two members need DIFFERENT predicates. A QUEUED
        # job is claimable immediately; a RETRY_WAIT job only
        # once next_attempt_at has passed. So membership comes
        # from the constant and the backoff gate is applied
        # only to RETRY_WAIT.
        #
        # Equivalent to the previous expression in every case,
        # including next_attempt_at IS NULL, where both forms
        # evaluate to NULL and the row is not claimed.
        #
        # A status added to CLAIMABLE_STATUSES is now picked up
        # here automatically, with no backoff gate -- which is
        # the right default, since only RETRY_WAIT has a
        # backoff to wait out.
        #
        # test_phase11_route_and_domain_contracts asserts which
        # statuses this query can actually claim, by putting a
        # job in every status and seeing which come back.
        claimable = (
            DocumentJobModel.status.in_(
                CLAIMABLE_STATUSES
            )
            & (
                (
                    DocumentJobModel.status
                    != RETRY_WAIT
                )
                | (
                    DocumentJobModel.next_attempt_at
                    <= moment
                )
            )
        )

        if only_job_ids is not None:

            identifiers = (
                [
                    only_job_ids
                ]
                if isinstance(
                    only_job_ids,
                    str,
                )
                else list(
                    only_job_ids
                )
            )

            claimable = (
                claimable
                & DocumentJobModel.id.in_(
                    identifiers
                )
            )


        statement = (
            select(
                DocumentJobModel
            )
            .where(
                claimable
            )
            .order_by(
                DocumentJobModel.created_at,
                DocumentJobModel.id,
            )
            .limit(1)
            .with_for_update(
                skip_locked=True,
            )
        )

        job = (
            self.session
            .execute(
                statement
            )
            .scalars()
            .first()
        )


        if job is None:
            return None


        job.status = "PROCESSING"

        job.worker_id = worker_id

        job.current_stage = "READING"

        job.attempt_count = (
            job.attempt_count + 1
        )

        job.started_at = (
            job.started_at
            or moment
        )

        job.next_attempt_at = None

        job.lease_expires_at = (
            moment
            + timedelta(
                seconds=lease_seconds,
            )
        )

        self.session.flush()

        return job


    def extend_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
        stage: str | None = None,
        now: datetime | None = None,
    ) -> bool:

        """
        Push a lease further out, and optionally record the
        stage now being worked on.

        Scoped to worker_id on purpose. A worker whose lease
        already expired and whose job was reclaimed by someone
        else must not be able to reach back in and extend it
        -- that would give two workers a live claim on one
        row, which is the exact thing the lease exists to
        prevent. The False return is how the caller learns it
        has lost the job.
        """

        moment = (
            now
            if now is not None
            else datetime.now(
                timezone.utc
            )
        )

        values = {
            "lease_expires_at": (
                moment
                + timedelta(
                    seconds=lease_seconds,
                )
            ),
        }


        if stage is not None:
            values["current_stage"] = stage


        statement = (
            update(
                DocumentJobModel
            )
            .where(
                DocumentJobModel.id
                == job_id,

                DocumentJobModel.worker_id
                == worker_id,

                DocumentJobModel.status
                == "PROCESSING",
            )
            .values(
                **values
            )
        )

        result = (
            self.session.execute(
                statement
            )
        )

        return bool(
            result.rowcount
        )


    # ======================================================
    # COMPLETE
    # ======================================================

    def mark_completed(
        self,
        *,
        job_id: str,
        document_id: str,
        now: datetime | None = None,
    ) -> bool:

        moment = (
            now
            if now is not None
            else datetime.now(
                timezone.utc
            )
        )

        statement = (
            update(
                DocumentJobModel
            )
            .where(
                DocumentJobModel.id
                == job_id,

                DocumentJobModel.status
                == "PROCESSING",
            )
            .values(
                status="COMPLETED",
                document_id=document_id,
                current_stage=None,
                completed_at=moment,
                lease_expires_at=None,
                worker_id=None,
                safe_error_code=None,
                safe_error_message=None,
            )
        )

        result = (
            self.session.execute(
                statement
            )
        )

        return bool(
            result.rowcount
        )


    def mark_failed(
        self,
        *,
        job_id: str,
        error_code: str,
        error_message: str,
        now: datetime | None = None,
    ) -> bool:

        moment = (
            now
            if now is not None
            else datetime.now(
                timezone.utc
            )
        )

        statement = (
            update(
                DocumentJobModel
            )
            .where(
                DocumentJobModel.id
                == job_id,
            )
            .values(
                status="FAILED",
                current_stage=None,
                failed_at=moment,
                lease_expires_at=None,
                worker_id=None,
                next_attempt_at=None,
                safe_error_code=error_code,
                safe_error_message=error_message,
            )
        )

        result = (
            self.session.execute(
                statement
            )
        )

        return bool(
            result.rowcount
        )


    def mark_retry(
        self,
        *,
        job_id: str,
        error_code: str,
        error_message: str,
        retry_at: datetime,
        now: datetime | None = None,
    ) -> bool:

        """
        Park a job until retry_at.

        The error code and message are kept while it waits, so
        a person looking at a queued-looking job can see why
        it is waiting rather than assuming it is stuck.
        """

        statement = (
            update(
                DocumentJobModel
            )
            .where(
                DocumentJobModel.id
                == job_id,
            )
            .values(
                status="RETRY_WAIT",
                current_stage=None,
                lease_expires_at=None,
                worker_id=None,
                next_attempt_at=retry_at,
                safe_error_code=error_code,
                safe_error_message=error_message,
            )
        )

        result = (
            self.session.execute(
                statement
            )
        )

        return bool(
            result.rowcount
        )


    # ======================================================
    # RECOVERY
    # ======================================================

    def find_expired_leases(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[DocumentJobModel]:

        """
        Jobs stuck in PROCESSING whose worker has gone.

        Locked with SKIP LOCKED for the same reason as the
        claim: two workers sweeping at once must not both
        recover the same row and both requeue it.
        """

        moment = (
            now
            if now is not None
            else datetime.now(
                timezone.utc
            )
        )

        statement = (
            select(
                DocumentJobModel
            )
            .where(
                DocumentJobModel.status
                == "PROCESSING",

                DocumentJobModel.lease_expires_at
                .is_not(None),

                DocumentJobModel.lease_expires_at
                < moment,
            )
            .order_by(
                DocumentJobModel.lease_expires_at
            )
            .limit(
                limit
            )
            .with_for_update(
                skip_locked=True,
            )
        )

        return list(
            self.session
            .execute(
                statement
            )
            .scalars()
            .all()
        )


    def requeue(
        self,
        *,
        job_id: str,
        error_code: str,
        error_message: str,
    ) -> bool:

        """
        Return an abandoned job to the queue.

        attempt_count is deliberately not reset. A document
        that repeatedly kills its worker must eventually stop
        being retried, or one bad file occupies a worker
        forever -- so an abandoned attempt is still an
        attempt.
        """

        statement = (
            update(
                DocumentJobModel
            )
            .where(
                DocumentJobModel.id
                == job_id,

                DocumentJobModel.status
                == "PROCESSING",
            )
            .values(
                status="QUEUED",
                current_stage=None,
                worker_id=None,
                lease_expires_at=None,
                next_attempt_at=None,
                safe_error_code=error_code,
                safe_error_message=error_message,
            )
        )

        result = (
            self.session.execute(
                statement
            )
        )

        return bool(
            result.rowcount
        )


# ==========================================================
# DOCUMENT BATCH REPOSITORY
# PHASE 9.4
# ==========================================================

class DocumentBatchRepository:

    def __init__(
        self,
        session: Session,
    ) -> None:

        self.session = session


    def create_batch(
        self,
        *,
        submitted_count: int,
    ) -> DocumentBatchModel:

        batch = (
            DocumentBatchModel(
                submitted_count=(
                    submitted_count
                ),
            )
        )

        self.session.add(
            batch
        )

        self.session.flush()

        return batch


    def get_batch(
        self,
        batch_id: str,
    ) -> DocumentBatchModel | None:

        return (
            self.session.get(
                DocumentBatchModel,
                batch_id,
            )
        )
