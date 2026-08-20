import io
import json
import logging

from fastapi.testclient import (
    TestClient,
)

from src.api.main import (
    app,
)

from src.operational_logging import (
    LOGGER_ROOT_NAME,
    STRUCTURED_FIELDS,
    StructuredJSONFormatter,
    configure_operational_logging,
    get_operational_logger,
    log_event,
    log_exception,
)


# ==========================================================
# ASSERT HELPERS
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
):

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


def assert_true(
    condition: bool,
    message: str,
):

    if not condition:

        raise AssertionError(
            message
        )


# ==========================================================
# LOG CAPTURE
# ==========================================================
#
# Captures structured records emitted by the real
# "vigilox" logger hierarchy using the real production
# StructuredJSONFormatter.
#
# This verifies the actual serialized operational output
# rather than a test-only reimplementation.
# ==========================================================

class StructuredLogCapture:

    def __init__(
        self,
    ):

        self.stream = (
            io.StringIO()
        )


        self.handler = (
            logging.StreamHandler(
                self.stream
            )
        )


        self.handler.setFormatter(
            StructuredJSONFormatter()
        )


        self.root_logger = (
            logging.getLogger(
                LOGGER_ROOT_NAME
            )
        )


        self.previous_level = (
            self.root_logger.level
        )


    def __enter__(
        self,
    ):

        self.root_logger.addHandler(
            self.handler
        )


        # Ensure DEBUG-level events are also captured
        # regardless of VIGILOX_LOG_LEVEL.

        self.root_logger.setLevel(
            logging.DEBUG
        )


        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):

        self.root_logger.removeHandler(
            self.handler
        )


        self.root_logger.setLevel(
            self.previous_level
        )


        return False


    # ======================================================
    # PARSED STRUCTURED RECORDS
    # ======================================================

    def records(
        self,
    ) -> list[dict]:

        parsed = []


        for line in (
            self.stream
            .getvalue()
            .splitlines()
        ):

            stripped = (
                line.strip()
            )


            if not stripped:

                continue


            # Any non-JSON line is a structured logging
            # contract violation.

            parsed.append(
                json.loads(
                    stripped
                )
            )


        return parsed


    def find_event(
        self,
        event: str,
    ) -> dict | None:

        for record in (
            self.records()
        ):

            if (
                record.get(
                    "event"
                )
                == event
            ):

                return record


        return None


# ==========================================================
# FAILING QUERY SERVICE
# ==========================================================

PRIVATE_QUEUE_FAILURE = (
    "PRIVATE_LOGGING_DB_FAILURE_"
    "MUST_NOT_LEAK"
)


class FailingDocumentQueryService:

    def get_review_queue(
        self,
        *,
        priority=None,
        document_type=None,
    ):

        raise RuntimeError(
            PRIVATE_QUEUE_FAILURE
        )


# ==========================================================
# TEST 1 — STRUCTURED EVENT SERIALIZATION
# ==========================================================

def test_structured_event_serialization():

    print()
    print("-" * 76)
    print(
        "TEST 1 - STRUCTURED EVENT "
        "JSON SERIALIZATION"
    )
    print("-" * 76)


    logger = (
        get_operational_logger(
            "test.events"
        )
    )


    with StructuredLogCapture() as capture:

        log_event(
            logger,

            event=(
                "structured_logging_probe"
            ),

            message=(
                "Structured logging probe."
            ),

            request_id=(
                "req-1234"
            ),

            document_id=(
                "doc-5678"
            ),

            reviewer_id=(
                "reviewer-1"
            ),

            status_code=200,

            error_code=(
                "NONE"
            ),
        )


        records = (
            capture.records()
        )


    # ======================================================
    # VALID JSON
    # ======================================================

    assert_equal(
        len(
            records
        ),
        1,
        (
            "Exactly one structured log "
            "record should be emitted."
        ),
    )


    print(
        "[PASS] Structured event log "
        "serialized as valid JSON"
    )


    record = (
        records[
            0
        ]
    )


    # ======================================================
    # REQUIRED FIELDS
    # ======================================================

    for required_field in (
        "timestamp",
        "level",
        "logger",
        "event",
        "message",
    ):

        assert_true(
            required_field
            in record,
            (
                "Required structured field "
                f"is missing: {required_field}"
            ),
        )


    assert_equal(
        record[
            "event"
        ],
        "structured_logging_probe",
        (
            "Structured event name "
            "is incorrect."
        ),
    )


    assert_equal(
        record[
            "level"
        ],
        "INFO",
        (
            "Structured log level "
            "is incorrect."
        ),
    )


    assert_equal(
        record[
            "logger"
        ],
        f"{LOGGER_ROOT_NAME}.test.events",
        (
            "Structured logger name should "
            "live under the vigilox "
            "hierarchy."
        ),
    )


    print(
        "[PASS] Required structured "
        "fields present"
    )


    # ======================================================
    # OPTIONAL CONTEXT
    # ======================================================

    assert_equal(
        record[
            "request_id"
        ],
        "req-1234",
        (
            "request_id context missing."
        ),
    )


    assert_equal(
        record[
            "document_id"
        ],
        "doc-5678",
        (
            "document_id context missing."
        ),
    )


    assert_equal(
        record[
            "reviewer_id"
        ],
        "reviewer-1",
        (
            "reviewer_id context missing."
        ),
    )


    assert_equal(
        record[
            "status_code"
        ],
        200,
        (
            "status_code context missing."
        ),
    )


    print(
        "[PASS] Structured context "
        "fields included"
    )


    # ======================================================
    # UNSET OPTIONAL FIELDS OMITTED
    # ======================================================

    assert_true(
        "error_type"
        not in record,
        (
            "Unset optional fields should "
            "be omitted rather than "
            "serialized as null."
        ),
    )


    print(
        "[PASS] Unset optional fields "
        "omitted from payload"
    )


