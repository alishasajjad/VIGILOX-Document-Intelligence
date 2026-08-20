from concurrent.futures import (
    ThreadPoolExecutor,
)

from threading import Barrier

from fastapi.testclient import (
    TestClient,
)

from sqlalchemy import (
    func,
    select,
)

from backend.app.main import (
    app,
)

from database.database import (
    SessionLocal,
)

from database.models import (
    AuditEventModel,
    DocumentModel,
    HumanReviewModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from database.repositories import (
    HumanReviewRepository,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)

from backend.app.services.reviewer_identity_service import (
    ReviewerIdentityService,
)


# ==========================================================
# TEST PIPELINE RESULT
# ==========================================================

def build_pipeline_result() -> dict:

    issue = {
        "code":
            "DOCUMENT_EXPIRED",

        "severity":
            "WARNING",

        "field":
            "expiry_date",

        "message":
            (
                "The document has passed "
                "its validated expiry date."
            ),
    }


    return {
        "extraction": {
            "document_type":
                "guard_license",

            "full_name": {
                "value":
                    "PHASE 7C TEST USER",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "P7C123456",

                "source_line_ids": [
                    "L2"
                ],
            },

            "id_number": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "expiry_date": {
                "value":
                    "2026-01-01",

                "source_line_ids": [
                    "L4",
                    "L5",
                ],
            },

            "date_of_birth": {
                "value":
                    "1990-01-01",

                "source_line_ids": [
                    "L6",
                    "L7",
                ],
            },

            "issue_date": {
                "value":
                    "2025-01-01",

                "source_line_ids": [
                    "L3"
                ],
            },

            "issuer": {
                "value":
                    "TX DPS",

                "source_line_ids": [
                    "L8"
                ],
            },
        },

        "ocr_lines": [
            {
                "text":
                    "PHASE 7C TEST USER",

                "confidence":
                    0.999,

                "bbox":
                    [10, 10, 200, 30],
            },

            {
                "text":
                    "LICENSE",

                "confidence":
                    0.999,

                "bbox":
                    [10, 40, 90, 60],
            },

            {
                "text":
                    "P7C123456",

                "confidence":
                    0.999,

                "bbox":
                    [100, 40, 200, 60],
            },

            {
                "text":
                    "PRINTDATE 01/01/2025",

                "confidence":
                    0.999,

                "bbox":
                    [10, 70, 230, 90],
            },

            {
                "text":
                    "EXPIRES",

                "confidence":
                    0.999,

                "bbox":
                    [10, 100, 90, 120],
            },

            {
                "text":
                    "01/01/2026",

                "confidence":
                    0.999,

                "bbox":
                    [100, 100, 200, 120],
            },

            {
                "text":
                    "DOB",

                "confidence":
                    0.999,

                "bbox":
                    [10, 130, 50, 150],
            },

            {
                "text":
                    "01/01/1990",

                "confidence":
                    0.999,

                "bbox":
                    [60, 130, 170, 150],
            },

            {
                "text":
                    "ISSUED BY TX DPS",

                "confidence":
                    0.989,

                "bbox":
                    [10, 160, 210, 180],
            },
        ],

        "evidence_flags":
            [],

        "field_confidence": {
            "full_name":
                0.999,

            "licence_number":
                0.999,

            "id_number":
                None,

            "expiry_date":
                0.999,

            "date_of_birth":
                0.999,

            "issue_date":
                0.999,

            "issuer":
                0.989,
        },

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    "2026-01-01",

                "status":
                    "EXPIRED",

                "days_until_expiry":
                    -230,
            },

            "logical_issues":
                [],

            "valid":
                True,
        },

        "anomaly_validation": {
            "document_type":
                "guard_license",

            "valid":
                True,

            "has_anomalies":
                True,

            "error_count":
                0,

            "warning_count":
                1,

            "issues": [
                issue
            ],
        },

        "review_decision": {
            "decision":
                "REVIEW_REQUIRED",

            "review_required":
                True,

            "priority":
                "MEDIUM",

            "reason_codes": [
                "DOCUMENT_EXPIRED"
            ],

            "issues": [
                issue
            ],
        },
    }


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


# ==========================================================
# REVIEWER AUTH HEADERS
# PHASE 7C.5
# ==========================================================

def reviewer_headers(
    reviewer_id: str,
    role: str = "REVIEWER",
) -> dict[str, str]:

    return {
        "X-VIGILOX-REVIEWER-ID":
            reviewer_id,

        "X-VIGILOX-REVIEWER-ROLE":
            role,
    }


# ==========================================================
# CREATE TEMPORARY DOCUMENT
# ==========================================================

