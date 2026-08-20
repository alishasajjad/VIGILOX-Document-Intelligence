import tempfile

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
)

from database.repositories import (
    DuplicateHumanReviewError,
)

from backend.app.services.document_storage_service import (
    DocumentStorageService,
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


def assert_true(
    condition: bool,
    message: str,
):

    if not condition:

        raise AssertionError(
            message
        )


def assert_error(
    response,
    *,
    status_code: int,
    code: str,
):

    assert_equal(
        response.status_code,
        status_code,
        "Unexpected HTTP status.",
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
            "Expected central "
            "error contract."
        ),
    )


    assert_equal(
        body[
            "error"
        ][
            "code"
        ],
        code,
        (
            "Unexpected domain "
            "error code."
        ),
    )


    assert_true(
        "detail"
        in body,
        (
            "Legacy detail field "
            "must remain available."
        ),
    )


# ==========================================================
# QUERY SERVICES
# ==========================================================

class MissingDocumentQueryService:

    def get_document(
        self,
        document_id: str,
    ):

        return None


    def get_document_history(
        self,
        document_id: str,
    ):

        return None


class MissingImageQueryService:

    def get_document(
        self,
        document_id: str,
    ):

        return {
            "document": {
                "id":
                    document_id,

                "original_filename":
                    "missing.jpg",

                "content_type":
                    "image/jpeg",

                "processing_status":
                    "PROCESSED",
            },

            "analysis": {
                "review_decision": {
                    "decision":
                        "REVIEW_REQUIRED",
                }
            },
        }


class InvalidStoredContentTypeQueryService:

    def get_document(
        self,
        document_id: str,
    ):

        return {
            "document": {
                "id":
                    document_id,

                "original_filename":
                    "invalid.bin",

                "content_type":
                    "application/octet-stream",

                "processing_status":
                    "PROCESSED",
            },

            "analysis": {
                "review_decision": {
                    "decision":
                        "REVIEW_REQUIRED",
                }
            },
        }


class ReviewDocumentQueryService:

    def get_document(
        self,
        document_id: str,
    ):

        return {
            "document": {
                "id":
                    document_id,

                "processing_status":
                    "PROCESSED",
            },

            "analysis": {
                "review_decision": {
                    "decision":
                        "REVIEW_REQUIRED",

                    "review_required":
                        True,

                    "priority":
                        "MEDIUM",

                    "reason_codes":
                        [],
                }
            },
        }


class FailingQueueQueryService:

    def get_review_queue(
        self,
        *,
        priority=None,
        document_type=None,
    ):

        raise RuntimeError(
            "PRIVATE DB FAILURE"
        )


# ==========================================================
# HUMAN REVIEW SERVICES
# ==========================================================

class InvalidHumanReviewService:

    def submit_review(
        self,
        **kwargs,
    ):

        raise ValueError(
            "Invalid human review."
        )


class SuccessfulHumanReviewService:

    def submit_review(
        self,
        *,
        document_id,
        reviewer_id,
        review_result,
        action,
        notes,
        corrections,
    ):

        return {
            "review_id":
                "review-test",

            "document_id":
                document_id,

            "reviewer_id":
                reviewer_id,

            "machine_decision":
                "REVIEW_REQUIRED",

            "machine_priority":
                "MEDIUM",

            "machine_reason_codes":
                [],

            "human_action":
                action,

            "corrections":
                corrections or {},

            "notes":
                notes,

            "reviewed_at":
                "2026-08-20T00:00:00+00:00",
        }


# ==========================================================
# PERSISTENCE FAKES
# ==========================================================

class StorageOnlyPersistence:

    def __init__(
        self,
        storage_service,
    ):

        self.storage_service = (
            storage_service
        )


class DuplicateReviewPersistence:

    def save_human_review(
        self,
        *,
        review_result,
    ):

        raise DuplicateHumanReviewError(
            review_result[
                "document_id"
            ]
        )


class FailingReviewPersistence:

    def save_human_review(
        self,
        *,
        review_result,
    ):

        raise RuntimeError(
            "PRIVATE REVIEW DATABASE ERROR"
        )


# ==========================================================
# FAILING PIPELINE
# ==========================================================

