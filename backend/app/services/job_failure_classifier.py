import random
import re

from dataclasses import dataclass

from backend.app.domain.job_states import (
    JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE,
    JOB_ERROR_PROCESSING_FAILED,
    JOB_ERROR_PROVIDER_RATE_LIMITED,
    JOB_ERROR_PROVIDER_TIMEOUT,
    JOB_ERROR_PROVIDER_UNAVAILABLE,
    JOB_ERROR_SOURCE_MISSING,
    JOB_ERROR_UNSUPPORTED_DOCUMENT,
    is_transient,
    safe_message,
)


# ==========================================================
# JOB FAILURE CLASSIFIER
# PHASE 9.3
# ==========================================================
#
# Turns an exception into a decision: retry this, or stop.
#
#
# WHY IT IS A SEPARATE MODULE
# ----------------------------------------------------------
#
# Because the decision is the interesting part and it should
# be testable without a worker, a database or a provider. Every
# branch below is reachable from a unit test that constructs an
# exception and reads the verdict.
#
# It also keeps provider-specific knowledge in one file. The
# worker never imports groq, and never asks what an HTTP 429
# means.
#
#
# THE RULE
# ----------------------------------------------------------
#
# Retry only what a retry could plausibly fix.
#
#     rate limited        yes -- capacity comes back
#     provider 5xx        yes -- the other end is unwell
#     timeout             yes -- may have been a slow moment
#     database down       yes -- infrastructure returns
#
#     unsupported file    no  -- it will be unsupported again
#     malformed job row   no  -- nobody is going to fix it
#     source file gone    no  -- the bytes are not coming back
#     bad credentials     no  -- a person has to change config
#
# Retrying a permanent failure is not merely wasteful. It
# occupies a worker that could be processing a document that
# would succeed, and with OCR at eighteen seconds a median
# that is real throughput spent on a foregone conclusion.
#
#
# WHY BAD CREDENTIALS ARE PERMANENT
# ----------------------------------------------------------
#
# A 401 will be a 401 on all three attempts. It is an operator
# problem, and burning the attempt budget makes the job FAILED
# either way -- just later, and after three round trips. The
# job carries the generic message; the real reason goes to the
# log, where an operator is looking.
# ==========================================================


# Never wait longer than this, whatever a provider asks for.
# A Retry-After of 86400 is a provider telling us to come back
# tomorrow; honouring it literally would leave a job silently
# parked for a day with no operator visibility.
MAX_RETRY_DELAY_SECONDS = 900

# First backoff step. Deliberately not sub-second: nothing
# here is worth hammering.
BASE_RETRY_DELAY_SECONDS = 5

RETRY_BACKOFF_FACTOR = 3

# Plus or minus this proportion. Jitter matters because a
# batch of twenty files hits the rate limit at the same
# instant, and without it all twenty would retry in lockstep
# forever.
RETRY_JITTER = 0.2


@dataclass(frozen=True)
class FailureVerdict:

    code: str

    message: str

    transient: bool

    # From the provider, when it said so. None means fall back
    # to exponential backoff.
    retry_after_seconds: float | None = None

    # For the log only. Never persisted on the job row and
    # never serialized to an API response.
    error_type: str = ""

    detail: str = ""


# ==========================================================
# RETRY-AFTER
# ==========================================================

def _retry_after_from(
    exception: Exception,
) -> float | None:

    """
    Read a Retry-After the provider actually sent.

    Honouring it is the difference between backing off
    politely and guessing. Both header forms are accepted, and
    anything unparseable is ignored rather than treated as
    zero -- a zero would turn a rate limit into a hot loop,
    which is the specific thing this must never do.
    """

    response = getattr(
        exception,
        "response",
        None,
    )

    headers = getattr(
        response,
        "headers",
        None,
    )


    raw = None


    if headers is not None:

        for name in (
            "retry-after",
            "Retry-After",
            "x-ratelimit-reset-tokens",
            "x-ratelimit-reset-requests",
        ):

            try:
                found = headers.get(
                    name
                )

            except Exception:      # noqa: BLE001
                found = None


            if found:
                raw = found
                break


    if raw is None:
        return None


    text = str(
        raw
    ).strip()


    # Plain seconds.
    try:
        seconds = float(
            text
        )

    except ValueError:
        seconds = None


    if seconds is None:

        # Groq also uses forms like "2m59.56s" and "1.5s".
        match = re.fullmatch(
            r"(?:(\d+(?:\.\d+)?)m)?"
            r"(?:(\d+(?:\.\d+)?)s)?",
            text,
        )

        if not match or not any(
            match.groups()
        ):
            return None


        minutes = float(
            match.group(1) or 0
        )

        secs = float(
            match.group(2) or 0
        )

        seconds = (
            minutes * 60.0
            + secs
        )


    if seconds < 0:
        return None


    return min(
        seconds,
        float(
            MAX_RETRY_DELAY_SECONDS
        ),
    )