def create_test_document(
    persistence_service: PersistenceService,
    filename: str,
) -> str:

    stored = (
        persistence_service
        .save_processed_document(
            original_filename=(
                filename
            ),

            content_type=(
                "image/jpeg"
            ),

            pipeline_result=(
                build_pipeline_result()
            ),
        )
    )


    return stored[
        "document_id"
    ]


# ==========================================================
# COUNT HUMAN REVIEWS
# ==========================================================

def count_human_reviews(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    HumanReviewModel.id
                )
            )
            .where(
                HumanReviewModel.document_id
                == document_id
            )
        )


        return (
            session.scalar(
                statement
            )
            or 0
        )


# ==========================================================
# COUNT HUMAN REVIEW AUDIT EVENTS
# ==========================================================

def count_human_review_audits(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    AuditEventModel.id
                )
            )
            .where(
                AuditEventModel.document_id
                == document_id
            )
            .where(
                AuditEventModel.event_type
                == "HUMAN_REVIEW"
            )
        )


        return (
            session.scalar(
                statement
            )
            or 0
        )


# ==========================================================
# GET SINGLE HUMAN REVIEW
# ==========================================================

def get_human_review(
    document_id: str,
) -> HumanReviewModel:

    with SessionLocal() as session:

        statement = (
            select(
                HumanReviewModel
            )
            .where(
                HumanReviewModel.document_id
                == document_id
            )
        )


        review = (
            session
            .scalars(
                statement
            )
            .one()
        )


        _ = (
            review.id,
            review.reviewer_id,
            review.human_action,
            review.corrections,
        )


        return review


# ==========================================================
# VERIFY DOCUMENT IS NOT IN PENDING QUEUE
# ==========================================================

def assert_not_in_queue(
    client: TestClient,
    document_id: str,
):

    response = client.get(
        "/api/v1/reviews/queue"
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Review queue request "
            "should return HTTP 200."
        ),
    )


    document_ids = {
        item[
            "document_id"
        ]
        for item
        in response.json()[
            "documents"
        ]
    }


    if (
        document_id
        in document_ids
    ):

        raise AssertionError(
            (
                "Reviewed document should "
                "not remain in the pending "
                "review queue."
            )
        )


# ==========================================================
# VERIFY ORIGINAL MACHINE EXTRACTION
# ==========================================================

def assert_machine_extraction_preserved(
    client: TestClient,
    document_id: str,
):

    response = client.get(
        (
            "/api/v1/documents/"
            f"{document_id}"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Reviewed document should "
            "remain retrievable."
        ),
    )


    analysis = (
        response.json()[
            "analysis"
        ]
    )


    assert_equal(
        analysis[
            "extraction"
        ][
            "expiry_date"
        ][
            "value"
        ],
        "2026-01-01",
        (
            "Original machine expiry date "
            "must remain unchanged."
        ),
    )


    assert_equal(
        analysis[
            "extraction"
        ][
            "issuer"
        ][
            "value"
        ],
        "TX DPS",
        (
            "Original machine issuer "
            "must remain unchanged."
        ),
    )


# ==========================================================
# CONCURRENT API REQUEST
# PHASE 7C.5 AUTHENTICATED REVIEWER
# ==========================================================