class FailingPipeline:

    def process(
        self,
        image_path: str,
    ):

        raise RuntimeError(
            "PRIVATE PIPELINE ERROR"
        )


# ==========================================================
# REVIEW HEADERS
# ==========================================================

def reviewer_headers():

    return {
        "X-VIGILOX-REVIEWER-ID":
            "phase7c7c-reviewer",

        "X-VIGILOX-REVIEWER-ROLE":
            "REVIEWER",
    }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7c — DOMAIN "
        "ERROR MAPPING TEST"
    )
    print("=" * 76)


    client = None


    state_names = (
        "document_query",
        "persistence",
        "human_review",
        "reviewer_identity",
        "pipeline",
    )


    original_state = {
        name:
            getattr(
                app.state,
                name,
                None,
            )

        for name
        in state_names
    }


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        storage_service = (
            DocumentStorageService(
                storage_root=(
                    temp_root
                    / "documents"
                )
            )
        )


        try:

            client = TestClient(
                app,
                raise_server_exceptions=False,
            )


            app.state.reviewer_identity = (
                ReviewerIdentityService(
                    mode="trusted_headers"
                )
            )


            # ==================================================
            # TEST 1 — DOCUMENT NOT FOUND
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 1 — DOCUMENT NOT FOUND"
            )
            print("-" * 76)


            app.state.document_query = (
                MissingDocumentQueryService()
            )


            response = (
                client.get(
                    "/api/v1/documents/missing"
                )
            )


            assert_error(
                response,
                status_code=404,
                code="DOCUMENT_NOT_FOUND",
            )


            print(
                "[PASS] Document not-found "
                "mapped explicitly"
            )


            # ==================================================
            # TEST 2 — ORIGINAL IMAGE MISSING
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 2 — ORIGINAL IMAGE MISSING"
            )
            print("-" * 76)


            app.state.document_query = (
                MissingImageQueryService()
            )


            app.state.persistence = (
                StorageOnlyPersistence(
                    storage_service
                )
            )


            response = (
                client.get(
                    (
                        "/api/v1/documents/"
                        "missing-image/image"
                    )
                )
            )


            assert_error(
                response,
                status_code=404,
                code=(
                    "ORIGINAL_DOCUMENT_NOT_AVAILABLE"
                ),
            )


            print(
                "[PASS] Missing original "
                "mapped explicitly"
            )


            # ==================================================
            # TEST 3 — INVALID STORED CONTENT TYPE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 3 — INVALID STORED "
                "CONTENT TYPE"
            )
            print("-" * 76)


            app.state.document_query = (
                InvalidStoredContentTypeQueryService()
            )


            response = (
                client.get(
                    (
                        "/api/v1/documents/"
                        "invalid-content/image"
                    )
                )
            )


            assert_error(
                response,
                status_code=500,
                code=(
                    "STORED_DOCUMENT_CONTENT_TYPE_INVALID"
                ),
            )


            print(
                "[PASS] Invalid stored "
                "content type mapped"
            )


            # ==================================================
            # TEST 4 — INVALID HUMAN REVIEW
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 4 — INVALID HUMAN REVIEW"
            )
            print("-" * 76)


            app.state.document_query = (
                ReviewDocumentQueryService()
            )


            app.state.human_review = (
                InvalidHumanReviewService()
            )


            response = (
                client.post(
                    (
                        "/api/v1/documents/"
                        "review-doc/reviews"
                    ),

                    headers=(
                        reviewer_headers()
                    ),

                    json={
                        "action":
                            "APPROVE",

                        "notes":
                            None,

                        "corrections":
                            None,
                    },
                )
            )


            assert_error(
                response,
                status_code=400,
                code=(
                    "INVALID_HUMAN_REVIEW"
                ),
            )


            print(
                "[PASS] Human review domain "
                "validation mapped"
            )


            # ==================================================
            # TEST 5 — DUPLICATE REVIEW
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 5 — DUPLICATE REVIEW"
            )
            print("-" * 76)


            app.state.human_review = (
                SuccessfulHumanReviewService()
            )


            app.state.persistence = (
                DuplicateReviewPersistence()
            )


            response = (
                client.post(
                    (
                        "/api/v1/documents/"
                        "duplicate-doc/reviews"
                    ),

                    headers=(
                        reviewer_headers()
                    ),

                    json={
                        "action":
                            "APPROVE",

                        "notes":
                            None,

                        "corrections":
                            None,
                    },
                )
            )


            assert_error(
                response,
                status_code=409,
                code=(
                    "DOCUMENT_ALREADY_REVIEWED"
                ),
            )


            print(
                "[PASS] Duplicate review "
                "mapped to stable conflict code"
            )


            # ==================================================
            # TEST 6 — REVIEW PERSISTENCE FAILURE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 6 — REVIEW "
                "PERSISTENCE FAILURE"
            )
            print("-" * 76)


            app.state.persistence = (
                FailingReviewPersistence()
            )


            response = (
                client.post(
                    (
                        "/api/v1/documents/"
                        "persist-fail/reviews"
                    ),

                    headers=(
                        reviewer_headers()
                    ),

                    json={
                        "action":
                            "APPROVE",

                        "notes":
                            None,

                        "corrections":
                            None,
                    },
                )
            )


            assert_error(
                response,
                status_code=500,
                code=(
                    "HUMAN_REVIEW_PERSISTENCE_FAILED"
                ),
            )


            assert_true(
                "PRIVATE REVIEW DATABASE ERROR"
                not in str(
                    response.json()
                ),
                (
                    "Private review persistence "
                    "error leaked to client."
                ),
            )


            print(
                "[PASS] Review persistence "
                "failure sanitized and mapped"
            )


            # ==================================================
            # TEST 7 — REVIEW QUEUE FAILURE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 7 — REVIEW QUEUE FAILURE"
            )
            print("-" * 76)


            app.state.document_query = (
                FailingQueueQueryService()
            )


            response = (
                client.get(
                    "/api/v1/reviews/queue"
                )
            )


            assert_error(
                response,
                status_code=500,
                code=(
                    "REVIEW_QUEUE_LOAD_FAILED"
                ),
            )


            assert_true(
                "PRIVATE DB FAILURE"
                not in str(
                    response.json()
                ),
                (
                    "Private queue exception "
                    "leaked to client."
                ),
            )


            print(
                "[PASS] Review queue failure "
                "sanitized and mapped"
            )


            # ==================================================
            # TEST 8 — DOCUMENT PROCESSING FAILURE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 8 — DOCUMENT "
                "PROCESSING FAILURE"
            )
            print("-" * 76)


            app.state.pipeline = (
                FailingPipeline()
            )


            response = (
                client.post(
                    "/api/v1/documents/analyze",

                    files={
                        "file": (
                            "document.jpg",
                            b"valid-test-bytes",
                            "image/jpeg",
                        )
                    },
                )
            )


            assert_error(
                response,
                status_code=500,
                code=(
                    "DOCUMENT_PROCESSING_FAILED"
                ),
            )


            assert_true(
                "PRIVATE PIPELINE ERROR"
                not in str(
                    response.json()
                ),
                (
                    "Pipeline implementation "
                    "detail leaked to client."
                ),
            )


            print(
                "[PASS] Document processing "
                "failure sanitized and mapped"
            )


            # ==================================================
            # TEST 9 — HISTORY NOT FOUND
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 9 — HISTORY DOCUMENT "
                "NOT FOUND"
            )
            print("-" * 76)


            app.state.document_query = (
                MissingDocumentQueryService()
            )


            response = (
                client.get(
                    (
                        "/api/v1/documents/"
                        "missing/history"
                    )
                )
            )


            assert_error(
                response,
                status_code=404,
                code=(
                    "DOCUMENT_NOT_FOUND"
                ),
            )


            print(
                "[PASS] History not-found "
                "uses document domain code"
            )


            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.7c DOMAIN "
                "ERROR MAPPING TEST PASSED"
            )
            print("=" * 76)


        finally:

            if client is not None:

                client.close()


            for name in state_names:

                original = (
                    original_state[
                        name
                    ]
                )


                if original is not None:

                    setattr(
                        app.state,
                        name,
                        original,
                    )


                elif hasattr(
                    app.state,
                    name,
                ):

                    delattr(
                        app.state,
                        name,
                    )


            print()
            print(
                "[CLEANUP] Phase 7C.7c "
                "temporary API state removed."
            )


if __name__ == "__main__":

    main()