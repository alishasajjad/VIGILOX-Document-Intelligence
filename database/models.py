from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)

from sqlalchemy.dialects.postgresql import (
    JSONB,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from database.database import Base

# PHASE 10.3. The partial unique index below is declared over
# exactly the job states the application calls active, so the
# constraint reads the same tuple the code does.
from backend.app.domain.job_states import (
    ACTIVE_STATUSES,
)


# ==========================================================
# DOCUMENT
# ==========================================================

class DocumentModel(Base):

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    original_filename: Mapped[str] = (
        mapped_column(
            String(255),
            nullable=False,
        )
    )

    content_type: Mapped[str] = (
        mapped_column(
            String(100),
            nullable=False,
        )
    )

    document_type: Mapped[
        str | None
    ] = mapped_column(
        String(50),
        nullable=True,
    )

    processing_status: Mapped[str] = (
        mapped_column(
            String(50),
            nullable=False,
            default="PROCESSED",
        )
    )

    # ==================================================
    # SOURCE FINGERPRINT
    # PHASE 10.3
    # ==================================================
    #
    # SHA-256 of the ORIGINAL uploaded bytes, 64 hex
    # characters.
    #
    # NULLABLE, and it stays nullable for two reasons. Every
    # document stored before Phase 10.3 has no fingerprint,
    # and null says "unknown" where a placeholder would
    # claim a source nobody computed. And an upload whose
    # bytes could not be read for hashing must still be
    # able to produce a document rather than failing on a
    # secondary concern.
    #
    # NOT UNIQUE, deliberately. Reprocessing identical bytes
    # is an allowed, explicit business action, and a unique
    # constraint here would forbid it outright. Uniqueness
    # is enforced instead over ACTIVE JOBS, which is the
    # thing that actually needs to be exclusive -- see the
    # partial index on document_jobs below.
    # ==================================================

    source_sha256: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )
    )

    # Duplicate lookup happens on every upload, before any
    # OCR is spent, so it has to be an index seek rather
    # than a scan of the documents table.
    #
    # Plain btree, not unique: see the column comment.
    __table_args__ = (
        Index(
            "ix_documents_source_sha256",
            "source_sha256",
        ),
    )


# ==========================================================
# DOCUMENT ANALYSIS
# ==========================================================

class DocumentAnalysisModel(Base):

    __tablename__ = (
        "document_analyses"
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
        index=True,
    )

    extraction: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    ocr_lines: Mapped[list] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    evidence_flags: Mapped[list] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    field_confidence: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    date_validation: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    anomaly_validation: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    # PHASE 10.1. Nullable, so every row written before
    # quality assessment existed stays valid and reads as
    # "not assessed" rather than as "no problems found".
    # Those are different statements and the interface says
    # which one it is.
    quality: Mapped[
        dict | None
    ] = mapped_column(
        JSONB,
        nullable=True,
    )

    review_decision: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )


# ==========================================================
# HUMAN REVIEW
# PHASE 7C.1
# ==========================================================

class HumanReviewModel(Base):

    __tablename__ = (
        "human_reviews"
    )

    # ======================================================
    # ONE COMPLETED HUMAN REVIEW PER DOCUMENT
    # ======================================================
    #
    # Phase 7C.1 production rule:
    #
    # A document can have at most one completed
    # human-review record.
    #
    # This database constraint is the final protection
    # against concurrent reviewers submitting conflicting
    # decisions for the same document.
    #
    # Application-level checks improve the normal UX,
    # while this constraint protects against race
    # conditions.
    # ======================================================

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            name=(
                "uq_human_reviews_"
                "document_id"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    document_id: Mapped[str] = (
        mapped_column(
            ForeignKey(
                "documents.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            index=True,
        )
    )

    reviewer_id: Mapped[str] = (
        mapped_column(
            String(100),
            nullable=False,
        )
    )

    machine_decision: Mapped[
        str | None
    ] = mapped_column(
        String(50),
        nullable=True,
    )

    machine_priority: Mapped[
        str | None
    ] = mapped_column(
        String(30),
        nullable=True,
    )

    machine_reason_codes: Mapped[list] = (
        mapped_column(
            JSONB,
            nullable=False,
            default=list,
        )
    )

    human_action: Mapped[str] = (
        mapped_column(
            String(30),
            nullable=False,
        )
    )

    corrections: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
            default=dict,
        )
    )

    notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    reviewed_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )


