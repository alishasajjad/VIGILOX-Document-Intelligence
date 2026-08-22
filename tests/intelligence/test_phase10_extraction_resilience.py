"""
==========================================================
PHASE 10.4 - EXTRACTION RESILIENCE
==========================================================

WHAT THIS SUITE IS PROTECTING
----------------------------------------------------------

  1. The two retry layers stay separate. Structured-output
     failures belong to ExtractionService; provider and
     network failures belong to the job layer. If either
     starts handling the other, retries multiply.

  2. The worst-case provider work for one document is a known
     number, computed from the values actually in force.

  3. That worst case FITS INSIDE THE WORKER LEASE. This is the
     assertion that matters most, because it was false before
     Phase 10.4 and nothing was checking it.

  4. The model is configurable and the fallback is narrow: it
     fires only when the provider says the model does not
     exist, never on a rate limit or an outage.

NO PROVIDER CALLS
----------------------------------------------------------

Every test here uses a fake Groq client. The real measurements
that set the defaults live in
scripts/development/extraction_latency_study.py and are quoted
in the service, not re-run here.
"""

import ast
import inspect
import json
import os
import sys
import textwrap

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


# A key is required to construct the service, and no request is
# ever made with it. Set before the import so a machine with no
# .env can still run this suite.
os.environ.setdefault(
    "GROQ_API_KEY",
    "test-key-not-used",
)


import groq                                       # noqa: E402
import httpx                                      # noqa: E402

from backend.app.services import (                # noqa: E402
    extraction_service as extraction_module,
)

from backend.app.services.extraction_service import (  # noqa: E402
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_READ_TIMEOUT_SECONDS,
    DEFAULT_STRUCTURED_OUTPUT_ATTEMPTS,
    ExtractionService,
)

from backend.app.services.document_worker import (     # noqa: E402
    DEFAULT_LEASE_SECONDS,
)

from backend.app.services.job_service import (         # noqa: E402
    DEFAULT_MAX_ATTEMPTS,
)

from backend.app.services.job_failure_classifier import (  # noqa: E402
    classify,
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
# A FAKE PROVIDER
# ==========================================================

VALID_EXTRACTION = {
    "document_type": "guard_license",

    "full_name": {
        "value": "SAMPLE, JANE",
        "source_line_ids": ["L2"],
    },

    "licence_number": {
        "value": "12345678",
        "source_line_ids": ["L3"],
    },

    "id_number": {
        "value": None,
        "source_line_ids": [],
    },

    "expiry_date": {
        "value": "2027-01-01",
        "source_line_ids": ["L4"],
    },

    "date_of_birth": {
        "value": None,
        "source_line_ids": [],
    },

    "issue_date": {
        "value": None,
        "source_line_ids": [],
    },

    "issuer": {
        "value": "TX DPS",
        "source_line_ids": ["L5"],
    },
}


OCR_LINES = [
    {
        "line_id": "L0",
        "text": "TEXAS DEPARTMENT OF PUBLIC SAFETY",
        "confidence": 0.99,
        "bbox": [[0, 0], [10, 0], [10, 5], [0, 5]],
    },
    {
        "line_id": "L1",
        "text": "SECURITY GUARD LICENSE",
        "confidence": 0.99,
        "bbox": [[0, 6], [10, 6], [10, 11], [0, 11]],
    },
    {
        "line_id": "L2",
        "text": "NAME SAMPLE, JANE",
        "confidence": 0.99,
        "bbox": [[0, 12], [10, 12], [10, 17], [0, 17]],
    },
    {
        "line_id": "L3",
        "text": "LICENSE NO 12345678",
        "confidence": 0.99,
        "bbox": [[0, 18], [10, 18], [10, 23], [0, 23]],
    },
    {
        "line_id": "L4",
        "text": "EXPIRES 2027-01-01",
        "confidence": 0.99,
        "bbox": [[0, 24], [10, 24], [10, 29], [0, 29]],
    },
    {
        "line_id": "L5",
        "text": "ISSUED BY TX DPS",
        "confidence": 0.99,
        "bbox": [[0, 30], [10, 30], [10, 35], [0, 35]],
    },
]


def json_generation_error() -> groq.BadRequestError:

    """
    The 400 the provider returns when it cannot produce JSON
    matching a strict schema.

    The message text matters: the service keys on it to decide
    whether the failure is a formatting problem worth asking
    again, or something else that must propagate.
    """

    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
    )

    response = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "code": "json_validate_failed",
                "message": (
                    "Failed to generate JSON. "
                    "Generated JSON does not match "
                    "the expected schema."
                ),
            }
        },
    )

    return groq.BadRequestError(
        "json_validate_failed: Failed to generate JSON.",
        response=response,
        body=None,
    )


