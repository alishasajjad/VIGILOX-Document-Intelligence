# ==========================================================
# DOCUMENT JOB STATES
# PHASE 9.2
# ==========================================================
#
# The single authority for what a job can be. Both the API
# schema and the worker read from here, so a state cannot
# exist in one and not the other.
#
#
# WHY THERE ARE ONLY FIVE
# ----------------------------------------------------------
#
# It is tempting to expose OCR, EXTRACTING, VALIDATING and
# PERSISTING as top-level states, because a progress bar with
# four labelled steps looks like a more capable product than
# one that says "processing".
#
# But a state is a promise. If the frontend can render
# EXTRACTING, then something has to write EXTRACTING, at the
# moment it becomes true, durably, and it has to be correct
# when a worker dies mid-stage. Four extra states means four
# extra database writes per document, on the hot path, for
# presentation.
#
# So the states are the ones that change what the system does:
#
#     QUEUED       waiting for a worker
#     PROCESSING   a worker holds a lease on it
#     RETRY_WAIT   a transient failure; next_attempt_at is set
#     COMPLETED    document_id is available
#     FAILED       terminal; safe_error_code explains it
#
# and the finer detail lives in current_stage, which is
# advisory. The distinction is deliberate and the frontend
# honours it: status drives what the page does, current_stage
# only ever changes a label. A stale stage is cosmetic; a
# stale status would be a bug.
#
#
# WHAT IS NOT HERE
# ----------------------------------------------------------
#
# No percentage. The pipeline cannot report progress within a
# stage -- PaddleOCR does not stream, and the Groq call is one
# request -- so any number between 0 and 100 would be
# invented. A stage name is the honest resolution.
# ==========================================================


# ==========================================================
# STATUS
# ==========================================================

QUEUED = "QUEUED"

PROCESSING = "PROCESSING"

RETRY_WAIT = "RETRY_WAIT"

COMPLETED = "COMPLETED"

FAILED = "FAILED"


JOB_STATUSES = (
    QUEUED,
    PROCESSING,
    RETRY_WAIT,
    COMPLETED,
    FAILED,
)


# A job in one of these is finished and will never move again.
TERMINAL_STATUSES = (
    COMPLETED,
    FAILED,
)


# A job in one of these is still going to be worked on, one
# way or another. The exact complement of TERMINAL_STATUSES.
#
# PHASE 10.3 needs this as a set the DATABASE can enforce
# against: the partial unique index that stops two concurrent
# jobs existing for identical source bytes is declared over
# exactly these three states. So the tuple is the single
# definition of "active", and the index, the query and the
# tests all read it from here.
ACTIVE_STATUSES = (
    QUEUED,
    PROCESSING,
    RETRY_WAIT,
)


# A job in one of these is waiting to be picked up. RETRY_WAIT
# counts, but only once next_attempt_at has passed.
CLAIMABLE_STATUSES = (
    QUEUED,
    RETRY_WAIT,
)


# ==========================================================
# STAGE
# ==========================================================
#
# Advisory detail within PROCESSING. The worker writes these
# as it advances, and each one costs a database update, so
# they are coarse on purpose: one per pipeline phase that
# takes real time, not one per function call.
# ==========================================================

STAGE_READING = "READING"

STAGE_OCR = "OCR"

STAGE_EXTRACTING = "EXTRACTING"

STAGE_VALIDATING = "VALIDATING"

STAGE_PERSISTING = "PERSISTING"


JOB_STAGES = (
    STAGE_READING,
    STAGE_OCR,
    STAGE_EXTRACTING,
    STAGE_VALIDATING,
    STAGE_PERSISTING,
)


# ==========================================================
# FAILURE CODES
# ==========================================================
#
# Every code a job row may carry. These reach the browser, so
# they are a vocabulary rather than whatever str(exception)
# happened to say -- the existing error contract rule, applied
# to jobs.
#
# TRANSIENT_CODES are the ones worth retrying. Everything else
# is terminal on the first attempt: retrying an unsupported
# file type just wastes a worker and delays the answer.
# ==========================================================

JOB_ERROR_PROVIDER_RATE_LIMITED = (
    "PROVIDER_RATE_LIMITED"
)

JOB_ERROR_PROVIDER_UNAVAILABLE = (
    "PROVIDER_UNAVAILABLE"
)

JOB_ERROR_PROVIDER_TIMEOUT = (
    "PROVIDER_TIMEOUT"
)

# The database or the filesystem, not the LLM provider.
# Distinguished from PROVIDER_UNAVAILABLE because the two lead
# an operator to look in completely different places, and a
# job row saying "provider" while PostgreSQL is down would
# send them the wrong way.
JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE = (
    "INFRASTRUCTURE_UNAVAILABLE"
)

JOB_ERROR_SOURCE_MISSING = (
    "SOURCE_MISSING"
)

JOB_ERROR_UNSUPPORTED_DOCUMENT = (
    "UNSUPPORTED_DOCUMENT"
)

JOB_ERROR_PROCESSING_FAILED = (
    "PROCESSING_FAILED"
)