# ==========================================================
# AUDIT EVENT
# ==========================================================

class AuditEventModel(Base):

    __tablename__ = (
        "audit_events"
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    document_id: Mapped[str] = (
        mapped_column(
            ForeignKey(
                "documents.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            index=True,
        )
    )

    event_type: Mapped[str] = (
        mapped_column(
            String(100),
            nullable=False,
        )
    )

    actor_type: Mapped[str] = (
        mapped_column(
            String(50),
            nullable=False,
        )
    )

    actor_id: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    details: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
            default=dict,
        )
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )


# ==========================================================
# DOCUMENT BATCH
# PHASE 9.4
# ==========================================================
#
# A batch groups jobs submitted in one user action. It holds
# no status of its own -- that is derived from its jobs by
# derive_batch_status(), every time it is read.
#
# Storing a batch status would create a second place that
# could disagree with the jobs about whether the batch is
# finished, and the jobs would be the ones telling the truth.
# So there is nothing here to fall out of sync.
# ==========================================================

class DocumentBatchModel(Base):

    __tablename__ = (
        "document_batches"
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # How many jobs were accepted into this batch when it was
    # created. Recorded so that a batch whose rows were partly
    # lost is detectable, rather than silently reading as
    # smaller than it was.
    submitted_count: Mapped[int] = (
        mapped_column(
            Integer,
            nullable=False,
            default=0,
        )
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )


# ==========================================================
# DOCUMENT JOB
# PHASE 9.2
# ==========================================================
#
# The durable queue. One row per document awaiting or
# undergoing processing.
#
#
# WHY POSTGRESQL AND NOT REDIS OR CELERY
# ----------------------------------------------------------
#
# PostgreSQL is already a hard dependency, already backed up,
# already monitored and already transactional. A job table
# with SELECT ... FOR UPDATE SKIP LOCKED gives exactly-once
# claiming, durability across restarts and a lease for crash
# recovery, with no new service to deploy, secure or operate.
#
# Redis or Celery would add a broker, a result backend, a
# second failure mode and a second thing to back up, in
# exchange for throughput this workload does not need: the
# bottleneck is a multi-second OCR and LLM pipeline, not queue
# operations per second. If document volume ever outgrows
# that, the claim protocol is the only thing that has to
# change.
#
#
# WHY THE PAYLOAD IS NOT HERE
# ----------------------------------------------------------
#
# A job carries operational metadata and a pointer to the
# uploaded bytes. It does not carry the extraction, the OCR
# text or any extracted field, because a job row is queue
# state and would otherwise become a second, staler copy of
# the document record -- and one that outlives its usefulness
# in a table nobody thinks of as holding personal data.
#
# On success the job records document_id and nothing else.
# ==========================================================

class DocumentJobModel(Base):

    __tablename__ = (
        "document_jobs"
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    batch_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        ForeignKey(
            "document_batches.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    # ------------------------------------------------------
    # STATE
    # ------------------------------------------------------

    status: Mapped[str] = (
        mapped_column(
            String(20),
            nullable=False,
            default="QUEUED",
        )
    )

    # Advisory detail within PROCESSING. Never authoritative:
    # the frontend uses status to decide what to do and
    # current_stage only to choose a label, so a stale stage
    # is cosmetic.
    current_stage: Mapped[
        str | None
    ] = mapped_column(
        String(20),
        nullable=True,
    )

    # ------------------------------------------------------
    # SOURCE
    # ------------------------------------------------------

    original_filename: Mapped[str] = (
        mapped_column(
            String(255),
            nullable=False,
        )
    )

    content_type: Mapped[str] = (
        mapped_column(
            String(100),
            nullable=False,
        )
    )

    size_bytes: Mapped[int] = (
        mapped_column(
            Integer,
            nullable=False,
            default=0,
        )
    )

    # The name of the pending upload, relative to the pending
    # store's own root. A bare name rather than a full path:
    # storing an absolute path would make the rows
    # machine-specific and would put a filesystem path into a
    # value that reaches an API response.
    # ==================================================
    # SOURCE FINGERPRINT
    # PHASE 10.3
    # ==================================================
    #
    # SHA-256 of the uploaded bytes, computed at job
    # creation -- before a worker, before OCR, before a
    # single Groq token. That is the whole point of putting
    # it here rather than only on the document: a duplicate
    # is answerable in an index seek instead of 17 seconds
    # of pipeline.
    #
    # Nullable so that a job whose bytes could not be
    # hashed still queues, and so that jobs created before
    # Phase 10.3 remain valid rows. A null takes part in no
    # uniqueness and blocks nothing, which is the correct
    # behaviour for "not known".
    # ==================================================

    source_sha256: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
    )

    source_name: Mapped[str] = (
        mapped_column(
            String(255),
            nullable=False,
        )
    )

    # ------------------------------------------------------
    # RESULT
    # ------------------------------------------------------

    document_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # ------------------------------------------------------
    # ATTEMPTS
    # ------------------------------------------------------

    attempt_count: Mapped[int] = (
        mapped_column(
            Integer,
            nullable=False,
            default=0,
        )
    )

    max_attempts: Mapped[int] = (
        mapped_column(
            Integer,
            nullable=False,
            default=3,
        )
    )

    next_attempt_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ------------------------------------------------------
    # LEASE
    # ------------------------------------------------------
    #
    # A worker that dies mid-job leaves its row in PROCESSING
    # with nobody working on it. The lease is what makes that
    # recoverable: the row is only genuinely being worked on
    # while lease_expires_at is in the future, so a sweep can
    # return expired ones to the queue without guessing
    # whether the worker is still alive.
    # ------------------------------------------------------

    worker_id: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    lease_expires_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ------------------------------------------------------
    # FAILURE
    # ------------------------------------------------------
    #
    # A code from job_states.JOB_ERROR_CODES and a sentence a
    # person can read. Never str(exception): the same rule the
    # HTTP error contract already follows, because these reach
    # the browser too.
    # ------------------------------------------------------

    safe_error_code: Mapped[
        str | None
    ] = mapped_column(
        String(50),
        nullable=True,
    )

    safe_error_message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # ------------------------------------------------------
    # TIMESTAMPS
    # ------------------------------------------------------

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )

    started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )
    )

    # ------------------------------------------------------
    # INDEXES
    # ------------------------------------------------------
    #
    # Three, each justified by a query that runs constantly
    # rather than by a guess about what might be slow.
    #
    #   claim   the worker's claim query, which filters on
    #           status and orders by created_at, and runs
    #           every poll interval for the life of the
    #           process
    #
    #   batch   the batch status query, which counts jobs by
    #           status for one batch_id, and runs on every
    #           poll from a browser watching a batch upload
    #
    #   active source
    #           PHASE 10.3. Not a performance index. A
    #           CORRECTNESS constraint, described below.
    #
    # Phase 12.9 re-checks these against real plans.
    # ------------------------------------------------------
    #
    # WHY THE ACTIVE-SOURCE INDEX IS UNIQUE AND PARTIAL
    # ------------------------------------------------------
    #
    # Two identical uploads arriving at the same moment must
    # not both start a job. Doing that check in Python --
    # look for an active job, then insert -- has a window
    # between the two statements where both requests see
    # nothing and both insert. Widening the transaction does
    # not close it either: under READ COMMITTED neither
    # transaction can see the other uncommitted row.
    #
    # A unique index has no window. Whichever INSERT reaches
    # the index second fails, and PostgreSQL decides which
    # one that is. The loser is reported as
    # DUPLICATE_IN_PROGRESS.
    #
    # PARTIAL, over ACTIVE_STATUSES only, because uniqueness
    # is wanted for exactly as long as a job is going to be
    # worked on. Once it reaches COMPLETED or FAILED the
    # index entry goes away, which is what allows a
    # deliberate reprocess of the same bytes later --
    # something a unique constraint on all rows, or on
    # documents.source_sha256, would have made impossible.
    #
    # The predicate is built from ACTIVE_STATUSES rather
    # than a literal list, so the constraint and the code
    # cannot end up disagreeing about which states are
    # active.
    # ------------------------------------------------------

    __table_args__ = (
        Index(
            "ix_document_jobs_claim",
            "status",
            "next_attempt_at",
            "created_at",
        ),

        Index(
            "ix_document_jobs_batch",
            "batch_id",
            "status",
        ),

        Index(
            "uq_document_jobs_active_source",
            "source_sha256",
            unique=True,
            postgresql_where=(
                text(
                    "status IN ("
                    + ", ".join(
                        f"'{status}'"
                        for status in ACTIVE_STATUSES
                    )
                    + ")"
                )
            ),
        ),
    )


