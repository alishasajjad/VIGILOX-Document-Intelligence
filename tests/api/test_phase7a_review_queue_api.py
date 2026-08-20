from datetime import (
    datetime,
    timedelta,
    timezone,
)
from uuid import uuid4

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import app

from database.database import (
    SessionLocal,
)

from database.models import (
    DocumentModel,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from database.repositories import (
    DocumentAnalysisRepository,
    DocumentRepository,
    HumanReviewRepository,
)


# ==========================================================
# TEST PIPELINE RESULT BUILDER
# ==========================================================

def build_pipeline_result(
    *,
    document_type: str,
    decision: str,
    priority: str,
    reason_codes: list[str] | None = None,
) -> dict:

    reason_codes = (
        reason_codes
        or []
    )

    issues = [
        {
            "code": code,
            "severity": (
                "ERROR"
                if priority == "HIGH"
                else "WARNING"
            ),
            "field": None,
            "message": (
                f"Phase 7A API test issue: "
                f"{code}"
            ),
        }
        for code in reason_codes
    ]

    return {
        "extraction": {
            "document_type":
                document_type,
        },

        "ocr_lines":
            [],

        "evidence_flags":
            [],

        "field_confidence":
            {},

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    None,

                "status":
                    "NOT_AVAILABLE",

                "days_until_expiry":
                    None,
            },

            "logical_issues":
                [],

            "valid":
                True,
        },

        "anomaly_validation": {
            "document_type":
                document_type,

            "valid":
                True,

            "has_anomalies":
                bool(reason_codes),

            "error_count": (
                len(reason_codes)
                if priority == "HIGH"
                else 0
            ),

            "warning_count": (
                len(reason_codes)
                if priority != "HIGH"
                else 0
            ),

            "issues":
                issues,
        },

        "review_decision": {
            "decision":
                decision,

            "review_required": (
                decision
                == "REVIEW_REQUIRED"
            ),

            "priority":
                priority,

            "reason_codes":
                reason_codes,

            "issues":
                issues,
        },
    }


# ==========================================================
# ASSERTION HELPER
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


# ==========================================================
# FILTER ONLY TEMPORARY TEST DOCUMENTS
# ==========================================================

def get_test_items(
    response_body: dict,
    document_ids: set[str],
) -> list[dict]:

    return [
        item
        for item
        in response_body[
            "documents"
        ]
        if (
            item["document_id"]
            in document_ids
        )
    ]


# ==========================================================
# MAIN TEST
# ==========================================================