# ==========================================================
# TEST 2 — EXCEPTION LOGGING
# ==========================================================

def test_exception_logging_includes_error_type():

    print()
    print("-" * 76)
    print(
        "TEST 2 - EXCEPTION LOGGING "
        "AND SERVER-SIDE TRACE"
    )
    print("-" * 76)


    logger = (
        get_operational_logger(
            "test.exceptions"
        )
    )


    private_message = (
        "PRIVATE_TRACE_ONLY_SERVER_SIDE"
    )


    with StructuredLogCapture() as capture:

        try:

            raise ValueError(
                private_message
            )


        except ValueError as exc:

            log_exception(
                logger,

                event=(
                    "document_query_failed"
                ),

                message=(
                    "Failed to load document."
                ),

                exc=exc,

                document_id=(
                    "doc-error-1"
                ),

                status_code=500,

                error_code=(
                    "DOCUMENT_QUERY_FAILED"
                ),
            )


        record = (
            capture.find_event(
                "document_query_failed"
            )
        )


    assert_true(
        record is not None,
        (
            "Structured exception event "
            "was not emitted."
        ),
    )


    # ======================================================
    # ERROR TYPE
    # ======================================================

    assert_equal(
        record[
            "error_type"
        ],
        "ValueError",
        (
            "Exception logging should "
            "include error_type."
        ),
    )


    print(
        "[PASS] Exception log includes "
        "error_type"
    )


    assert_equal(
        record[
            "error_code"
        ],
        "DOCUMENT_QUERY_FAILED",
        (
            "Exception logging should "
            "include the stable API "
            "error code."
        ),
    )


    assert_equal(
        record[
            "level"
        ],
        "ERROR",
        (
            "Exception logging should use "
            "ERROR level."
        ),
    )


    print(
        "[PASS] Exception log includes "
        "stable error_code"
    )


    # ======================================================
    # SERVER-SIDE TRACE IS ALLOWED
    # ======================================================

    assert_true(
        "exception"
        in record,
        (
            "Server-side exception trace "
            "should be available in "
            "operational logs."
        ),
    )


    assert_true(
        private_message
        in record[
            "exception"
        ],
        (
            "Server-side trace should "
            "retain the real exception "
            "information."
        ),
    )


    assert_true(
        private_message
        not in record[
            "message"
        ],
        (
            "The safe log message should "
            "not embed raw internal "
            "exception text."
        ),
    )


    print(
        "[PASS] Server-side exception "
        "trace logged"
    )


# ==========================================================
# TEST 3 — CONTEXT ALLOWLIST
# ==========================================================