# ==========================================================
# BACKOFF
# ==========================================================

def retry_delay_seconds(
    *,
    attempt_count: int,
    retry_after_seconds: float | None = None,
    jitter: bool = True,
) -> float:

    """
    How long to park a job before its next attempt.

    A provider's own Retry-After wins when it sent one,
    because it knows when capacity returns and we do not.
    Otherwise: bounded exponential backoff with jitter.

    attempt_count is the number of attempts already made, so
    the first retry is one base delay rather than zero.
    """

    if retry_after_seconds is not None:

        base = max(
            float(
                retry_after_seconds
            ),
            1.0,
        )

    else:

        exponent = max(
            0,
            int(
                attempt_count
            )
            - 1,
        )

        base = (
            BASE_RETRY_DELAY_SECONDS
            * (
                RETRY_BACKOFF_FACTOR
                ** exponent
            )
        )


    base = min(
        base,
        float(
            MAX_RETRY_DELAY_SECONDS
        ),
    )


    if not jitter:
        return round(
            base,
            3,
        )


    spread = (
        base
        * RETRY_JITTER
    )

    jittered = (
        base
        + random.uniform(
            -spread,
            spread,
        )
    )

    # Never below a second, whatever the jitter did.
    return round(
        max(
            1.0,
            jittered,
        ),
        3,
    )


# ==========================================================
# PERMANENT SENTINEL
# ==========================================================

class UnsupportedDocumentError(
    RuntimeError
):
    """
    A document that cannot be recognised as one of the
    supported types.

    NOTHING RAISES THIS, AND THAT IS THE PHASE 10.2 DECISION.
    ------------------------------------------------------
    This class was added in Phase 9 in anticipation of Phase
    10.2, and the docstring used to say Phase 10.2 raises it.
    It does not.

    Phase 10.2 concluded that an unsupported document is a
    successful DOMAIN OUTCOME rather than a job failure: the
    pipeline ran to the end, produced a record and a
    classification, and the job COMPLETED. Failing the job
    would have made the outcome look transient and invited a
    retry that cannot change anything, since classification is
    deterministic over the same bytes.

    See backend/app/domain/classification.py.

    It is kept, rather than deleted, as a fail-safe: if any
    future path does raise it, the classifier treats it as
    PERMANENT instead of burning three job attempts on a
    document that will classify the same way every time.
    Flagged for the Phase 12 dead-code audit so the decision
    gets looked at again rather than inherited.
    """


class JobDataError(
    RuntimeError
):
    """
    Raised when a job row itself is unusable -- a source name
    that fails validation, a missing required field.

    Permanent by definition: the row is not going to repair
    itself, and retrying re-reads the same bad data.
    """


# ==========================================================
# CLASSIFY
# ==========================================================

def classify(
    exception: BaseException,
) -> FailureVerdict:

    """
    The verdict for one failed attempt.

    Ordered most specific first. The final fallback is
    permanent on purpose: an exception nobody has classified
    is not known to be retryable, and treating unknowns as
    retryable would let one novel bug consume the whole
    attempt budget of every document that hits it.
    """

    error_type = type(
        exception
    ).__name__

    detail = str(
        exception
    )[:500]


    def verdict(
        code: str,
        retry_after: float | None = None,
    ) -> FailureVerdict:

        return FailureVerdict(
            code=code,
            message=safe_message(
                code
            ),
            transient=is_transient(
                code
            ),
            retry_after_seconds=retry_after,
            error_type=error_type,
            detail=detail,
        )


    # ------------------------------------------------------
    # OUR OWN PERMANENT SIGNALS
    # ------------------------------------------------------

    if isinstance(
        exception,
        UnsupportedDocumentError,
    ):
        return verdict(
            JOB_ERROR_UNSUPPORTED_DOCUMENT
        )


    if isinstance(
        exception,
        JobDataError,
    ):
        return verdict(
            JOB_ERROR_PROCESSING_FAILED
        )


    # ------------------------------------------------------
    # THE SOURCE FILE
    # ------------------------------------------------------
    #
    # The bytes are gone. No number of retries brings them
    # back, and the reader-facing message says to upload
    # again, which is the only thing that will work.
    # ------------------------------------------------------

    if isinstance(
        exception,
        FileNotFoundError,
    ):
        return verdict(
            JOB_ERROR_SOURCE_MISSING
        )


    # ------------------------------------------------------
    # THE PROVIDER
    # ------------------------------------------------------
    #
    # groq is imported lazily so this module stays importable
    # -- and unit-testable -- in an environment without the
    # SDK or without credentials.
    # ------------------------------------------------------

    provider = (
        _classify_provider(
            exception,
            verdict,
        )
    )

    if provider is not None:
        return provider


    # ------------------------------------------------------
    # INFRASTRUCTURE
    # ------------------------------------------------------

    infrastructure = (
        _classify_infrastructure(
            exception,
            verdict,
        )
    )

    if infrastructure is not None:
        return infrastructure


    # ------------------------------------------------------
    # EVERYTHING ELSE
    # ------------------------------------------------------
    #
    # ValueError and RuntimeError reach here from extraction
    # when the model could not produce a valid structured
    # document. Extraction already retries that internally,
    # so by the time it escapes it has been tried and it is
    # done.
    # ------------------------------------------------------

    return verdict(
        JOB_ERROR_PROCESSING_FAILED
    )


