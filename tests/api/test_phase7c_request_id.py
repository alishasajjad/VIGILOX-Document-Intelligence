import io
import json
import logging
import uuid

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
)

from backend.app.api.request_context import (
    REQUEST_ID_HEADER,
    sanitize_client_request_id,
)

from backend.app.core.logging import (
    LOGGER_ROOT_NAME,
    StructuredJSONFormatter,
)

from backend.app.services.reviewer_identity_service import (
    ReviewerIdentityService,
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


def assert_not_equal(
    actual,
    forbidden,
    message: str,
):

    if actual == forbidden:

        raise AssertionError(
            f"{message}\n"
            f"Forbidden value: {forbidden}"
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
# REQUEST ID FORMAT
# ==========================================================

def assert_valid_request_id(
    value,
    message: str,
):

    assert_true(
        isinstance(
            value,
            str,
        ),
        (
            f"{message} "
            "Request ID must be a string."
        ),
    )


    try:

        parsed = (
            uuid.UUID(
                value
            )
        )


    except (
        ValueError,
        AttributeError,
        TypeError,
    ) as exc:

        raise AssertionError(
            f"{message} "
            "Request ID is not a valid "
            f"UUID: {value!r}"
        ) from exc


    assert_equal(
        parsed.version,
        4,
        (
            f"{message} "
            "Request ID must be a uuid4 "
            "value."
        ),
    )


    assert_equal(
        str(
            parsed
        ),
        value,
        (
            f"{message} "
            "Request ID should be the "
            "canonical uuid4 string."
        ),
    )


# ==========================================================
# STRUCTURED LOG CAPTURE
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


    def find_event(
        self,
        event: str,
    ) -> dict | None:

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


            record = (
                json.loads(
                    stripped
                )
            )


            if (
                record.get(
                    "event"
                )
                == event
            ):

                return record


        return None


# ==========================================================
# TEST DOUBLES
# ==========================================================

PRIVATE_QUEUE_FAILURE = (
    "PRIVATE_REQUEST_ID_DB_FAILURE"
)


class FailingDocumentQueryService:
    """
    Forces the review-queue endpoint into its explicit
    domain APIError mapping.
    """

    def get_review_queue(
        self,
        *,
        priority=None,
        document_type=None,
    ):

        raise RuntimeError(
            PRIVATE_QUEUE_FAILURE
        )


class MalformedDocumentQueryService:
    """
    Returns a structurally invalid stored document.

    The endpoint reads:

        result["document"]["processing_status"]

    OUTSIDE its try/except block, so this produces a genuine
    UNHANDLED exception. That is the only path which reaches
    Starlette's ServerErrorMiddleware, which sits outside the
    correlation middleware.

    This is exactly the case where the request ID must still
    appear in both the response header and the error payload.
    """

    def get_document(
        self,
        document_id: str,
    ):

        return {
            "analysis":
                None,
        }


# ==========================================================
# TEST 1 — SUCCESS RESPONSE HEADER
# ==========================================================

def test_success_response_has_request_id(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - SUCCESS RESPONSE "
        "REQUEST ID HEADER"
    )
    print("-" * 76)


    response = (
        client.get(
            "/health"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Health check should return "
            "HTTP 200."
        ),
    )


    request_id = (
        response.headers.get(
            REQUEST_ID_HEADER
        )
    )


    assert_true(
        request_id is not None,
        (
            "Successful response is missing "
            f"the {REQUEST_ID_HEADER} header."
        ),
    )


    print(
        "[PASS] Success request receives "
        f"{REQUEST_ID_HEADER}"
    )


    # ======================================================
    # FORMAT
    # ======================================================

    assert_valid_request_id(
        request_id,
        (
            "Successful response header."
        ),
    )


    print(
        "[PASS] Request ID is a valid "
        "uuid4"
    )


    # ======================================================
    # SUCCESS BODY IS UNCHANGED
    # ======================================================
    #
    # The architecture deliberately keeps the correlation ID
    # in the response HEADER for successful requests instead
    # of mutating every existing success payload.
    # ======================================================

    body = (
        response.json()
    )


    assert_equal(
        body,
        {
            "status":
                "ok",

            "service":
                "vigilox-document-intelligence",

            "version":
                "0.1.0",
        },
        (
            "Existing success payloads must "
            "remain backward compatible."
        ),
    )


    print(
        "[PASS] Success payload remains "
        "backward compatible"
    )


# ==========================================================
# TEST 2 — UNIQUENESS
# ==========================================================

def test_request_ids_are_unique(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - REQUEST ID UNIQUENESS"
    )
    print("-" * 76)


    observed = []


    for _ in range(
        25
    ):

        response = (
            client.get(
                "/health"
            )
        )


        observed.append(
            response.headers.get(
                REQUEST_ID_HEADER
            )
        )


    assert_equal(
        len(
            set(
                observed
            )
        ),
        len(
            observed
        ),
        (
            "Each request must receive a "
            "distinct correlation ID."
        ),
    )


    print(
        "[PASS] Separate requests receive "
        "distinct request IDs"
    )


    # ======================================================
    # SINGLE HEADER VALUE
    # ======================================================

    raw_header_values = [
        header_value
        for (
            header_name,
            header_value,
        ) in response.headers.raw
        if (
            header_name.lower()
            == REQUEST_ID_HEADER
            .lower()
            .encode()
        )
    ]


    assert_equal(
        len(
            raw_header_values
        ),
        1,
        (
            "Exactly one authoritative "
            f"{REQUEST_ID_HEADER} header "
            "must be emitted."
        ),
    )


    print(
        "[PASS] Exactly one authoritative "
        "header emitted"
    )


# ==========================================================
# TEST 3 — HTTP 404
# ==========================================================

def test_not_found_request_id(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - HTTP 404 REQUEST ID"
    )
    print("-" * 76)


    response = (
        client.get(
            "/api/v1/definitely-not-a-route"
        )
    )


    assert_equal(
        response.status_code,
        404,
        (
            "Unknown route should return "
            "HTTP 404."
        ),
    )


    header_request_id = (
        response.headers.get(
            REQUEST_ID_HEADER
        )
    )


    payload_request_id = (
        response.json()[
            "error"
        ][
            "request_id"
        ]
    )


    assert_valid_request_id(
        header_request_id,
        "HTTP 404 header.",
    )


    assert_equal(
        payload_request_id,
        header_request_id,
        (
            "HTTP 404 response header and "
            "error.request_id must match."
        ),
    )


    print(
        "[PASS] HTTP 404 header matches "
        "error.request_id"
    )


# ==========================================================
# TEST 4 — VALIDATION 422
# ==========================================================

def test_validation_error_request_id(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - HTTP 422 REQUEST ID"
    )
    print("-" * 76)


    response = (
        client.post(
            "/api/v1/documents/analyze"
        )
    )


    assert_equal(
        response.status_code,
        422,
        (
            "Missing multipart file should "
            "return HTTP 422."
        ),
    )


    header_request_id = (
        response.headers.get(
            REQUEST_ID_HEADER
        )
    )


    payload_request_id = (
        response.json()[
            "error"
        ][
            "request_id"
        ]
    )


    assert_valid_request_id(
        header_request_id,
        "HTTP 422 header.",
    )


    assert_equal(
        payload_request_id,
        header_request_id,
        (
            "HTTP 422 response header and "
            "error.request_id must match."
        ),
    )


    print(
        "[PASS] HTTP 422 header matches "
        "error.request_id"
    )


# ==========================================================
# TEST 5 — DOMAIN API ERROR
# ==========================================================

def test_domain_api_error_request_id(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - DOMAIN APIError "
        "REQUEST ID"
    )
    print("-" * 76)


    response = (
        client.get(
            "/api/v1/reviews/queue"
            "?priority=NOT_A_PRIORITY"
        )
    )


    assert_equal(
        response.status_code,
        400,
        (
            "Invalid priority should return "
            "HTTP 400."
        ),
    )


    body = (
        response.json()
    )


    assert_equal(
        body[
            "error"
        ][
            "code"
        ],
        "INVALID_REVIEW_PRIORITY",
        (
            "Domain error code should remain "
            "the precise Phase 7C.7c code."
        ),
    )


    header_request_id = (
        response.headers.get(
            REQUEST_ID_HEADER
        )
    )


    assert_valid_request_id(
        header_request_id,
        "Domain APIError header.",
    )


    assert_equal(
        body[
            "error"
        ][
            "request_id"
        ],
        header_request_id,
        (
            "Domain APIError header and "
            "error.request_id must match."
        ),
    )


    print(
        "[PASS] Domain APIError header "
        "matches error.request_id"
    )


    # ======================================================
    # AUTHENTICATION ERROR PATH
    # ======================================================

    original_reviewer_identity = (
        getattr(
            app.state,
            "reviewer_identity",
            None,
        )
    )


    try:

        app.state.reviewer_identity = (
            ReviewerIdentityService(
                mode="trusted_headers"
            )
        )


        response = (
            client.get(
                "/api/v1/reviewer/me"
            )
        )


        assert_equal(
            response.status_code,
            401,
            (
                "Missing reviewer identity "
                "should return HTTP 401."
            ),
        )


        body = (
            response.json()
        )


        header_request_id = (
            response.headers.get(
                REQUEST_ID_HEADER
            )
        )


        assert_valid_request_id(
            header_request_id,
            "HTTP 401 header.",
        )


        assert_equal(
            body[
                "error"
            ][
                "request_id"
            ],
            header_request_id,
            (
                "HTTP 401 header and "
                "error.request_id must match."
            ),
        )


        print(
            "[PASS] HTTP 401 header matches "
            "error.request_id"
        )


    finally:

        if (
            original_reviewer_identity
            is not None
        ):

            app.state.reviewer_identity = (
                original_reviewer_identity
            )


# ==========================================================
# TEST 6 — UNEXPECTED HTTP 500
# ==========================================================

def test_unhandled_error_request_id(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - UNEXPECTED HTTP 500 "
        "REQUEST ID"
    )
    print("-" * 76)


    original_document_query = (
        getattr(
            app.state,
            "document_query",
            None,
        )
    )


    try:

        app.state.document_query = (
            MalformedDocumentQueryService()
        )


        with StructuredLogCapture() as capture:

            response = (
                client.get(
                    "/api/v1/documents/"
                    "malformed-document"
                )
            )


            log_record = (
                capture.find_event(
                    "unhandled_api_exception"
                )
            )


        assert_equal(
            response.status_code,
            500,
            (
                "An unhandled endpoint "
                "exception should return "
                "HTTP 500."
            ),
        )


        body = (
            response.json()
        )


        assert_equal(
            body[
                "error"
            ][
                "code"
            ],
            "INTERNAL_SERVER_ERROR",
            (
                "Unhandled exceptions should "
                "use the generic internal "
                "error code."
            ),
        )


        header_request_id = (
            response.headers.get(
                REQUEST_ID_HEADER
            )
        )


        assert_valid_request_id(
            header_request_id,
            (
                "Unhandled HTTP 500 header."
            ),
        )


        assert_equal(
            body[
                "error"
            ][
                "request_id"
            ],
            header_request_id,
            (
                "Unhandled HTTP 500 header "
                "and error.request_id must "
                "match. ServerErrorMiddleware "
                "runs outside the correlation "
                "middleware, so the error "
                "handler must attach the "
                "header itself."
            ),
        )


        print(
            "[PASS] Unhandled HTTP 500 header "
            "matches error.request_id"
        )


        # ==============================================
        # STRUCTURED LOG CORRELATION
        # ==============================================

        assert_true(
            log_record is not None,
            (
                "Unhandled exception should "
                "emit a structured "
                "unhandled_api_exception "
                "event."
            ),
        )


        assert_equal(
            log_record[
                "request_id"
            ],
            header_request_id,
            (
                "Structured operational log "
                "must use the same request "
                "ID as the response."
            ),
        )


        print(
            "[PASS] Unhandled exception log "
            "shares the same request ID"
        )


        # ==============================================
        # NO TRACE LEAK
        # ==============================================

        assert_true(
            "Traceback"
            not in json.dumps(
                body
            ),
            (
                "Stack trace leaked into the "
                "HTTP 500 response."
            ),
        )


        print(
            "[PASS] HTTP 500 response remains "
            "sanitized"
        )


    finally:

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


# ==========================================================
# TEST 7 — LOG / RESPONSE CORRELATION
# ==========================================================

def test_log_shares_request_id(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - OPERATIONAL LOG "
        "CORRELATION"
    )
    print("-" * 76)


    original_document_query = (
        getattr(
            app.state,
            "document_query",
            None,
        )
    )


    try:

        app.state.document_query = (
            FailingDocumentQueryService()
        )


        with StructuredLogCapture() as capture:

            response = (
                client.get(
                    "/api/v1/reviews/queue"
                )
            )


            log_record = (
                capture.find_event(
                    "review_queue_load_failed"
                )
            )


        header_request_id = (
            response.headers.get(
                REQUEST_ID_HEADER
            )
        )


        assert_valid_request_id(
            header_request_id,
            "Domain HTTP 500 header.",
        )


        assert_true(
            log_record is not None,
            (
                "Review queue failure should "
                "emit a structured event."
            ),
        )


        assert_equal(
            log_record[
                "request_id"
            ],
            header_request_id,
            (
                "Structured operational log "
                "must share the response "
                "request ID."
            ),
        )


        print(
            "[PASS] Structured log shares "
            "the response request ID"
        )


        assert_equal(
            response.json()[
                "error"
            ][
                "request_id"
            ],
            header_request_id,
            (
                "Error payload must share the "
                "same request ID."
            ),
        )


        print(
            "[PASS] Response, error payload "
            "and log share one request ID"
        )


    finally:

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


# ==========================================================
# TEST 8 — CLIENT CANNOT SPOOF
# ==========================================================

def test_client_cannot_spoof_request_id(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - CLIENT SPOOFING "
        "PREVENTION"
    )
    print("-" * 76)


    spoofed_value = (
        "CLIENT-SPOOFED-REQUEST-ID"
    )


    # ======================================================
    # SUCCESS PATH
    # ======================================================

    response = (
        client.get(
            "/health",

            headers={
                REQUEST_ID_HEADER:
                    spoofed_value,
            },
        )
    )


    header_request_id = (
        response.headers.get(
            REQUEST_ID_HEADER
        )
    )


    assert_not_equal(
        header_request_id,
        spoofed_value,
        (
            "The client must not be able to "
            "dictate the authoritative "
            "request ID."
        ),
    )


    assert_valid_request_id(
        header_request_id,
        "Spoof attempt success path.",
    )


    print(
        "[PASS] Client header does not "
        "become the authoritative ID"
    )


    # ======================================================
    # ERROR PATH
    # ======================================================

    response = (
        client.get(
            "/api/v1/definitely-not-a-route",

            headers={
                REQUEST_ID_HEADER:
                    spoofed_value,
            },
        )
    )


    body = (
        response.json()
    )


    assert_not_equal(
        body[
            "error"
        ][
            "request_id"
        ],
        spoofed_value,
        (
            "A spoofed client header must not "
            "reach error.request_id."
        ),
    )


    assert_equal(
        body[
            "error"
        ][
            "request_id"
        ],
        response.headers.get(
            REQUEST_ID_HEADER
        ),
        (
            "Header and payload must still "
            "agree while a spoof attempt is "
            "present."
        ),
    )


    assert_valid_request_id(
        body[
            "error"
        ][
            "request_id"
        ],
        "Spoof attempt error path.",
    )


    print(
        "[PASS] Spoofed value never reaches "
        "error.request_id"
    )


    # ======================================================
    # HEADER INJECTION / LOG FORGING DEFENCE
    # ======================================================

    for hostile_value in (
        "abc\r\nX-Injected: 1",
        "value with spaces",
        "x" * 500,
        "",
        "   ",
        "a;b|c",
    ):

        assert_equal(
            sanitize_client_request_id(
                hostile_value
            ),
            None,
            (
                "Hostile client tracing ID "
                "should be rejected: "
                f"{hostile_value!r}"
            ),
        )


    print(
        "[PASS] Hostile client tracing "
        "values rejected"
    )


    # ======================================================
    # WELL-FORMED CLIENT TRACING ID IS RETAINED SEPARATELY
    # ======================================================

    assert_equal(
        sanitize_client_request_id(
            "upstream-trace-123"
        ),
        "upstream-trace-123",
        (
            "A well-formed client tracing ID "
            "should still be retained as a "
            "non-authoritative value."
        ),
    )


    print(
        "[PASS] Well-formed client tracing "
        "ID kept non-authoritative"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7e - CORRELATION / "
        "REQUEST ID TEST"
    )
    print("=" * 76)


    client = None


    try:

        client = TestClient(
            app,
            raise_server_exceptions=False,
        )


        test_success_response_has_request_id(
            client
        )

        test_request_ids_are_unique(
            client
        )

        test_not_found_request_id(
            client
        )

        test_validation_error_request_id(
            client
        )

        test_domain_api_error_request_id(
            client
        )

        test_unhandled_error_request_id(
            client
        )

        test_log_shares_request_id(
            client
        )

        test_client_cannot_spoof_request_id(
            client
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.7e CORRELATION "
            "/ REQUEST ID TEST PASSED"
        )
        print("=" * 76)


    finally:

        if client is not None:

            client.close()


        print()
        print(
            "[CLEANUP] Phase 7C.7e "
            "temporary API state removed."
        )


if __name__ == "__main__":

    main()