def test_context_allowlist():

    print()
    print("-" * 76)
    print(
        "TEST 3 - LOGGING CONTEXT "
        "ALLOWLIST"
    )
    print("-" * 76)


    logger = (
        get_operational_logger(
            "test.allowlist"
        )
    )


    # ======================================================
    # ATTEMPT TO SMUGGLE SENSITIVE CONTEXT
    # ======================================================
    #
    # Even if a caller mistakenly attaches sensitive data
    # to a log record, the structured formatter must only
    # serialize allowlisted operational fields.
    # ======================================================

    forbidden_values = {
        "authorization":
            "Bearer SECRET_TOKEN_VALUE",

        "groq_api_key":
            "gsk_SECRET_API_KEY_VALUE",

        "database_url":
            (
                "postgresql://user:"
                "SECRET_PASSWORD@host/db"
            ),

        "request_body":
            "SECRET_REQUEST_BODY_CONTENT",

        "document_bytes":
            "SECRET_DOCUMENT_IMAGE_BYTES",
    }


    with StructuredLogCapture() as capture:

        logger.info(
            "Allowlist probe.",

            extra={
                "event":
                    "allowlist_probe",

                "document_id":
                    "doc-allowlist",

                **forbidden_values,
            },
        )


        records = (
            capture.records()
        )


    record = (
        records[
            0
        ]
    )


    serialized = (
        json.dumps(
            record
        )
    )


    # ======================================================
    # FORBIDDEN KEYS AND VALUES ABSENT
    # ======================================================

    for (
        forbidden_key,
        forbidden_value,
    ) in forbidden_values.items():

        assert_true(
            forbidden_key
            not in record,
            (
                "Non-allowlisted context key "
                "leaked into structured log: "
                f"{forbidden_key}"
            ),
        )


        assert_true(
            forbidden_value
            not in serialized,
            (
                "Sensitive context value "
                "leaked into structured log: "
                f"{forbidden_key}"
            ),
        )


    print(
        "[PASS] Secret / auth / request-body "
        "fields not auto-included"
    )


    # ======================================================
    # ALLOWLISTED FIELDS STILL WORK
    # ======================================================

    assert_equal(
        record[
            "document_id"
        ],
        "doc-allowlist",
        (
            "Allowlisted context should "
            "still be serialized."
        ),
    )


    permitted_keys = (
        {
            "timestamp",
            "level",
            "logger",
            "message",
            "exception",
        }
        | set(
            STRUCTURED_FIELDS
        )
    )


    for present_key in (
        record.keys()
    ):

        assert_true(
            present_key
            in permitted_keys,
            (
                "Structured log emitted a "
                "field outside the allowlist: "
                f"{present_key}"
            ),
        )


    print(
        "[PASS] Structured payload "
        "restricted to allowlist"
    )


# ==========================================================
# TEST 4 — IDEMPOTENT CONFIGURATION
# ==========================================================

def test_idempotent_logging_configuration():

    print()
    print("-" * 76)
    print(
        "TEST 4 - IDEMPOTENT LOGGING "
        "CONFIGURATION"
    )
    print("-" * 76)


    root_logger = (
        logging.getLogger(
            LOGGER_ROOT_NAME
        )
    )


    handler_count_before = (
        len(
            root_logger.handlers
        )
    )


    # ======================================================
    # REPEATED CONFIGURATION
    # ======================================================

    for _ in range(
        5
    ):

        configure_operational_logging()


    handler_count_after = (
        len(
            root_logger.handlers
        )
    )


    assert_equal(
        handler_count_after,
        handler_count_before,
        (
            "Repeated logging configuration "
            "must not create duplicate "
            "handlers."
        ),
    )


    print(
        "[PASS] Repeated configuration "
        "creates no duplicate handlers"
    )


    # ======================================================
    # REPEATED TESTCLIENT CONSTRUCTION
    # ======================================================

    for _ in range(
        3
    ):

        with TestClient(
            app,
            raise_server_exceptions=False,
        ) as client:

            response = (
                client.get(
                    "/health"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Health check should "
                    "remain available."
                ),
            )


    assert_equal(
        len(
            root_logger.handlers
        ),
        handler_count_before,
        (
            "Repeated TestClient use must "
            "not create duplicate handlers."
        ),
    )


    print(
        "[PASS] Repeated TestClient use "
        "creates no duplicate handlers"
    )


    # ======================================================
    # SINGLE EMISSION PER EVENT
    # ======================================================
    #
    # Duplicate handlers would surface as duplicated
    # structured records.
    # ======================================================

    logger = (
        get_operational_logger(
            "test.idempotent"
        )
    )


    with StructuredLogCapture() as capture:

        log_event(
            logger,

            event=(
                "idempotent_probe"
            ),

            message=(
                "Idempotent probe."
            ),
        )


        records = (
            capture.records()
        )


    assert_equal(
        len(
            records
        ),
        1,
        (
            "A single structured event must "
            "produce exactly one record."
        ),
    )


    print(
        "[PASS] Single event produces "
        "exactly one record"
    )


# ==========================================================
# TEST 5 — API INTERNAL ERROR LOGGING + SANITIZATION
# ==========================================================