def submit_concurrent_review(
    document_id: str,
    reviewer_id: str,
    action: str,
) -> tuple[
    int,
    dict,
]:

    client = (
        TestClient(
            app
        )
    )


    try:

        response = client.post(
            (
                "/api/v1/documents/"
                f"{document_id}"
                "/reviews"
            ),

            headers=reviewer_headers(
                reviewer_id
            ),

            json={
                "action":
                    action,

                "notes":
                    (
                        "Phase 7C.1 concurrent "
                        "review test."
                    ),
            },
        )


        try:

            body = (
                response.json()
            )

        except Exception:

            body = {
                "raw":
                    response.text
            }


        return (
            response.status_code,
            body,
        )


    finally:

        client.close()


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.1 — DUPLICATE / "
        "CONCURRENT REVIEW PROTECTION TEST"
    )
    print("=" * 76)


    persistence_service = (
        PersistenceService()
    )


    client = None


    created_document_ids: list[str] = []


    original_has_review_method = (
        HumanReviewRepository
        .has_review_for_document
    )


    try:

        # ==================================================
        # INITIALIZE APPLICATION SERVICES
        # ==================================================

        app.state.persistence = (
            persistence_service
        )


        app.state.document_query = (
            DocumentQueryService()
        )


        app.state.human_review = (
            HumanReviewService()
        )


        app.state.reviewer_identity = (
            ReviewerIdentityService(
                mode="trusted_headers"
            )
        )


        client = (
            TestClient(
                app
            )
        )


        print()
        print(
            "[OK] Phase 7C.1 test "
            "services initialized"
        )


        # ==================================================
        # TEST 1
        # SEQUENTIAL DUPLICATE REVIEW
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — SEQUENTIAL DUPLICATE REVIEW"
        )
        print("-" * 76)


        sequential_document_id = (
            create_test_document(
                persistence_service,
                (
                    "phase7c_sequential_"
                    "duplicate.jpg"
                ),
            )
        )


        created_document_ids.append(
            sequential_document_id
        )


        # ==================================================
        # FIRST REVIEW
        # ==================================================

        response = client.post(
            (
                "/api/v1/documents/"
                f"{sequential_document_id}"
                "/reviews"
            ),

            headers=reviewer_headers(
                "phase7c-reviewer-a"
            ),

            json={
                "action":
                    "APPROVE",

                "notes":
                    (
                        "First accepted "
                        "human review."
                    ),
            },
        )


        assert_equal(
            response.status_code,
            200,
            (
                "First human review should "
                "return HTTP 200."
            ),
        )


        assert_equal(
            response.json()[
                "human_action"
            ],
            "APPROVE",
            (
                "First human action "
                "should be APPROVE."
            ),
        )


        print(
            "[PASS] First human review "
            "accepted with HTTP 200"
        )


        # ==================================================
        # SECOND SEQUENTIAL REVIEW
        # ==================================================

        response = client.post(
            (
                "/api/v1/documents/"
                f"{sequential_document_id}"
                "/reviews"
            ),

            headers=reviewer_headers(
                "phase7c-reviewer-b"
            ),

            json={
                "action":
                    "REJECT",

                "notes":
                    (
                        "This duplicate review "
                        "must be rejected."
                    ),
            },
        )


        assert_equal(
            response.status_code,
            409,
            (
                "Second human review should "
                "return HTTP 409."
            ),
        )


        assert_equal(
            response.json().get(
                "detail"
            ),
            (
                "Document has already "
                "been reviewed."
            ),
            (
                "Unexpected duplicate "
                "review error message."
            ),
        )


        print(
            "[PASS] Sequential duplicate "
            "review rejected with HTTP 409"
        )


        # ==================================================
        # VERIFY ONE REVIEW
        # ==================================================

        assert_equal(
            count_human_reviews(
                sequential_document_id
            ),
            1,
            (
                "Sequential duplicate test "
                "must contain exactly one "
                "human review."
            ),
        )


        print(
            "[PASS] Exactly one "
            "human_reviews row persisted"
        )


        # ==================================================
        # VERIFY ONE HUMAN AUDIT
        # ==================================================

        assert_equal(
            count_human_review_audits(
                sequential_document_id
            ),
            1,
            (
                "Sequential duplicate test "
                "must contain exactly one "
                "HUMAN_REVIEW audit event."
            ),
        )


        print(
            "[PASS] Exactly one HUMAN_REVIEW "
            "audit event persisted"
        )


        # ==================================================
        # VERIFY ORIGINAL WINNING REVIEW
        # ==================================================

        review = (
            get_human_review(
                sequential_document_id
            )
        )


        assert_equal(
            review.reviewer_id,
            "phase7c-reviewer-a",
            (
                "The first authenticated "
                "reviewer should remain "
                "authoritative."
            ),
        )


        assert_equal(
            review.human_action,
            "APPROVE",
            (
                "The first APPROVE decision "
                "should remain authoritative."
            ),
        )


        print(
            "[PASS] First human review "
            "remains authoritative"
        )


        assert_not_in_queue(
            client,
            sequential_document_id,
        )


        print(
            "[PASS] Sequentially reviewed "
            "document removed from queue"
        )


        assert_machine_extraction_preserved(
            client,
            sequential_document_id,
        )


        print(
            "[PASS] Machine extraction "
            "remains unchanged"
        )


        # ==================================================
        # TEST 2
        # FORCED DATABASE-LEVEL CONCURRENCY RACE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — CONCURRENT DATABASE RACE"
        )
        print("-" * 76)


        concurrent_document_id = (
            create_test_document(
                persistence_service,
                (
                    "phase7c_concurrent_"
                    "duplicate.jpg"
                ),
            )
        )


        created_document_ids.append(
            concurrent_document_id
        )


        concurrency_barrier = (
            Barrier(
                2
            )
        )


        def forced_concurrent_precheck(
            self,
            document_id: str,
        ) -> bool:

            concurrency_barrier.wait(
                timeout=10
            )


            return False


        HumanReviewRepository.has_review_for_document = (
            forced_concurrent_precheck
        )


        # ==================================================
        # SEND BOTH AUTHENTICATED REQUESTS AT SAME TIME
        # ==================================================

        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:

            future_a = (
                executor.submit(
                    submit_concurrent_review,
                    concurrent_document_id,
                    "phase7c-concurrent-a",
                    "APPROVE",
                )
            )


            future_b = (
                executor.submit(
                    submit_concurrent_review,
                    concurrent_document_id,
                    "phase7c-concurrent-b",
                    "REJECT",
                )
            )


            result_a = (
                future_a.result(
                    timeout=30
                )
            )


            result_b = (
                future_b.result(
                    timeout=30
                )
            )


        HumanReviewRepository.has_review_for_document = (
            original_has_review_method
        )


        results = [
            result_a,
            result_b,
        ]


        status_codes = sorted(
            result[
                0
            ]
            for result
            in results
        )


        assert_equal(
            status_codes,
            [
                200,
                409,
            ],
            (
                "Concurrent review race must "
                "produce exactly one HTTP 200 "
                "and one HTTP 409."
            ),
        )


        print(
            "[PASS] Concurrent race produced "
            "one HTTP 200 and one HTTP 409"
        )


        # ==================================================
        # VERIFY LOSING RESPONSE
        # ==================================================

        conflict_results = [
            result
            for result
            in results
            if (
                result[
                    0
                ]
                == 409
            )
        ]


        assert_equal(
            len(
                conflict_results
            ),
            1,
            (
                "Exactly one concurrent "
                "request must conflict."
            ),
        )


        conflict_body = (
            conflict_results[
                0
            ][
                1
            ]
        )


        assert_equal(
            conflict_body.get(
                "detail"
            ),
            (
                "Document has already "
                "been reviewed."
            ),
            (
                "Concurrent loser should "
                "receive the clean HTTP 409 "
                "duplicate-review message."
            ),
        )


        print(
            "[PASS] Concurrent loser received "
            "clean duplicate-review response"
        )


        # ==================================================
        # VERIFY DATABASE CONSTRAINT RESULT
        # ==================================================

        assert_equal(
            count_human_reviews(
                concurrent_document_id
            ),
            1,
            (
                "Concurrent test must persist "
                "exactly one human review."
            ),
        )


        print(
            "[PASS] PostgreSQL retained exactly "
            "one concurrent human review"
        )


        # ==================================================
        # VERIFY TRANSACTIONAL AUDIT SAFETY
        # ==================================================

        assert_equal(
            count_human_review_audits(
                concurrent_document_id
            ),
            1,
            (
                "Concurrent race must create "
                "exactly one HUMAN_REVIEW "
                "audit event."
            ),
        )


        print(
            "[PASS] Losing transaction created "
            "no duplicate HUMAN_REVIEW audit"
        )


        # ==================================================
        # DISPLAY WINNING REVIEW
        # ==================================================

        winning_review = (
            get_human_review(
                concurrent_document_id
            )
        )


        print(
            (
                "[INFO] Concurrent winner: "
                f"{winning_review.reviewer_id} "
                f"→ "
                f"{winning_review.human_action}"
            )
        )


        if (
            winning_review.reviewer_id
            not in {
                "phase7c-concurrent-a",
                "phase7c-concurrent-b",
            }
        ):

            raise AssertionError(
                "Unexpected concurrent "
                "winning reviewer."
            )


        if (
            winning_review.human_action
            not in {
                "APPROVE",
                "REJECT",
            }
        ):

            raise AssertionError(
                "Unexpected concurrent "
                "winning action."
            )


        print(
            "[PASS] Winning concurrent review "
            "stored correctly"
        )


        # ==================================================
        # QUEUE REMOVAL
        # ==================================================

        assert_not_in_queue(
            client,
            concurrent_document_id,
        )


        print(
            "[PASS] Concurrently reviewed "
            "document removed from queue"
        )


        # ==================================================
        # MACHINE PROVENANCE
        # ==================================================

        assert_machine_extraction_preserved(
            client,
            concurrent_document_id,
        )


        print(
            "[PASS] Machine extraction preserved "
            "after concurrent review"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.1 DUPLICATE / "
            "CONCURRENT REVIEW PROTECTION TEST PASSED"
        )
        print("=" * 76)


    finally:

        # ==================================================
        # RESTORE MONKEYPATCH
        # ==================================================

        HumanReviewRepository.has_review_for_document = (
            original_has_review_method
        )


        # ==================================================
        # CLOSE CLIENT
        # ==================================================

        if client is not None:

            client.close()


        # ==================================================
        # DATABASE CLEANUP
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


        # ==================================================
        # STORAGE CLEANUP
        # ==================================================

        for document_id in (
            created_document_ids
        ):

            (
                persistence_service
                .storage_service
                .delete_document(
                    document_id
                )
            )


        # ==================================================
        # APP STATE CLEANUP
        # ==================================================

        for state_name in (
            "persistence",
            "document_query",
            "human_review",
            "reviewer_identity",
        ):

            if hasattr(
                app.state,
                state_name,
            ):

                delattr(
                    app.state,
                    state_name,
                )


        print()
        print(
            "[CLEANUP] Phase 7C.1 temporary "
            "documents, reviews and audits removed."
        )


if __name__ == "__main__":

    main()