JOB_ERROR_ATTEMPTS_EXHAUSTED = (
    "ATTEMPTS_EXHAUSTED"
)

JOB_ERROR_ABANDONED = (
    "ABANDONED"
)


JOB_ERROR_CODES = (
    JOB_ERROR_PROVIDER_RATE_LIMITED,
    JOB_ERROR_PROVIDER_UNAVAILABLE,
    JOB_ERROR_PROVIDER_TIMEOUT,
    JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE,
    JOB_ERROR_SOURCE_MISSING,
    JOB_ERROR_UNSUPPORTED_DOCUMENT,
    JOB_ERROR_PROCESSING_FAILED,
    JOB_ERROR_ATTEMPTS_EXHAUSTED,
    JOB_ERROR_ABANDONED,
)


TRANSIENT_CODES = (
    JOB_ERROR_PROVIDER_RATE_LIMITED,
    JOB_ERROR_PROVIDER_UNAVAILABLE,
    JOB_ERROR_PROVIDER_TIMEOUT,
    JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE,
)


# ==========================================================
# SAFE MESSAGES
# ==========================================================
#
# What a person reads. Deliberately free of provider names,
# internal service names, file paths and exception text.
# ==========================================================

SAFE_MESSAGES = {
    JOB_ERROR_PROVIDER_RATE_LIMITED: (
        "The document intelligence service is at "
        "capacity. This document is queued and will be "
        "retried automatically."
    ),

    JOB_ERROR_PROVIDER_UNAVAILABLE: (
        "The document intelligence service is "
        "temporarily unavailable. This document will be "
        "retried automatically."
    ),

    JOB_ERROR_PROVIDER_TIMEOUT: (
        "Reading this document took longer than "
        "allowed. It will be retried automatically."
    ),

    JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE: (
        "A system this service depends on is "
        "temporarily unavailable. This document will "
        "be retried automatically."
    ),

    JOB_ERROR_SOURCE_MISSING: (
        "The uploaded file is no longer available and "
        "cannot be processed. Please upload it again."
    ),

    JOB_ERROR_UNSUPPORTED_DOCUMENT: (
        "This document could not be recognised as a "
        "supported document type."
    ),

    JOB_ERROR_PROCESSING_FAILED: (
        "This document could not be processed."
    ),

    JOB_ERROR_ATTEMPTS_EXHAUSTED: (
        "This document could not be processed after "
        "several attempts."
    ),

    JOB_ERROR_ABANDONED: (
        "Processing was interrupted and could not be "
        "resumed."
    ),
}


def safe_message(
    code: str | None,
) -> str:

    """
    The reader-facing sentence for a failure code.

    An unknown code returns the generic sentence rather than
    the code itself, so a code added to the worker without a
    message here cannot leak an identifier into the interface.
    """

    if code is None:
        return ""


    return SAFE_MESSAGES.get(
        code,
        SAFE_MESSAGES[
            JOB_ERROR_PROCESSING_FAILED
        ],
    )


def is_transient(
    code: str | None,
) -> bool:

    return code in TRANSIENT_CODES


# ==========================================================
# BATCH STATUS
# ==========================================================
#
# A batch has no state of its own worth storing. It is
# derived, every time, from the jobs it contains -- because
# storing it would mean two places could disagree about
# whether a batch is finished, and the jobs would be right.
# ==========================================================

BATCH_QUEUED = "QUEUED"

BATCH_PROCESSING = "PROCESSING"

BATCH_COMPLETED = "COMPLETED"

BATCH_COMPLETED_WITH_FAILURES = (
    "COMPLETED_WITH_FAILURES"
)

BATCH_FAILED = "FAILED"


BATCH_STATUSES = (
    BATCH_QUEUED,
    BATCH_PROCESSING,
    BATCH_COMPLETED,
    BATCH_COMPLETED_WITH_FAILURES,
    BATCH_FAILED,
)


def derive_batch_status(
    counts: dict[str, int],
) -> str:

    """
    The status of a batch, from the states of its jobs.

    counts maps a job status to how many jobs are in it.

    One failed file must never invalidate the files that
    succeeded, so a batch with both is COMPLETED_WITH_FAILURES
    and the successful document ids stay available. Only a
    batch where everything failed is FAILED.
    """

    total = sum(
        counts.get(
            status,
            0,
        )
        for status in JOB_STATUSES
    )


    if total == 0:
        return BATCH_QUEUED


    completed = counts.get(
        COMPLETED,
        0,
    )

    failed = counts.get(
        FAILED,
        0,
    )

    finished = completed + failed


    if finished < total:

        # Anything still moving means the batch is working,
        # including a job sitting in RETRY_WAIT.
        if counts.get(
            PROCESSING,
            0,
        ) or counts.get(
            RETRY_WAIT,
            0,
        ):
            return BATCH_PROCESSING


        if completed or failed:
            return BATCH_PROCESSING


        return BATCH_QUEUED


    if failed == 0:
        return BATCH_COMPLETED


    if completed == 0:
        return BATCH_FAILED


    return BATCH_COMPLETED_WITH_FAILURES