def main():

    print()
    print("=" * 72)
    print(
        "PHASE 7A — REVIEW QUEUE "
        "FASTAPI TEST"
    )
    print("=" * 72)

    created_document_ids: list[str] = []

    client = None


    try:

        # ==================================================
        # 1. CREATE TEMPORARY DATABASE RECORDS
        # ==================================================

        with SessionLocal() as session:

            document_repository = (
                DocumentRepository(
                    session
                )
            )

            analysis_repository = (
                DocumentAnalysisRepository(
                    session
                )
            )

            human_review_repository = (
                HumanReviewRepository(
                    session
                )
            )


            base_time = datetime(
                2026,
                8,
                19,
                9,
                0,
                0,
                tzinfo=timezone.utc,
            )


            # ==============================================
            # HIGH — PENDING
            # ==============================================

            high_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_api_high.jpg"
                    ),
                    content_type=(
                        "image/jpeg"
                    ),
                    document_type=(
                        "guard_license"
                    ),
                )
            )

            high_document.created_at = (
                base_time
                + timedelta(
                    minutes=4
                )
            )

            analysis_repository.create_analysis(
                document_id=(
                    high_document.id
                ),
                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "guard_license"
                        ),
                        decision=(
                            "REVIEW_REQUIRED"
                        ),
                        priority="HIGH",
                        reason_codes=[
                            "MISSING_CRITICAL_FIELD"
                        ],
                    )
                ),
            )

            created_document_ids.append(
                high_document.id
            )


            # ==============================================
            # MEDIUM — PENDING
            # ==============================================

            medium_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_api_medium.jpg"
                    ),
                    content_type=(
                        "image/jpeg"
                    ),
                    document_type=(
                        "sia_badge"
                    ),
                )
            )

            medium_document.created_at = (
                base_time
                + timedelta(
                    minutes=2
                )
            )

            analysis_repository.create_analysis(
                document_id=(
                    medium_document.id
                ),
                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "sia_badge"
                        ),
                        decision=(
                            "REVIEW_REQUIRED"
                        ),
                        priority="MEDIUM",
                        reason_codes=[
                            "DOCUMENT_EXPIRED"
                        ],
                    )
                ),
            )

            created_document_ids.append(
                medium_document.id
            )


            # ==============================================
            # LOW — PENDING
            # ==============================================

            low_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_api_low.jpg"
                    ),
                    content_type=(
                        "image/jpeg"
                    ),
                    document_type=(
                        "id_card"
                    ),
                )
            )

            low_document.created_at = (
                base_time
                + timedelta(
                    minutes=1
                )
            )

            analysis_repository.create_analysis(
                document_id=(
                    low_document.id
                ),
                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "id_card"
                        ),
                        decision=(
                            "REVIEW_REQUIRED"
                        ),
                        priority="LOW",
                        reason_codes=[
                            "EXPIRING_SOON"
                        ],
                    )
                ),
            )

            created_document_ids.append(
                low_document.id
            )


            # ==============================================
            # AUTO ACCEPT — MUST NOT APPEAR
            # ==============================================

            auto_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_api_auto.jpg"
                    ),
                    content_type=(
                        "image/jpeg"
                    ),
                    document_type=(
                        "id_card"
                    ),
                )
            )

            auto_document.created_at = (
                base_time
            )

            analysis_repository.create_analysis(
                document_id=(
                    auto_document.id
                ),
                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "id_card"
                        ),
                        decision=(
                            "AUTO_ACCEPT"
                        ),
                        priority="NONE",
                        reason_codes=[],
                    )
                ),
            )

            created_document_ids.append(
                auto_document.id
            )


            # ==============================================
            # ALREADY REVIEWED — MUST NOT APPEAR
            # ==============================================

            reviewed_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_api_reviewed.jpg"
                    ),
                    content_type=(
                        "image/jpeg"
                    ),
                    document_type=(
                        "guard_license"
                    ),
                )
            )

            reviewed_document.created_at = (
                base_time
            )

            analysis_repository.create_analysis(
                document_id=(
                    reviewed_document.id
                ),
                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "guard_license"
                        ),
                        decision=(
                            "REVIEW_REQUIRED"
                        ),
                        priority="HIGH",
                        reason_codes=[
                            "INVALID_EVIDENCE"
                        ],
                    )
                ),
            )

            human_review_repository.create_review(
                review_result={
                    "review_id":
                        str(uuid4()),

                    "document_id":
                        reviewed_document.id,

                    "reviewer_id":
                        "phase7a-api-reviewer",

                    "machine_decision":
                        "REVIEW_REQUIRED",

                    "machine_priority":
                        "HIGH",

                    "machine_reason_codes": [
                        "INVALID_EVIDENCE"
                    ],

                    "human_action":
                        "APPROVE",

                    "corrections":
                        {},

                    "notes":
                        (
                            "Phase 7A API "
                            "test review."
                        ),

                    "reviewed_at":
                        (
                            datetime.now(
                                timezone.utc
                            ).isoformat()
                        ),
                }
            )

            created_document_ids.append(
                reviewed_document.id
            )


            session.commit()


        print(
            "[OK] Temporary API test "
            "documents created"
        )


        pending_ids = {
            high_document.id,
            medium_document.id,
            low_document.id,
        }

        all_test_ids = set(
            created_document_ids
        )


        # ==================================================
        # 2. PREPARE FASTAPI TEST CLIENT
        # ==================================================
        #
        # This endpoint only needs DocumentQueryService.
        # We inject it directly so this focused API test
        # does not initialize PaddleOCR / LLM pipeline.
        # ==================================================

        app.state.document_query = (
            DocumentQueryService()
        )

        client = TestClient(
            app
        )


        # ==================================================
        # TEST 1 — DEFAULT QUEUE
        # ==================================================

        response = client.get(
            "/api/v1/reviews/queue"
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Default review queue "
                "should return HTTP 200."
            ),
        )


        body = response.json()


        # Response-model fields
        for required_key in (
            "total",
            "filters",
            "documents",
        ):

            if required_key not in body:

                raise AssertionError(
                    "Response is missing "
                    f"required key: "
                    f"{required_key}"
                )


        print(
            "[PASS] GET /api/v1/reviews/queue "
            "returns HTTP 200"
        )

        print(
            "[PASS] Response schema "
            "contains required fields"
        )


        # ==================================================
        # TEST 2 — PENDING TEST DOCUMENTS APPEAR
        # ==================================================

        test_items = (
            get_test_items(
                body,
                pending_ids,
            )
        )


        test_names = [
            item[
                "original_filename"
            ]
            for item
            in test_items
        ]


        expected_names = [
            "phase7a_api_high.jpg",
            "phase7a_api_medium.jpg",
            "phase7a_api_low.jpg",
        ]


        assert_equal(
            test_names,
            expected_names,
            (
                "Pending API test "
                "documents are missing "
                "or incorrectly ordered."
            ),
        )


        print(
            "[PASS] REVIEW_REQUIRED "
            "documents returned"
        )

        print(
            "[PASS] HIGH → MEDIUM → LOW "
            "ordering returned by API"
        )


        # ==================================================
        # TEST 3 — AUTO ACCEPT EXCLUDED
        # ==================================================

        body_ids = {
            item["document_id"]
            for item
            in body["documents"]
        }


        assert_equal(
            auto_document.id
            in body_ids,
            False,
            (
                "AUTO_ACCEPT document "
                "must not appear in API queue."
            ),
        )


        print(
            "[PASS] AUTO_ACCEPT excluded"
        )


        # ==================================================
        # TEST 4 — HUMAN REVIEWED EXCLUDED
        # ==================================================

        assert_equal(
            reviewed_document.id
            in body_ids,
            False,
            (
                "Human-reviewed document "
                "must not appear in API queue."
            ),
        )


        print(
            "[PASS] Human-reviewed "
            "document excluded"
        )


        # ==================================================
        # TEST 5 — PRIORITY FILTER + NORMALIZATION
        # ==================================================

        response = client.get(
            "/api/v1/reviews/queue",
            params={
                "priority":
                    "high"
            },
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Lowercase priority filter "
                "should be accepted."
            ),
        )


        high_body = (
            response.json()
        )


        assert_equal(
            high_body[
                "filters"
            ][
                "priority"
            ],
            "HIGH",
            (
                "Priority should normalize "
                "to HIGH."
            ),
        )


        high_test_items = (
            get_test_items(
                high_body,
                all_test_ids,
            )
        )


        assert_equal(
            len(high_test_items),
            1,
            (
                "HIGH filter should return "
                "one Phase 7A API test item."
            ),
        )


        assert_equal(
            high_test_items[0][
                "document_id"
            ],
            high_document.id,
            (
                "Incorrect HIGH priority "
                "test document returned."
            ),
        )


        print(
            "[PASS] Priority filter"
        )

        print(
            "[PASS] Priority normalization"
        )


        # ==================================================
        # TEST 6 — DOCUMENT TYPE FILTER
        # ==================================================

        response = client.get(
            "/api/v1/reviews/queue",
            params={
                "document_type":
                    "ID_CARD"
            },
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Uppercase document_type "
                "should be accepted."
            ),
        )


        id_body = (
            response.json()
        )


        assert_equal(
            id_body[
                "filters"
            ][
                "document_type"
            ],
            "id_card",
            (
                "Document type should "
                "normalize to id_card."
            ),
        )


        id_test_items = (
            get_test_items(
                id_body,
                all_test_ids,
            )
        )


        assert_equal(
            len(id_test_items),
            1,
            (
                "ID card filter should "
                "return one pending "
                "Phase 7A test item."
            ),
        )


        assert_equal(
            id_test_items[0][
                "document_id"
            ],
            low_document.id,
            (
                "Incorrect ID-card "
                "test document returned."
            ),
        )


        print(
            "[PASS] Document-type filter"
        )

        print(
            "[PASS] Document-type "
            "normalization"
        )


        # ==================================================
        # TEST 7 — COMBINED FILTER
        # ==================================================

        response = client.get(
            "/api/v1/reviews/queue",
            params={
                "priority":
                    "MEDIUM",

                "document_type":
                    "sia_badge",
            },
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Combined filters should "
                "return HTTP 200."
            ),
        )


        combined_body = (
            response.json()
        )


        combined_test_items = (
            get_test_items(
                combined_body,
                all_test_ids,
            )
        )


        assert_equal(
            len(combined_test_items),
            1,
            (
                "Combined filter should "
                "return one Phase 7A item."
            ),
        )


        assert_equal(
            combined_test_items[0][
                "document_id"
            ],
            medium_document.id,
            (
                "Combined filter returned "
                "incorrect document."
            ),
        )


        print(
            "[PASS] Combined filters"
        )


        # ==================================================
        # TEST 8 — INVALID PRIORITY
        # ==================================================

        response = client.get(
            "/api/v1/reviews/queue",
            params={
                "priority":
                    "CRITICAL"
            },
        )


        assert_equal(
            response.status_code,
            400,
            (
                "Invalid priority should "
                "return HTTP 400."
            ),
        )


        print(
            "[PASS] Invalid priority "
            "rejected with HTTP 400"
        )


        # ==================================================
        # TEST 9 — INVALID DOCUMENT TYPE
        # ==================================================

        response = client.get(
            "/api/v1/reviews/queue",
            params={
                "document_type":
                    "passport"
            },
        )


        assert_equal(
            response.status_code,
            400,
            (
                "Invalid document type "
                "should return HTTP 400."
            ),
        )


        print(
            "[PASS] Invalid document type "
            "rejected with HTTP 400"
        )


        # ==================================================
        # TEST 10 — EMPTY FILTERED TEST RESULT
        # ==================================================

        response = client.get(
            "/api/v1/reviews/queue",
            params={
                "priority":
                    "HIGH",

                "document_type":
                    "id_card",
            },
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Valid empty filter should "
                "return HTTP 200."
            ),
        )


        empty_body = (
            response.json()
        )


        empty_test_items = (
            get_test_items(
                empty_body,
                all_test_ids,
            )
        )


        assert_equal(
            empty_test_items,
            [],
            (
                "Expected no Phase 7A "
                "HIGH-priority ID-card."
            ),
        )


        print(
            "[PASS] Empty valid filtered "
            "result handled correctly"
        )


        # ==================================================
        # EXISTING DATABASE RECORDS
        # ==================================================

        existing_items = [
            item
            for item
            in body["documents"]
            if (
                item["document_id"]
                not in all_test_ids
            )
        ]


        print()
        print(
            "Existing non-test pending "
            "documents returned by API: "
            f"{len(existing_items)}"
        )


        for item in existing_items:

            print(
                "  - "
                f"{item['original_filename']} "
                f"({item['review_priority']})"
            )


        # ==================================================
        # SUCCESS
        # ==================================================

        print()
        print("=" * 72)
        print(
            "[PASS] PHASE 7A REVIEW QUEUE "
            "FASTAPI TEST PASSED"
        )
        print("=" * 72)


    finally:

        # ==================================================
        # CLOSE TEST CLIENT
        # ==================================================

        if client is not None:

            client.close()


        # ==================================================
        # CLEANUP TEMPORARY DB DATA
        # ==================================================

        if created_document_ids:

            with SessionLocal() as session:

                for document_id in (
                    created_document_ids
                ):

                    document = (
                        session.get(
                            DocumentModel,
                            document_id,
                        )
                    )


                    if document is not None:

                        session.delete(
                            document
                        )


                session.commit()


            print()
            print(
                "[CLEANUP] Temporary "
                "Phase 7A API test "
                "documents removed."
            )


        # Remove manually injected state.
        if hasattr(
            app.state,
            "document_query",
        ):

            del app.state.document_query


if __name__ == "__main__":

    main()