def rate_limit_error() -> groq.RateLimitError:

    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
    )

    response = httpx.Response(
        429,
        request=request,
        headers={
            "retry-after": "30",
        },
        json={
            "error": {
                "message": "Rate limit reached.",
            }
        },
    )

    return groq.RateLimitError(
        "Rate limit reached.",
        response=response,
        body=None,
    )


def model_not_found_error() -> groq.NotFoundError:

    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
    )

    response = httpx.Response(
        404,
        request=request,
        json={
            "error": {
                "code": "model_not_found",
                "message": (
                    "The model `retired-model` does not "
                    "exist or you do not have access "
                    "to it."
                ),
            }
        },
    )

    return groq.NotFoundError(
        (
            "Error code: 404 - model_not_found: The model "
            "does not exist or you do not have access to it."
        ),
        response=response,
        body=None,
    )


class FakeCompletions:

    def __init__(
        self,
        outcomes,
    ) -> None:

        # One entry per call: either an exception to raise, or
        # a payload to return.
        self.outcomes = list(
            outcomes
        )

        self.calls: list[dict] = []


    def create(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        outcome = (
            self.outcomes.pop(0)
            if self.outcomes
            else VALID_EXTRACTION
        )

        if isinstance(
            outcome,
            BaseException,
        ):
            raise outcome


        # The shape the service reads: choices[0].message.content
        # holding a JSON string.
        class Message:
            content = json.dumps(
                outcome
            )

        class Choice:
            message = Message()

        class Response:
            choices = [
                Choice()
            ]

        return Response()


class FakeClient:

    def __init__(
        self,
        outcomes,
    ) -> None:

        self.completions = FakeCompletions(
            outcomes
        )

        class Chat:
            pass

        self.chat = Chat()

        self.chat.completions = (
            self.completions
        )

        self.max_retries = 1


def service_with(
    outcomes,
    **kwargs,
) -> tuple:

    """
    A real ExtractionService with a fake client attached.

    The service is constructed normally, so its configuration
    and its prompt building are the real ones. Only the
    transport is replaced.
    """

    service = ExtractionService(
        **kwargs
    )

    client = FakeClient(
        outcomes
    )

    service.client = client

    return service, client


# ==========================================================
# 1. CONFIGURATION IS EXPLICIT
# ==========================================================

def test_configuration_is_explicit() -> None:

    section(
        "TEST 1 - NOTHING IS LEFT TO AN SDK DEFAULT"
    )

    service = ExtractionService()

    assert_equal(
        service.model,
        DEFAULT_MODEL,
        "The model comes from configuration.",
    )

    assert_equal(
        service.max_retries,
        DEFAULT_MAX_RETRIES,
        "The retry count is set explicitly.",
    )

    assert_true(
        DEFAULT_MAX_RETRIES
        < groq._constants.DEFAULT_MAX_RETRIES,
        (
            "The retry count must be a DELIBERATE value "
            "below the SDK default, not the SDK default "
            "inherited by accident. The SDK ships 2; "
            "Phase 10.4 measured that the second retry only "
            "helps when two attempts fail consecutively, "
            "which is the job layer's job, while costing a "
            "read timeout plus a sleep in the worst case."
        ),
    )

    assert_equal(
        service.read_timeout_seconds,
        DEFAULT_READ_TIMEOUT_SECONDS,
        "The read timeout is set explicitly.",
    )

    assert_true(
        service.fallback_model is None,
        (
            "There is NO default fallback model. A "
            "hard-coded second model would change extraction "
            "semantics without anybody choosing it."
        ),
    )

    ok(
        f"model={service.model}, "
        f"max_retries={service.max_retries} "
        f"(SDK default is "
        f"{groq._constants.DEFAULT_MAX_RETRIES}), "
        f"read_timeout={service.read_timeout_seconds}s, "
        "no default fallback"
    )


    # ------------------------------------------------------
    # THE CLIENT ACTUALLY RECEIVED THEM
    # ------------------------------------------------------

    assert_equal(
        service.client.max_retries,
        DEFAULT_MAX_RETRIES,
        (
            "The configured retry count must reach the Groq "
            "client. Setting it on the service and not on the "
            "client would leave the SDK default in force "
            "while every comment and every budget calculation "
            "claimed otherwise."
        ),
    )

    timeout = service.client.timeout

    assert_equal(
        timeout.read,
        DEFAULT_READ_TIMEOUT_SECONDS,
        (
            "The configured read timeout must reach the "
            "client."
        ),
    )

    ok(
        "The Groq client carries the configured retry count "
        f"and read timeout ({timeout.read}s read, "
        f"{timeout.connect}s connect)"
    )


def test_configuration_from_environment() -> None:

    section(
        "TEST 2 - CONFIGURATION COMES FROM THE ENVIRONMENT"
    )

    original = {
        name: os.environ.get(
            name
        )
        for name in (
            "VIGILOX_GROQ_MODEL",
            "VIGILOX_GROQ_FALLBACK_MODEL",
            "VIGILOX_GROQ_MAX_RETRIES",
            "VIGILOX_GROQ_READ_TIMEOUT_SECONDS",
            "VIGILOX_EXTRACTION_ATTEMPTS",
        )
    }

    try:

        os.environ[
            "VIGILOX_GROQ_MODEL"
        ] = "configured/primary"

        os.environ[
            "VIGILOX_GROQ_FALLBACK_MODEL"
        ] = "configured/fallback"

        os.environ[
            "VIGILOX_GROQ_MAX_RETRIES"
        ] = "0"

        os.environ[
            "VIGILOX_GROQ_READ_TIMEOUT_SECONDS"
        ] = "12.5"

        os.environ[
            "VIGILOX_EXTRACTION_ATTEMPTS"
        ] = "2"

        service = ExtractionService()

        assert_equal(
            service.model,
            "configured/primary",
            "The model is configurable.",
        )

        assert_equal(
            service.fallback_model,
            "configured/fallback",
            "The fallback is configurable.",
        )

        assert_equal(
            service.max_retries,
            0,
            (
                "Zero must be honoured rather than treated "
                "as unset. An operator disabling SDK retries "
                "has to be able to."
            ),
        )

        assert_equal(
            service.read_timeout_seconds,
            12.5,
            "The read timeout is configurable.",
        )

        assert_equal(
            service.max_structured_output_attempts,
            2,
            "The attempt count is configurable.",
        )

        ok(
            "Model, fallback, retries, timeout and attempts "
            "all read from the environment, and 0 is honoured "
            "rather than treated as unset"
        )


        # ----------------------------------------------
        # A MALFORMED SETTING FALLS BACK
        # ----------------------------------------------

        os.environ[
            "VIGILOX_GROQ_MAX_RETRIES"
        ] = "not-a-number"

        service = ExtractionService()

        assert_equal(
            service.max_retries,
            DEFAULT_MAX_RETRIES,
            (
                "A malformed tuning value must fall back to "
                "the measured default rather than taking the "
                "process down. It is a knob, not a "
                "correctness input."
            ),
        )

        ok(
            "A malformed value falls back to the measured "
            "default instead of raising"
        )


    finally:

        for name, value in original.items():

            if value is None:
                os.environ.pop(
                    name,
                    None,
                )

            else:
                os.environ[
                    name
                ] = value


# ==========================================================
# 3. THE CALL BUDGET
# ==========================================================

def test_call_budget() -> None:

    section(
        "TEST 3 - THE WORST-CASE PROVIDER CALL BUDGET"
    )

    service = ExtractionService()

    budget = service.call_budget(
        job_attempts=DEFAULT_MAX_ATTEMPTS,
    )

    attempts = (
        DEFAULT_STRUCTURED_OUTPUT_ATTEMPTS
    )

    expected_per_create = (
        1
        + DEFAULT_MAX_RETRIES
    )

    assert_equal(
        budget[
            "http_requests_per_create"
        ],
        expected_per_create,
        (
            "One request plus the configured SDK retries."
        ),
    )


    # ------------------------------------------------------
    # THE NUMBER IS NOT THE NAIVE PRODUCT
    # ------------------------------------------------------

    naive = (
        DEFAULT_MAX_ATTEMPTS
        * attempts
        * expected_per_create
    )

    assert_true(
        budget[
            "http_requests_per_document"
        ]
        < naive,
        (
            "The budget must be smaller than "
            "job_attempts x extraction_attempts x "
            "(1 + retries).\n\n"
            "That product assumes every structured-output "
            "attempt can pay for SDK retries. It cannot: a "
            "retryable error is not caught by the "
            "structured-output loop, so it propagates on the "
            "first attempt that hits one. Only the LAST "
            "attempt executed in a job attempt can spend more "
            "than a single request.\n\n"
            f"naive={naive} "
            f"actual="
            f"{budget['http_requests_per_document']}"
        ),
    )

    expected_per_job_attempt = (
        (
            attempts
            - 1
        )
        + expected_per_create
    )

    assert_equal(
        budget[
            "http_requests_per_job_attempt"
        ],
        expected_per_job_attempt,
        (
            "(attempts - 1) json failures at one request "
            "each, plus one attempt that ends in a retryable "
            "error and therefore pays the SDK retries."
        ),
    )

    assert_equal(
        budget[
            "http_requests_per_document"
        ],
        expected_per_job_attempt
        * DEFAULT_MAX_ATTEMPTS,
        (
            "And that, once per job attempt."
        ),
    )

    ok(
        "Worst case "
        f"{budget['http_requests_per_document']} provider "
        f"requests per document "
        f"({expected_per_job_attempt} per job attempt x "
        f"{DEFAULT_MAX_ATTEMPTS} attempts), against a naive "
        f"product of {naive}"
    )


def test_call_budget_fits_lease() -> None:

    section(
        "TEST 4 - THE WORST CASE FITS INSIDE THE LEASE"
    )

    # ------------------------------------------------------
    # THIS IS THE ASSERTION PHASE 10.4 EXISTS FOR.
    #
    # Before it, the extraction configuration allowed a single
    # job attempt to run for 943 seconds against a 180 second
    # lease -- 5.2 times over. Nothing was wrong in the sense
    # of incorrect: mark_completed is scoped to a job still
    # PROCESSING under the same worker, so the late worker
    # could not overwrite the new owner's result and its
    # document was discarded. But a slow document was
    # processed twice, and the only trace was a log line.
    # ------------------------------------------------------

    service = ExtractionService()

    budget = service.call_budget(
        job_attempts=DEFAULT_MAX_ATTEMPTS,
    )

    # Measured, from the latency study. The lease has to cover
    # the whole pipeline in one window, because the pipeline
    # runs as a single call between two stage markers and the
    # worker cannot extend a lease from inside it.
    measured_ocr_maximum = 43.0

    other_stages = 5.0

    worst_case = (
        budget[
            "seconds_per_job_attempt"
        ]
        + measured_ocr_maximum
        + other_stages
    )

    # 90%, not 100%. A bound that only just fits is not a
    # bound: the OCR figure came from nine documents on one
    # machine.
    ceiling = (
        DEFAULT_LEASE_SECONDS
        * 0.9
    )

    assert_true(
        worst_case <= ceiling,
        (
            "The worst-case pipeline time must fit inside 90% "
            "of the worker lease.\n\n"
            f"extraction worst case  "
            f"{budget['seconds_per_job_attempt']:.0f}s\n"
            f"measured OCR maximum   "
            f"{measured_ocr_maximum:.0f}s\n"
            f"other stages           "
            f"{other_stages:.0f}s\n"
            f"total                  {worst_case:.0f}s\n"
            f"lease                  "
            f"{DEFAULT_LEASE_SECONDS}s\n"
            f"90% of lease           {ceiling:.0f}s\n\n"
            "If this fails, either the extraction "
            "configuration got more expensive or the lease "
            "got shorter. Raising the lease and lowering the "
            "read timeout or the retry count are both valid "
            "fixes; ignoring it means a healthy worker can "
            "lose its own job mid-document and the work is "
            "done twice."
        ),
    )

    ok(
        f"worst case {worst_case:.0f}s vs lease "
        f"{DEFAULT_LEASE_SECONDS}s "
        f"({100 * worst_case / DEFAULT_LEASE_SECONDS:.0f}% "
        "utilisation)"
    )


# ==========================================================
# 5. RETRY OWNERSHIP
# ==========================================================

def test_structured_output_retry_is_bounded() -> None:

    section(
        "TEST 5 - STRUCTURED-OUTPUT RETRY IS BOUNDED"
    )

    attempts = (
        DEFAULT_STRUCTURED_OUTPUT_ATTEMPTS
    )

    # ------------------------------------------------------
    # A recoverable formatting failure, then success.
    # ------------------------------------------------------

    service, client = service_with(
        [
            json_generation_error(),
            VALID_EXTRACTION,
        ]
    )

    result = service.extract(
        OCR_LINES
    )

    assert_equal(
        result.document_type,
        "guard_license",
        (
            "A formatting failure followed by a good response "
            "must produce the extraction."
        ),
    )

    assert_equal(
        len(
            client.completions.calls
        ),
        2,
        "One failure, one success, two calls.",
    )

    ok(
        "A json-generation failure is retried and the second "
        "response is used"
    )


    # ------------------------------------------------------
    # Exhausted.
    # ------------------------------------------------------

    service, client = service_with(
        [
            json_generation_error()
            for _ in range(
                attempts + 4
            )
        ]
    )

    try:
        service.extract(
            OCR_LINES
        )

        raise AssertionError(
            (
                "Repeated formatting failures must not "
                "succeed."
            )
        )

    except RuntimeError as error:

        assert_true(
            "structured" in str(
                error
            ).lower()
            or "valid" in str(
                error
            ).lower(),
            (
                "The exhaustion error must say what was "
                "exhausted."
            ),
        )

    assert_equal(
        len(
            client.completions.calls
        ),
        attempts,
        (
            "Exactly the configured number of attempts. Not "
            "more: an unbounded formatting retry against a "
            "document the provider cannot format is a loop "
            "that burns quota to no end."
        ),
    )

    ok(
        f"Repeated formatting failures stop after exactly "
        f"{attempts} attempts"
    )


    # ------------------------------------------------------
    # AND THE EXHAUSTION IS PERMANENT TO THE JOB LAYER
    # ------------------------------------------------------

    verdict = classify(
        RuntimeError(
            "Groq failed to generate a valid structured "
            "document after 3 attempts."
        )
    )

    assert_equal(
        verdict.transient,
        False,
        (
            "Exhausted formatting recovery must be PERMANENT "
            "to the job layer.\n\n"
            "If it were transient, the job would retry, and "
            "each retry would spend another three formatting "
            "attempts on a document the provider has already "
            "failed to format three times -- which is exactly "
            "the retry multiplication this phase exists to "
            "prevent."
        ),
    )

    ok(
        "Exhausted formatting recovery classifies as "
        f"{verdict.code}, non-transient, so the job layer "
        "does not multiply it"
    )


def test_provider_errors_are_not_retried_here() -> None:

    section(
        "TEST 6 - PROVIDER FAILURES BELONG TO THE JOB LAYER"
    )

    for label, error in (
        (
            "rate limit",
            rate_limit_error(),
        ),
        (
            "connection",
            groq.APIConnectionError(
                request=httpx.Request(
                    "POST",
                    "https://api.groq.com/x",
                )
            ),
        ),
    ):

        service, client = service_with(
            [
                error,
                VALID_EXTRACTION,
            ]
        )

        try:
            service.extract(
                OCR_LINES
            )

            raise AssertionError(
                (
                    f"A {label} failure must propagate, not "
                    "be retried inside extraction."
                )
            )

        except Exception as raised:      # noqa: BLE001

            assert_true(
                raised is error,
                (
                    f"The original {label} error must reach "
                    "the caller unchanged, so the job "
                    "classifier can see its type and its "
                    "Retry-After. Wrapping it would hide "
                    "both.\n"
                    f"Got: {type(raised).__name__}"
                ),
            )

        assert_equal(
            len(
                client.completions.calls
            ),
            1,
            (
                f"A {label} failure must cost exactly one "
                "call from this layer. The SDK may have "
                "retried inside that call; this layer must "
                "not retry on top of it."
            ),
        )

        verdict = classify(
            error
        )

        assert_equal(
            verdict.transient,
            True,
            (
                f"And the job layer must see a {label} "
                "failure as transient, because it owns that "
                "recovery."
            ),
        )

        ok(
            f"A {label} failure propagates after 1 call and "
            f"the job layer classifies it {verdict.code} "
            "(transient)"
        )


def test_unrelated_bad_request_propagates() -> None:

    section(
        "TEST 7 - AN UNRELATED 400 IS NOT A FORMATTING RETRY"
    )

    request = httpx.Request(
        "POST",
        "https://api.groq.com/x",
    )

    unrelated = groq.BadRequestError(
        "Invalid value for max_completion_tokens.",
        response=httpx.Response(
            400,
            request=request,
            json={
                "error": {
                    "message": (
                        "Invalid value for "
                        "max_completion_tokens."
                    ),
                }
            },
        ),
        body=None,
    )

    service, client = service_with(
        [
            unrelated,
            VALID_EXTRACTION,
        ]
    )

    try:
        service.extract(
            OCR_LINES
        )

        raise AssertionError(
            (
                "A 400 that is not a JSON-generation failure "
                "must propagate immediately."
            )
        )

    except groq.BadRequestError as raised:

        assert_true(
            raised is unrelated,
            "Unchanged.",
        )

    assert_equal(
        len(
            client.completions.calls
        ),
        1,
        (
            "Retrying a malformed request would send the same "
            "malformed request again. The retry is for "
            "formatting failures the provider might recover "
            "from, not for our own bad parameters."
        ),
    )

    ok(
        "A 400 unrelated to JSON generation propagates after "
        "exactly 1 call"
    )


# ==========================================================
# 8. THE MODEL FALLBACK
# ==========================================================

def test_fallback_is_off_by_default() -> None:

    section(
        "TEST 8 - THE FALLBACK IS OFF UNLESS CONFIGURED"
    )

    service, client = service_with(
        [
            model_not_found_error(),
        ]
    )

    assert_true(
        service.fallback_model is None,
        "No fallback is configured.",
    )

    try:
        service.extract(
            OCR_LINES
        )

        raise AssertionError(
            (
                "With no fallback configured, a missing model "
                "must fail rather than silently trying "
                "something else."
            )
        )

    except groq.NotFoundError:
        pass

    assert_equal(
        len(
            client.completions.calls
        ),
        1,
        (
            "Exactly one call, to the configured model. There "
            "is no hidden second model."
        ),
    )

    ok(
        "With no fallback configured, a missing model fails "
        "after one call to the configured model"
    )


def test_fallback_is_narrow() -> None:

    section(
        "TEST 9 - THE FALLBACK ONLY FIRES ON A MISSING MODEL"
    )

    # ------------------------------------------------------
    # It fires when the model is gone.
    # ------------------------------------------------------

    service, client = service_with(
        [
            model_not_found_error(),
            VALID_EXTRACTION,
        ],
        model="primary/model",
        fallback_model="fallback/model",
    )

    result = service.extract(
        OCR_LINES
    )

    assert_equal(
        result.document_type,
        "guard_license",
        (
            "The fallback must produce a normal extraction."
        ),
    )

    models = [
        call["model"]
        for call in client.completions.calls
    ]

    assert_equal(
        models,
        [
            "primary/model",
            "fallback/model",
        ],
        (
            "The primary is tried first, then the fallback "
            "exactly once, in that order."
        ),
    )

    ok(
        "A retired model falls back to the configured "
        "alternative: "
        f"{' then '.join(models)}"
    )


    # ------------------------------------------------------
    # THE SCHEMA CONTRACT IS IDENTICAL
    # ------------------------------------------------------

    primary_call, fallback_call = (
        client.completions.calls
    )

    for field in (
        "messages",
        "response_format",
        "max_completion_tokens",
        "reasoning_effort",
    ):

        assert_equal(
            fallback_call[field],
            primary_call[field],
            (
                "The fallback request must be identical to "
                "the primary apart from the model. A "
                "different schema, prompt or token limit "
                f"would change extraction semantics. "
                f"Differed on: {field}"
            ),
        )

    assert_equal(
        fallback_call[
            "response_format"
        ]["json_schema"]["strict"],
        True,
        (
            "Strict structured output is not relaxed for the "
            "fallback."
        ),
    )

    ok(
        "The fallback request is byte-identical to the "
        "primary apart from the model, and strict schema "
        "enforcement is unchanged"
    )


    # ------------------------------------------------------
    # IT DOES NOT FIRE ON ANYTHING ELSE
    # ------------------------------------------------------

    for label, error in (
        (
            "rate limit",
            rate_limit_error(),
        ),
        (
            "connection",
            groq.APIConnectionError(
                request=httpx.Request(
                    "POST",
                    "https://api.groq.com/x",
                )
            ),
        ),
        (
            "json generation",
            json_generation_error(),
        ),
    ):

        service, client = service_with(
            [
                error,
                VALID_EXTRACTION,
            ],
            model="primary/model",
            fallback_model="fallback/model",
        )

        try:
            service.extract(
                OCR_LINES
            )

        except Exception:                # noqa: BLE001
            pass


        used = {
            call["model"]
            for call in client.completions.calls
        }

        assert_true(
            "fallback/model" not in used,
            (
                f"A {label} failure must NOT trigger the "
                "model fallback.\n\n"
                "Those are transient or formatting problems "
                "that have nothing to do with which model is "
                "being asked. Switching models because of a "
                "rate limit would change extraction "
                "semantics for an unrelated reason, and would "
                "mask the real problem from the job layer "
                "that owns it."
            ),
        )

        ok(
            f"A {label} failure does not switch models "
            f"(used: {sorted(used)})"
        )


def test_fallback_detection_is_specific() -> None:

    section(
        "TEST 10 - MISSING-MODEL DETECTION IS SPECIFIC"
    )

    request = httpx.Request(
        "POST",
        "https://api.groq.com/x",
    )

    other_404 = groq.NotFoundError(
        "Error code: 404 - Not Found",
        response=httpx.Response(
            404,
            request=request,
            json={
                "error": {
                    "message": "Not Found",
                }
            },
        ),
        body=None,
    )

    assert_equal(
        ExtractionService._is_model_unavailable(
            other_404
        ),
        False,
        (
            "A 404 that does not name the model is not a "
            "missing-model signal. Treating every 404 as one "
            "would switch models over an unrelated bad path."
        ),
    )

    assert_equal(
        ExtractionService._is_model_unavailable(
            model_not_found_error()
        ),
        True,
        (
            "A 404 whose body says model_not_found is."
        ),
    )

    assert_equal(
        ExtractionService._is_model_unavailable(
            rate_limit_error()
        ),
        False,
        "A 429 is not a missing model.",
    )

    ok(
        "Only a 404 naming the model counts; a bare 404 and a "
        "429 do not"
    )


# ==========================================================
# 11. NO SECOND RETRY LAYER CREPT IN
# ==========================================================

def test_no_hidden_retry_layers() -> None:

    section(
        "TEST 11 - NO HIDDEN RETRY LAYER"
    )

    source = inspect.getsource(
        extraction_module
    )

    # ------------------------------------------------------
    # THE COMPLETION HELPER MUST NOT LOOP
    # ------------------------------------------------------
    #
    # Checked against the parsed SYNTAX TREE, not the source
    # text.
    #
    # The first version of this rule searched for the string
    # "for " and tripped on the phrase "for this request"
    # inside a log message. A rule that reads prose as code
    # will keep doing that, and the usual reaction to a rule
    # that cries wolf is to delete it.
    #
    # The AST cannot be fooled by a comment or a string.
    # ------------------------------------------------------

    LOOP_NODES = (
        ast.For,
        ast.While,
        ast.AsyncFor,
    )

    helper_tree = ast.parse(
        textwrap.dedent(
            inspect.getsource(
                ExtractionService
                ._create_completion
            )
        )
    )

    loops = [
        type(
            node
        ).__name__
        for node in ast.walk(
            helper_tree
        )
        if isinstance(
            node,
            LOOP_NODES,
        )
    ]

    assert_equal(
        loops,
        [],
        (
            "_create_completion must contain no loop.\n\n"
            "It exists to make one request, with one optional "
            "fallback. A loop here would be a third retry "
            "layer, invisible to both call_budget and the job "
            "layer, and the documented budget would silently "
            "stop being true."
        ),
    )


    # And the detector has to be able to see a loop when there
    # is one, or it is decoration.
    detected = [
        type(
            node
        ).__name__
        for node in ast.walk(
            ast.parse(
                "def f():\n"
                "    for index in range(3):\n"
                "        pass\n"
            )
        )
        if isinstance(
            node,
            LOOP_NODES,
        )
    ]

    assert_equal(
        detected,
        [
            "For"
        ],
        (
            "The loop detector must actually detect a loop, "
            "or this assertion proves nothing."
        ),
    )

    ok(
        "_create_completion contains no loop, checked on the "
        "syntax tree, and the detector is proven able to see "
        "one"
    )


    # The budget must be computed, not written down.
    budget_source = inspect.getsource(
        ExtractionService.call_budget
    )

    for hard_coded in (
        "return 15",
        "return 27",
        "= 15\n",
    ):

        assert_true(
            hard_coded not in budget_source,
            (
                "The budget must be derived from the values "
                "in force, never a literal. A literal would "
                "keep reporting the old number after somebody "
                "changed a timeout."
            ),
        )

    service = ExtractionService(
        model="m",
    )

    service.max_retries = 5

    service.max_structured_output_attempts = 4

    adjusted = service.call_budget(
        job_attempts=2,
    )

    assert_equal(
        adjusted[
            "http_requests_per_document"
        ],
        (
            (4 - 1)
            + (1 + 5)
        )
        * 2,
        (
            "Changing the configuration must change the "
            "budget."
        ),
    )

    ok(
        "call_budget tracks the live configuration: altered "
        "settings produce "
        f"{adjusted['http_requests_per_document']} requests "
        "per document"
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
        "PHASE 10.4 - EXTRACTION RESILIENCE"
    )
    print(
        "=" * 74
    )

    test_configuration_is_explicit()
    test_configuration_from_environment()
    test_call_budget()
    test_call_budget_fits_lease()
    test_structured_output_retry_is_bounded()
    test_provider_errors_are_not_retried_here()
    test_unrelated_bad_request_propagates()
    test_fallback_is_off_by_default()
    test_fallback_is_narrow()
    test_fallback_detection_is_specific()
    test_no_hidden_retry_layers()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 10.4 EXTRACTION RESILIENCE TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
