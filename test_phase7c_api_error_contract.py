from fastapi.testclient import (
    TestClient,
)

from src.api.main import (
    app,
)

from src.reviewer_identity_service import (
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


def assert_true(
    condition: bool,
    message: str,
):

    if not condition:

        raise AssertionError(
            message
        )


# ==========================================================
# ERROR CONTRACT ASSERTION
# ==========================================================

def assert_error_contract(
    response,
    *,
    expected_status: int,
    expected_code: str,
):

    assert_equal(
        response.status_code,
        expected_status,
        (
            "Unexpected HTTP status."
        ),
    )


    body = (
        response.json()
    )


    assert_equal(
        body[
            "status"
        ],
        "error",
        (
            "Error response should expose "
            "status=error."
        ),
    )


    assert_true(
        "detail"
        in body,
        (
            "Backward-compatible detail "
            "field is missing."
        ),
    )


    assert_true(
        "error"
        in body,
        (
            "Structured error object "
            "is missing."
        ),
    )


    error = (
        body[
            "error"
        ]
    )


    assert_equal(
        error[
            "code"
        ],
        expected_code,
        (
            "Unexpected structured "
            "error code."
        ),
    )


    assert_true(
        isinstance(
            error[
                "message"
            ],
            str,
        )
        and bool(
            error[
                "message"
            ]
        ),
        (
            "Error message should be "
            "a non-empty string."
        ),
    )


    assert_true(
        "request_id"
        in error,
        (
            "Error contract should expose "
            "request_id placeholder."
        ),
    )


# ==========================================================
# FAILING QUERY SERVICE
# ==========================================================

class FailingDocumentQueryService:

    def get_review_queue(
        self,
        *,
        priority=None,
        document_type=None,
    ):

        raise RuntimeError(
            (
                "SECRET INTERNAL DATABASE "
                "FAILURE SHOULD NOT LEAK"
            )
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7a — CENTRAL "
        "API ERROR CONTRACT TEST"
    )
    print("=" * 76)


    client = None


    original_document_query = (
        getattr(
            app.state,
            "document_query",
            None,
        )
    )


    original_reviewer_identity = (
        getattr(
            app.state,
            "reviewer_identity",
            None,
        )
    )


    try:

        # ==================================================
        # TEST CLIENT
        # ==================================================
        #
        # raise_server_exceptions=False is required so the
        # test can inspect our production-safe HTTP 500
        # response rather than having TestClient re-raise
        # the internal Python exception.
        # ==================================================

        client = TestClient(
            app,
            raise_server_exceptions=False,
        )


        # ==================================================
        # TEST 1 — HTTP 404
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — HTTP 404 CONTRACT"
        )
        print("-" * 76)


        response = (
            client.get(
                (
                    "/api/v1/"
                    "definitely-does-not-exist"
                )
            )
        )


        assert_error_contract(
            response,

            expected_status=404,

            expected_code=(
                "NOT_FOUND"
            ),
        )


        print(
            "[PASS] HTTP 404 uses "
            "central error contract"
        )


        # ==================================================
        # TEST 2 — APPLICATION HTTP 400
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — APPLICATION "
            "HTTP 400 CONTRACT"
        )
        print("-" * 76)


        response = (
            client.get(
                (
                    "/api/v1/reviews/queue"
                    "?priority=INVALID"
                )
            )
        )


        # ==================================================
        # PHASE 7C.7c CONTRACT EVOLUTION
        # ==================================================
        #
        # Phase 7C.7a returned the generic code:
        #
        #     BAD_REQUEST
        #
        # Phase 7C.7c intentionally replaced that with a
        # precise, stable domain code:
        #
        #     INVALID_REVIEW_PRIORITY
        #
        # The generic expectation below was migrated rather
        # than reverting the production error contract.
        # ==================================================

        assert_error_contract(
            response,

            expected_status=400,

            expected_code=(
                "INVALID_REVIEW_PRIORITY"
            ),
        )


        body = (
            response.json()
        )


        assert_equal(
            body[
                "detail"
            ],
            (
                "Invalid priority. "
                "Allowed values are "
                "HIGH, MEDIUM and LOW."
            ),
            (
                "Existing HTTPException "
                "detail should remain "
                "backward compatible."
            ),
        )


        print(
            "[PASS] Existing HTTPException "
            "detail preserved"
        )

        print(
            "[PASS] HTTP 400 exposes "
            "structured error code"
        )


        # ==================================================
        # TEST 3 — REQUEST VALIDATION 422
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 3 — REQUEST VALIDATION "
            "HTTP 422 CONTRACT"
        )
        print("-" * 76)


        response = (
            client.post(
                "/api/v1/documents/analyze"
            )
        )


        assert_error_contract(
            response,

            expected_status=422,

            expected_code=(
                "REQUEST_VALIDATION_ERROR"
            ),
        )


        body = (
            response.json()
        )


        assert_true(
            isinstance(
                body[
                    "detail"
                ],
                list,
            ),
            (
                "Validation detail should "
                "remain FastAPI-compatible "
                "as a list."
            ),
        )


        assert_true(
            "details"
            in body[
                "error"
            ],
            (
                "Structured validation "
                "details are missing."
            ),
        )


        assert_true(
            "validation_errors"
            in body[
                "error"
            ][
                "details"
            ],
            (
                "Validation errors are "
                "missing from structured "
                "error details."
            ),
        )


        print(
            "[PASS] Request validation "
            "uses central error contract"
        )

        print(
            "[PASS] Validation details "
            "preserved"
        )


        # ==================================================
        # TEST 4 — AUTHENTICATION ERROR 401
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 4 — AUTHENTICATION "
            "HTTP 401 CONTRACT"
        )
        print("-" * 76)


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


        # ==================================================
        # PHASE 7C.7c CONTRACT EVOLUTION
        # ==================================================
        #
        # Reviewer authentication failures now use the
        # reviewer-specific domain code introduced with the
        # Phase 7C.5 trust boundary.
        # ==================================================

        assert_error_contract(
            response,

            expected_status=401,

            expected_code=(
                "REVIEWER_AUTHENTICATION_REQUIRED"
            ),
        )


        print(
            "[PASS] Authentication failure "
            "uses central error contract"
        )


        # ==================================================
        # TEST 5 — INTERNAL SERVER ERROR
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 5 — INTERNAL SERVER "
            "ERROR SANITIZATION"
        )
        print("-" * 76)


        app.state.document_query = (
            FailingDocumentQueryService()
        )


        response = (
            client.get(
                "/api/v1/reviews/queue"
            )
        )


        # ==================================================
        # PHASE 7C.7c CONTRACT EVOLUTION
        # ==================================================
        #
        # The endpoint now maps an unexpected review-queue
        # failure to an explicit domain code instead of the
        # generic INTERNAL_SERVER_ERROR.
        #
        # The client-facing message stays sanitized, which
        # is asserted below.
        # ==================================================

        assert_error_contract(
            response,

            expected_status=500,

            expected_code=(
                "REVIEW_QUEUE_LOAD_FAILED"
            ),
        )


        body = (
            response.json()
        )


        serialized = str(
            body
        )


        assert_true(
            (
                "SECRET INTERNAL DATABASE "
                "FAILURE SHOULD NOT LEAK"
            )
            not in serialized,
            (
                "Internal exception detail "
                "leaked into client response."
            ),
        )


        assert_equal(
            body[
                "error"
            ][
                "message"
            ],
            (
                "Failed to load "
                "review queue."
            ),
            (
                "Endpoint-safe HTTP 500 "
                "message should be preserved."
            ),
        )


        print(
            "[PASS] HTTP 500 exposes "
            "safe client response"
        )

        print(
            "[PASS] Internal exception "
            "detail not leaked"
        )


        # ==================================================
        # TEST 6 — POPULATED REQUEST ID
        # ==================================================
        #
        # PHASE 7C.7e CONTRACT EVOLUTION
        #
        # The placeholder introduced by Phase 7C.7a is now
        # populated by the correlation-ID middleware.
        #
        # The previous assertion:
        #
        #     request_id is None
        #
        # was migrated rather than reverting the middleware.
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 6 — POPULATED "
            "REQUEST CORRELATION ID"
        )
        print("-" * 76)


        payload_request_id = (
            body[
                "error"
            ][
                "request_id"
            ]
        )


        assert_true(
            isinstance(
                payload_request_id,
                str,
            )
            and bool(
                payload_request_id
            ),
            (
                "Phase 7C.7e should populate "
                "error.request_id with a real "
                "correlation ID."
            ),
        )


        assert_equal(
            response.headers.get(
                "X-Request-ID"
            ),
            payload_request_id,
            (
                "error.request_id must match "
                "the X-Request-ID response "
                "header."
            ),
        )


        print(
            "[PASS] Error contract exposes "
            "an authoritative request ID"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.7a CENTRAL "
            "API ERROR CONTRACT TEST PASSED"
        )
        print("=" * 76)


    finally:

        # ==================================================
        # CLIENT CLEANUP
        # ==================================================

        if client is not None:

            client.close()


        # ==================================================
        # RESTORE APPLICATION STATE
        # ==================================================

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


        if (
            original_reviewer_identity
            is not None
        ):

            app.state.reviewer_identity = (
                original_reviewer_identity
            )


        elif hasattr(
            app.state,
            "reviewer_identity",
        ):

            delattr(
                app.state,
                "reviewer_identity",
            )


        print()
        print(
            "[CLEANUP] Phase 7C.7a "
            "temporary API state removed."
        )


if __name__ == "__main__":

    main()