# ==========================================================
# WORKER HEARTBEAT
# PHASE 11.14
# ==========================================================
#
# WHY THIS TABLE EXISTS
# ----------------------------------------------------------
# A healthy API does not prove a worker exists.
#
# Before this, the only signal an operator had was that the
# API answered /health/ready -- which checks the database and
# the storage root and says nothing whatever about whether
# anything is draining the queue. A deployment could serve
# uploads happily for hours with every worker dead, returning
# 202 to every upload, while the queue grew and no document
# was ever processed.
#
# That is the worst shape of outage: every individual check
# green, the product not working.
#
#
# WHY A TABLE AND NOT A CONFIGURATION VALUE
# ----------------------------------------------------------
# "docker compose ps shows a worker container" is not a
# heartbeat. Nor is "VIGILOX_WORKER_CONCURRENCY is set". Both
# describe intent. A worker process that is running but wedged
# -- stuck on a socket, thrashing, deadlocked -- satisfies
# both and drains nothing.
#
# A heartbeat has to be something the worker can only produce
# by actually running its loop. This row is written from
# inside that loop, so a stale timestamp means the loop
# stopped turning, whatever the container says.
#
# It also has to survive the API process, which is why it is
# in PostgreSQL rather than in memory: the API answers the
# health question and never shares a process with a worker.
#
#
# WHAT IS DELIBERATELY NOT IN HERE
# ----------------------------------------------------------
# No document id, no filename, no extracted value. A heartbeat
# is an operational signal and this table is read by
# monitoring; nothing about a specific person's document
# belongs in it.
#
# current_job_id is the one identifier present, and it is a
# job id -- an opaque uuid that names a unit of work, not a
# person. It is what makes "this worker has been on the same
# job for eleven minutes" answerable.
# ==========================================================