def _classify_provider(
    exception: BaseException,
    verdict,
) -> FailureVerdict | None:

    try:
        import groq

    except Exception:      # noqa: BLE001
        return None


    if isinstance(
        exception,
        groq.RateLimitError,
    ):
        return verdict(
            JOB_ERROR_PROVIDER_RATE_LIMITED,
            _retry_after_from(
                exception
            ),
        )


    if isinstance(
        exception,
        groq.APITimeoutError,
    ):
        return verdict(
            JOB_ERROR_PROVIDER_TIMEOUT
        )


    if isinstance(
        exception,
        groq.APIConnectionError,
    ):
        return verdict(
            JOB_ERROR_PROVIDER_UNAVAILABLE
        )


    if isinstance(
        exception,
        (
            groq.AuthenticationError,
            groq.PermissionDeniedError,
        ),
    ):
        # Permanent. A person has to change configuration; the
        # real reason is in the log, not on the job row.
        return verdict(
            JOB_ERROR_PROCESSING_FAILED
        )


    if isinstance(
        exception,
        groq.APIStatusError,
    ):

        status = getattr(
            exception,
            "status_code",
            None,
        )

        if isinstance(
            status,
            int,
        ):

            if status == 429:
                return verdict(
                    JOB_ERROR_PROVIDER_RATE_LIMITED,
                    _retry_after_from(
                        exception
                    ),
                )

            if status >= 500:
                return verdict(
                    JOB_ERROR_PROVIDER_UNAVAILABLE,
                    _retry_after_from(
                        exception
                    ),
                )

            # Any other 4xx is us, not them. Sending the same
            # request again produces the same answer.
            return verdict(
                JOB_ERROR_PROCESSING_FAILED
            )


        return verdict(
            JOB_ERROR_PROVIDER_UNAVAILABLE
        )


    return None


def _classify_infrastructure(
    exception: BaseException,
    verdict,
) -> FailureVerdict | None:

    try:
        from sqlalchemy.exc import (
            DBAPIError,
            OperationalError,
        )

    except Exception:      # noqa: BLE001
        return None


    # A dropped connection or a database restart. The write
    # may simply succeed next time, and failing the document
    # permanently because PostgreSQL blinked would be wrong.
    if isinstance(
        exception,
        OperationalError,
    ):
        return verdict(
            JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE
        )


    if isinstance(
        exception,
        DBAPIError,
    ):

        # connection_invalidated is SQLAlchemy telling us this
        # was a transport problem rather than a rejected
        # statement. An IntegrityError is not retryable and
        # falls through to permanent.
        if getattr(
            exception,
            "connection_invalidated",
            False,
        ):
            return verdict(
                JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE
            )


        return None


    if isinstance(
        exception,
        (
            ConnectionError,
            TimeoutError,
        ),
    ):
        return verdict(
            JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE
        )


    # A full disk is transient in the sense that matters:
    # someone frees space and the retry works.
    if isinstance(
        exception,
        OSError,
    ) and getattr(
        exception,
        "errno",
        None,
    ) in (
        28,      # ENOSPC
        122,     # EDQUOT
    ):
        return verdict(
            JOB_ERROR_INFRASTRUCTURE_UNAVAILABLE
        )


    return None