def test_api_internal_error_logging():

    print()
    print("-" * 76)
    print(
        "TEST 5 - API INTERNAL ERROR "
        "LOGGING AND SANITIZATION"
    )
    print("-" * 76)


    original_document_query = (
        getattr(
            app.state,
            "document_query",
            None,
        )
    )


    client = None


    try:

        client = TestClient(
            app,
            raise_server_exceptions=False,
        )


        app.state.document_query = (
            FailingDocumentQueryService()
        )


        with StructuredLogCapture() as capture:

            response = (
                client.get(
                    "/api/v1/reviews/queue"
                )
            )


            record = (
                capture.find_event(
                    "review_queue_load_failed"
                )
            )


        # ==============================================
        # OPERATIONAL LOG EMITTED
        # ==============================================

        assert_true(
            record is not None,
            (
                "Review queue failure should "
                "emit a structured "
                "review_queue_load_failed "
                "event."
            ),
        )


        print(
            "[PASS] Operational log event "
            "emitted for API failure"
        )


        assert_equal(
            record[
                "error_code"
            ],
            "REVIEW_QUEUE_LOAD_FAILED",
            (
                "Operational log should carry "
                "the stable API error code."
            ),
        )


        assert_equal(
            record[
                "status_code"
            ],
            500,
            (
                "Operational log should carry "
                "the HTTP status code."
            ),
        )


        assert_equal(
            record[
                "error_type"
            ],
            "RuntimeError",
            (
                "Operational log should carry "
                "the exception type."
            ),
        )


        print(
            "[PASS] Log event carries "
            "expected event / error_code"
        )


        # ==============================================
        # SERVER-SIDE TRACE PRESENT
        # ==============================================

        assert_true(
            PRIVATE_QUEUE_FAILURE
            in record[
                "exception"
            ],
            (
                "Server-side operational log "
                "should retain the private "
                "exception trace."
            ),
        )


        print(
            "[PASS] Private exception trace "
            "retained server-side"
        )


        # ==============================================
        # CLIENT RESPONSE SANITIZED
        # ==============================================

        assert_equal(
            response.status_code,
            500,
            (
                "Review queue failure should "
                "return HTTP 500."
            ),
        )


        body = (
            response.json()
        )


        serialized_body = (
            json.dumps(
                body
            )
        )


        assert_true(
            PRIVATE_QUEUE_FAILURE
            not in serialized_body,
            (
                "Private exception detail "
                "leaked into the API "
                "response."
            ),
        )


        assert_true(
            "Traceback"
            not in serialized_body,
            (
                "Stack trace leaked into "
                "the API response."
            ),
        )


        assert_equal(
            body[
                "error"
            ][
                "code"
            ],
            "REVIEW_QUEUE_LOAD_FAILED",
            (
                "API response should expose "
                "the stable domain error "
                "code."
            ),
        )


        print(
            "[PASS] API response remains "
            "sanitized"
        )


    finally:

        if client is not None:

            client.close()


        if (
            original_document_query
            is not None
        ):

            app.state.document_query = (
                original_document_query
            )


        elif hasattr(
            app.state,
            "document_query",
        ):

            delattr(
                app.state,
                "document_query",
            )


        print()
        print(
            "[CLEANUP] Phase 7C.7d "
            "temporary API state removed."
        )


# ==========================================================
# TEST 6 — NO OPERATIONAL PRINTS IN PRODUCTION SOURCE
# ==========================================================

def test_no_operational_prints_in_source():

    print()
    print("-" * 76)
    print(
        "TEST 6 - PRODUCTION SOURCE "
        "PRINT SCAN"
    )
    print("-" * 76)


    from pathlib import Path


    source_root = (
        Path(
            __file__
        )
        .resolve()
        .parent
        / "src"
    )


    offending = []


    for python_file in sorted(
        source_root.rglob(
            "*.py"
        )
    ):

        for (
            line_number,
            line,
        ) in enumerate(
            python_file
            .read_text(
                encoding="utf-8"
            )
            .splitlines(),
            start=1,
        ):

            stripped = (
                line.strip()
            )


            if (
                stripped.startswith(
                    "print("
                )
                or stripped.startswith(
                    "print ("
                )
            ):

                offending.append(
                    f"{python_file.name}:"
                    f"{line_number}"
                )


    assert_equal(
        offending,
        [],
        (
            "Operational print() calls "
            "remain in production source. "
            "Use structured operational "
            "logging instead."
        ),
    )


    print(
        "[PASS] No print() based "
        "operational logging in src/"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7d - STRUCTURED "
        "OPERATIONAL LOGGING TEST"
    )
    print("=" * 76)


    test_structured_event_serialization()

    test_exception_logging_includes_error_type()

    test_context_allowlist()

    test_idempotent_logging_configuration()

    test_api_internal_error_logging()

    test_no_operational_prints_in_source()


    print()
    print("=" * 76)
    print(
        "[PASS] PHASE 7C.7d STRUCTURED "
        "OPERATIONAL LOGGING TEST PASSED"
    )
    print("=" * 76)


if __name__ == "__main__":

    main()