class WorkerHeartbeatModel(Base):

    __tablename__ = "worker_heartbeats"

    # The worker's own identifier, stable for the life of the
    # process. The primary key, so a restarting worker with
    # the same id updates its row rather than accumulating
    # rows -- and a worker with a new id per start would grow
    # this table, which is why default_worker_id derives from
    # the host and process rather than from a uuid4.
    worker_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    # Written every time the loop comes round. This is the
    # value monitoring compares against now().
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(
            timezone=True,
        ),
        nullable=False,
        server_default=func.now(),
    )

    # When this worker process started. Distinguishes "the
    # worker is fine and idle" from "the worker restarted
    # ninety times in the last hour", which look identical if
    # you only have last_seen_at.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(
            timezone=True,
        ),
        nullable=False,
        server_default=func.now(),
    )

    # RUNNING | DRAINING | STOPPED
    #
    # DRAINING is set when SIGTERM has been received and the
    # worker is finishing its current document. Without it, a
    # rolling deploy looks like a worker failure for the
    # length of the grace period.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text(
            "'RUNNING'"
        ),
    )

    # The job in hand, or null when idle. A job id, not a
    # document identity -- see the note above.
    current_job_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # Cumulative for this process, reset by a restart. Read
    # together with started_at to get a rate.
    jobs_completed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text(
            "0"
        ),
    )

    jobs_failed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text(
            "0"
        ),
    )

    # How many jobs this worker will run at once. Recorded so
    # an operator reading the table can tell whether the
    # deployment is configured the way they think.
    concurrency: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text(
            "1"
        ),
    )

    __table_args__ = (
        # Monitoring asks "is any worker recent?", which is an
        # ordered scan over last_seen_at.
        Index(
            "ix_worker_heartbeats_last_seen",
            "last_seen_at",
        ),
    )
